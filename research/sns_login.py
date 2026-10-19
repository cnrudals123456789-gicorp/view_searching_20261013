"""별도 계정으로 SNS 에 한 번 로그인해 두는 도구. 아이디·비밀번호는 열리는 브라우저 창에 직접 입력한다.
  python research/sns_login.py instagram
  python research/sns_login.py x
  python research/sns_login.py tiktok      (계정이 생겼을 때)
  python research/sns_login.py --status    (로그인 상태 확인)

- 채팅·파일에 아이디/비밀번호를 적지 않는다. 2단계 인증도 그 창에서 처리한다.
- 저장되는 것: 브라우저 세션(%LOCALAPPDATA%\\view_research\\profiles\\<사이트>) 과 계정 번호·시각(accounts.json). 비밀번호는 저장되지 않는다.
- 로그인이 감지되면 창이 자동으로 닫힌다 (최대 10분 대기).
"""
import json
import sys
import time
from datetime import datetime

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from _common import ACCOUNTS, LOGIN_SITES, PROFILES, UA  # noqa: E402


def load_accounts():
    try:
        return json.loads(ACCOUNTS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def cookie_map(ctx):
    return {c["name"]: c["value"] for c in ctx.cookies()}


def status():
    acc = load_accounts()
    for site in LOGIN_SITES:
        a = acc.get(site)
        print(f"{site:10s}", f"로그인됨 (계정번호 {a['user_id']}, {a['logged_in']})" if a else "로그인 안 됨")


def login(site, wait_min=10):
    from playwright.sync_api import sync_playwright
    cfg = LOGIN_SITES[site]
    prof = PROFILES / site
    prof.mkdir(parents=True, exist_ok=True)
    print(f"[{site}] 브라우저 창이 열립니다. 별도 계정으로 직접 로그인하세요. (최대 {wait_min}분 대기)")
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(prof), headless=False, user_agent=UA, locale="ko-KR",
                                                   viewport={"width": 1100, "height": 800})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(cfg["url"])
        deadline = time.time() + wait_min * 60
        ok = False
        while time.time() < deadline:
            try:
                ck = cookie_map(ctx)
            except Exception:                       # 창을 닫은 경우
                break
            if cfg["ok_cookie"] in ck:
                ok = True
                break
            time.sleep(2)
        if ok:
            time.sleep(3)                           # 쿠키가 디스크에 쓰이도록 잠깐 대기
            uid = cookie_map(ctx).get(cfg["id_cookie"], "?")
            acc = load_accounts()
            acc[site] = {"user_id": uid, "logged_in": datetime.now().strftime("%Y-%m-%d %H:%M")}
            ACCOUNTS.parent.mkdir(parents=True, exist_ok=True)
            ACCOUNTS.write_text(json.dumps(acc, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[{site}] 로그인 확인됨 — 세션 저장 완료 ({ACCOUNTS})")
        else:
            print(f"[{site}] 로그인이 확인되지 않았습니다. 다시 실행해 주세요.")
        ctx.close()
    return 0 if ok else 1


def main():
    a = sys.argv[1] if len(sys.argv) > 1 else ""
    if a == "--status":
        status()
        return 0
    if a in LOGIN_SITES:
        return login(a)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
