"""
네이버 로그인 관리 (순위 조회 전에 run_and_publish.bat 이 실행). 패키지(순위체크_프로그램)는 수정하지 않고 그 common.py 를 가져다 쓴다.
  python naver_guard.py check     # 세션 확인 → 필요하면 자동 로그인 1회 또는 로그인 창. 0=이미 로그인, 10=새로 로그인함, 1=로그인 못 함
  python naver_guard.py weekly    # 주간 직접 로그인: 로그아웃 후 로그인 창 (스케줄러 월요일 09:40)
  python naver_guard.py login     # 지금 로그인 창 띄우기 (캡차로 막혔을 때 등)
  python naver_guard.py set       # 자동 로그인 계정 저장 (아이디·비밀번호를 이 창에서 직접 입력, 화면에 안 보임)
  python naver_guard.py status

규칙 (2026-10-20 결정)
- 자동 로그인은 이 스크립트만 한 번 시도한다. 패키지가 스스로 재로그인하지 못하게 credentials.json 은
  guard_credentials.json 으로 옮겨 둔다 (login.py --set 으로 다시 생겨도 다음 실행 때 옮김).
- 자동 로그인이 한 번이라도 실패하면(캡차·추가 인증·비밀번호 오류) 더 시도하지 않고 'blocked' 로 표시한 뒤
  로그인 창을 띄운다. 사람이 직접 로그인해야 풀린다.
- 마지막 직접 로그인 후 7일이 지나면 자동 로그인 대신 로그인 창을 띄운다.
"""
import asyncio
import getpass
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PKG = next(p.parent for p in sorted(ROOT.rglob("rank.py"))
           if p.parent.name == "순위체크_프로그램" and "_backup" not in p.parts)
sys.path.insert(0, str(PKG))
from playwright.async_api import async_playwright  # noqa: E402
from common import (launch, is_logged_in, ensure_logged_in, keep_login_checked, save_state, read_login_id,  # noqa: E402
                    save_login_info, auto_login, PROFILE_DIR, STATE_FILE, CRED_FILE)

GUARD_CRED = CRED_FILE.parent / "guard_credentials.json"
GUARD_STATE = CRED_FILE.parent / "guard.json"
MANUAL_EVERY = timedelta(days=7)
WAIT_CHECK_MIN = 15     # 조회 직전 로그인 창 대기
WAIT_WEEKLY_MIN = 25    # 주간 로그인 창 대기 (09:40 → 10:05)
LOGIN_URL = "https://nid.naver.com/nidlogin.login?url=https%3A%2F%2Fwww.naver.com"
CAPTCHA_HINTS = ("captcha", "자동입력 방지", "자동입력방지", "보안문자")
VERIFY_HINTS = ("2단계", "새로운 환경", "새로운 기기", "본인확인", "deviceConfirm", "2step")


def log(msg: str):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [guard] {msg}", flush=True)


