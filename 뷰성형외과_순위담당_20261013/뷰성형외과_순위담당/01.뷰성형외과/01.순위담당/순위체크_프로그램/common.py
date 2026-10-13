import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent                     # 스크립트/결과 CSV 위치 (OneDrive)
# 로그인 세션(브라우저 프로필)은 OneDrive 동기화 충돌·쿠키 유출 방지를 위해 로컬에 저장
PROFILE_DIR = Path(os.environ["LOCALAPPDATA"]) / "naver_powerlink" / "profile"

PC_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")


def launch_kwargs(p, device: str, headless: bool) -> dict:
    """persistent context 실행 옵션. device: 'pc' | 'mobile'"""
    kw = dict(
        user_data_dir=str(PROFILE_DIR),
        headless=headless,
        locale="ko-KR",
        timezone_id="Asia/Seoul",
        args=["--disable-blink-features=AutomationControlled"],
        ignore_default_args=["--enable-automation"],
    )
    if device == "mobile":
        d = dict(p.devices["Galaxy S9+"])
        d.pop("default_browser_type", None)
        kw.update(d)
    else:
        kw.update(user_agent=PC_UA, viewport={"width": 1280, "height": 900})
    return kw


async def launch(p, device: str, headless: bool):
    """설치된 Chrome이 있으면 Chrome, 없으면 Playwright Chromium 사용"""
    kw = launch_kwargs(p, device, headless)
    try:
        return await p.chromium.launch_persistent_context(channel="chrome", **kw)
    except Exception:
        return await p.chromium.launch_persistent_context(**kw)


STATE_FILE = PROFILE_DIR.parent / "naver_state.json"   # 로그인 쿠키 백업 (세션 쿠키 복원용)


async def is_logged_in(ctx) -> bool:
    cookies = await ctx.cookies("https://www.naver.com")
    names = {c["name"] for c in cookies}
    return "NID_AUT" in names and "NID_SES" in names


async def keep_login_checked(ctx) -> bool:
    """'로그인 상태 유지'로 로그인했는지 (NID_AUT가 만료일이 있는 영구 쿠키인지)"""
    for c in await ctx.cookies("https://www.naver.com"):
        if c["name"] == "NID_AUT":
            return c.get("expires", -1) not in (-1, None)
    return False


async def save_state(ctx):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    await ctx.storage_state(path=str(STATE_FILE))


async def restore_state(ctx) -> bool:
    """브라우저 종료로 사라진 세션 쿠키를 백업 파일에서 복원"""
    if not STATE_FILE.exists():
        return False
    import json
    data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    cookies = [c for c in data.get("cookies", []) if "naver.com" in c.get("domain", "")]
    if not cookies:
        return False
    await ctx.add_cookies(cookies)
    return await is_logged_in(ctx)


async def ensure_logged_in(ctx) -> bool:
    if await is_logged_in(ctx):
        return True
    return await restore_state(ctx)


# 자동 로그인용 계정 (OneDrive 밖, 로컬에만 저장). {"id": "...", "pw": "..."}
CRED_FILE = PROFILE_DIR.parent / "credentials.json"
# 마지막으로 확인된 로그인 계정 정보 (대시보드 표시용). 비밀번호는 저장하지 않는다.
LOGIN_INFO_FILE = PROFILE_DIR.parent / "login_info.json"


def load_credentials() -> dict:
    import json
    if not CRED_FILE.exists():
        return {}
    try:
        d = json.loads(CRED_FILE.read_text(encoding="utf-8"))
        return d if d.get("id") and d.get("pw") else {}
    except Exception:
        return {}


def save_login_info(login_id: str, ok: bool):
    import json
    from datetime import datetime
    LOGIN_INFO_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOGIN_INFO_FILE.write_text(json.dumps({"id": login_id, "ok": ok, "checked_at": datetime.now().isoformat(timespec="seconds")},
                                          ensure_ascii=False), encoding="utf-8")


def load_login_info() -> dict:
    import json
    try:
        return json.loads(LOGIN_INFO_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


async def read_login_id(page) -> str:
    """naver.com 메인(로그인 상태)에서 로그인한 아이디를 읽는다. 실패 시 ''"""
    try:
        return await page.evaluate(r"""() => {
          const box = document.querySelector('[class*="MyView"]') || document.body;
          const m = box.innerText.match(/([A-Za-z0-9._-]+)@naver\.com/);
          return m ? m[1] : '';
        }""") or ""
    except Exception:
        return ""


async def auto_login(ctx, page, cred: dict) -> bool:
    """저장된 계정으로 네이버 로그인 ('로그인 상태 유지' 체크). 성공하면 세션을 백업한다."""
    await page.goto("https://nid.naver.com/nidlogin.login?url=https%3A%2F%2Fwww.naver.com", wait_until="domcontentloaded")
    await page.wait_for_selector("#id", timeout=10000)
    await page.wait_for_timeout(500)
    # 키 입력 대신 값 주입(+input 이벤트) — 자동입력 감지로 인한 캡차를 피하기 위한 일반적인 방식
    await page.evaluate("""([id, pw]) => {
      const set = (sel, v) => { const el = document.querySelector(sel); if (!el) return;
        el.focus(); el.value = v; el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true})); };
      set('#id', id); set('#pw', pw);
      const keep = document.querySelector('#loginStay, #keep, input[name=nvlong]');   // 로그인 상태 유지
      if (keep && !keep.checked) keep.click();
    }""", [cred["id"], cred["pw"]])
    await page.wait_for_timeout(400)
    # 로그인 버튼 (화면 레이아웃에 따라 id가 다름)
    btn = page.locator("#loginBtn_row, #loginBtn_column").filter(visible=True)
    if await btn.count():
        await btn.first.click(timeout=5000)
    else:
        await page.press("#pw", "Enter")
    for _ in range(20):
        await page.wait_for_timeout(500)
        if await is_logged_in(ctx):
            break
    else:
        return False
    # 새 기기 등록/보안 안내 페이지가 뜨면 naver.com으로 이동해 마무리
    await page.goto("https://www.naver.com", wait_until="domcontentloaded")
    await page.wait_for_timeout(1500)
    if not await is_logged_in(ctx):
        return False
    await save_state(ctx)
    return True


async def verify_logged_in(ctx, page) -> bool:
    """쿠키가 '있는지'가 아니라 서버가 세션을 '인정하는지' 확인.
    만료된 세션 쿠키는 naver.com 접속 시 서버가 지워버리므로, 접속 후에도 남아 있어야 진짜 로그인 상태다.
    (미로그인 상태로 검색하면 연령·성별 타겟팅이 빠져 실제 화면과 순위가 달라진다)
    세션이 없거나 만료됐고 credentials.json이 있으면 자동으로 다시 로그인한다."""
    ok = False
    if await ensure_logged_in(ctx):
        await page.goto("https://www.naver.com", wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)
        ok = await is_logged_in(ctx)
    if not ok:
        if STATE_FILE.exists():          # 만료된 백업은 제거
            STATE_FILE.unlink()
        cred = load_credentials()
        if cred:
            ok = await auto_login(ctx, page, cred)
    if not ok:
        save_login_info("", False)
        return False
    # 모바일 화면 등 아이디를 못 읽는 페이지면 직전에 확인된 아이디를 유지
    login_id = await read_login_id(page) or load_login_info().get("id", "") or load_credentials().get("id", "")
    save_login_info(login_id, True)
    return True