def load_state() -> dict:
    try:
        return json.loads(GUARD_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_guard(st: dict):
    GUARD_STATE.parent.mkdir(parents=True, exist_ok=True)
    GUARD_STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def migrate_creds():
    """패키지가 자동 로그인하지 못하게 계정 파일을 옮긴다"""
    if CRED_FILE.exists():
        CRED_FILE.replace(GUARD_CRED)
        log("credentials.json → guard_credentials.json 으로 옮김 (자동 로그인은 이 스크립트만 1회 시도)")


def load_cred() -> dict:
    try:
        d = json.loads(GUARD_CRED.read_text(encoding="utf-8"))
        return d if d.get("id") and d.get("pw") else {}
    except Exception:
        return {}


def manual_due(st: dict) -> bool:
    last = st.get("last_manual")
    return not last or datetime.now() - datetime.fromisoformat(last) >= MANUAL_EVERY


async def session_ok(ctx, page) -> bool:
    """쿠키가 아니라 서버가 세션을 인정하는지 (common.verify_logged_in 과 같은 기준, 재로그인은 하지 않음)"""
    if not await ensure_logged_in(ctx):
        return False
    await page.goto("https://www.naver.com", wait_until="domcontentloaded")
    await page.wait_for_timeout(1500)
    return await is_logged_in(ctx)


async def finish_login(ctx, page, st: dict, manual: bool):
    await page.goto("https://www.naver.com", wait_until="domcontentloaded")
    await page.wait_for_timeout(1500)
    await save_state(ctx)
    login_id = await read_login_id(page)
    save_login_info(login_id or load_cred().get("id", ""), True)
    keep = await keep_login_checked(ctx)
    now = datetime.now().isoformat(timespec="seconds")
    if manual:
        st.update(last_manual=now, blocked=False, blocked_reason="")
    else:
        st["last_auto"] = now
    save_guard(st)
    want = load_cred().get("id")
    if login_id and want and login_id != want:
        log(f"주의: 로그인한 계정({login_id})이 자동 로그인 계정({want})과 다릅니다 — 순위 타겟팅 기준이 달라집니다")
    log(f"로그인 완료: {login_id or '(아이디 확인 불가)'} / {'직접' if manual else '자동'} / 로그인 상태 유지: {'적용' if keep else '미적용'}")


async def manual_login(p, st: dict, wait_min: int, logout: bool) -> bool:
    ctx = await launch(p, "pc", headless=False)
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    try:
        if logout:
            try:
                await page.goto("https://nid.naver.com/nidlogin.logout?returl=https%3A%2F%2Fwww.naver.com",
                                wait_until="domcontentloaded")
            except Exception:
                pass
            await ctx.clear_cookies()
            STATE_FILE.unlink(missing_ok=True)
        elif await session_ok(ctx, page):
            await finish_login(ctx, page, st, manual=True)
            return True
        await page.goto(LOGIN_URL, wait_until="domcontentloaded")
        await page.evaluate("""() => { const k = document.querySelector('#keep, #loginStay, input[name=nvlong]');
                                       if (k && !k.checked) k.click(); }""")     # 로그인 상태 유지 미리 체크
        log(f"로그인 창을 띄웠습니다. 창에서 직접 로그인해 주세요 ('로그인 상태 유지' 체크). 최대 {wait_min}분 대기")
        for _ in range(wait_min * 60):
            await asyncio.sleep(1)
            if await is_logged_in(ctx):
                await finish_login(ctx, page, st, manual=True)
                return True
        log("시간 안에 로그인하지 않았습니다. 'python naver_guard.py login' 으로 다시 띄울 수 있습니다")
        return False
    finally:
        await ctx.close()


async def try_auto_login(p, st: dict) -> bool:
    cred = load_cred()
    if not cred:
        log("자동 로그인 계정 없음")
        return False
    ctx = await launch(p, "pc", headless=True)
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    try:
        await ctx.clear_cookies()
        log(f"자동 로그인 1회 시도 ({cred['id']})")
        try:
            ok = await auto_login(ctx, page, cred)
        except Exception as e:
            ok, html = False, f"error {e}"
        if ok:
            await finish_login(ctx, page, st, manual=False)
            return True
        try:
            html = (page.url + await page.content())
        except Exception:
            html = ""
        reason = ("캡차" if any(h in html for h in CAPTCHA_HINTS) else
                  "추가 인증" if any(h in html for h in VERIFY_HINTS) else "아이디·비밀번호 또는 기타")
        st.update(blocked=True, blocked_reason=reason, blocked_at=datetime.now().isoformat(timespec="seconds"))
        save_guard(st)
        log(f"자동 로그인 실패({reason}) → 자동 로그인을 멈춥니다. 직접 로그인해야 다시 풀립니다")
        return False
    finally:
        await ctx.close()


async def check() -> int:
    st = load_state()
    async with async_playwright() as p:
        ctx = await launch(p, "pc", headless=True)
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        ok = await session_ok(ctx, page)
        await ctx.close()
        if ok:
            log("세션 유효")
            return 0
        if st.get("blocked"):
            log(f"자동 로그인 중지 상태({st.get('blocked_reason')}, {st.get('blocked_at')}) → 직접 로그인 필요")
        elif manual_due(st):
            log(f"마지막 직접 로그인({st.get('last_manual') or '기록 없음'}) 후 7일 경과 → 직접 로그인 필요")
        elif await try_auto_login(p, st):
            return 10
        return 10 if await manual_login(p, st, WAIT_CHECK_MIN, logout=False) else 1


def set_cred():
    uid = input("네이버 아이디: ").strip()
    pw = getpass.getpass("비밀번호 (입력해도 화면에 안 보입니다): ")
    if not uid or not pw:
        sys.exit("아이디/비밀번호가 비어 있어 저장하지 않았습니다.")
    GUARD_CRED.parent.mkdir(parents=True, exist_ok=True)
    GUARD_CRED.write_text(json.dumps({"id": uid, "pw": pw}, ensure_ascii=False), encoding="utf-8")
    print("저장 완료:", GUARD_CRED, "(아이디:", uid + ")")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    migrate_creds()
    if cmd == "set":
        return set_cred()
    if cmd == "status":
        st = load_state()
        print(json.dumps({**st, "auto_account": load_cred().get("id", ""), "manual_due": manual_due(st)},
                         ensure_ascii=False, indent=1))
        return
    if cmd == "check":
        sys.exit(asyncio.run(check()))

    async def manual(logout):
        async with async_playwright() as p:
            return await manual_login(p, load_state(), WAIT_WEEKLY_MIN if logout else 10, logout)
    if cmd in ("weekly", "login"):
        sys.exit(0 if asyncio.run(manual(cmd == "weekly")) else 1)
    sys.exit(f"알 수 없는 명령: {cmd}")


if __name__ == "__main__":
    main()
