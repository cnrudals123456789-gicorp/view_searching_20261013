"""
네이버 로그인.
  - credentials.json(로컬, %LOCALAPPDATA%\\naver_powerlink)이 있으면 그 계정으로 자동 로그인
  - 없으면 브라우저 창을 열어 수동 로그인 ('로그인 상태 유지' 체크 권장)
  - 계정 저장/변경:  python login.py --set 아이디 비밀번호
평소에는 rank.py가 세션 만료를 감지하면 스스로 자동 로그인하므로 직접 실행할 일은 거의 없다.
"""
import asyncio
import json
import sys
from playwright.async_api import async_playwright
from common import (launch, is_logged_in, keep_login_checked, save_state, read_login_id, save_login_info,
                    load_credentials, auto_login, PROFILE_DIR, STATE_FILE, CRED_FILE)


def set_credentials(user_id: str, pw: str):
    CRED_FILE.parent.mkdir(parents=True, exist_ok=True)
    CRED_FILE.write_text(json.dumps({"id": user_id, "pw": pw}, ensure_ascii=False), encoding="utf-8")
    if STATE_FILE.exists():          # 계정이 바뀌었을 수 있으니 기존 세션 백업은 버린다
        STATE_FILE.unlink()
    print("계정 저장:", CRED_FILE, "(아이디:", user_id + ")")


async def main():
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    cred = load_credentials()
    async with async_playwright() as p:
        ctx = await launch(p, "pc", headless=bool(cred))
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        if cred:
            print(f"저장된 계정({cred['id']})으로 자동 로그인 중...")
            # 다른 계정 세션이 남아 있으면 지우고 새로 로그인
            await ctx.clear_cookies()
            if not await auto_login(ctx, page, cred):
                print("[!] 자동 로그인 실패. 아이디/비밀번호 또는 캡차·2단계 인증 여부를 확인하세요.")
                print("    수동 로그인: credentials.json을 지우고 python login.py 를 다시 실행")
                save_login_info("", False)
                await ctx.close()
                sys.exit(1)
        else:
            if await is_logged_in(ctx):
                print("이미 로그인되어 있습니다. 다른 계정으로 바꾸려면 브라우저에서 로그아웃 후 다시 로그인하세요.")
            await page.goto("https://nid.naver.com/nidlogin.login?url=https%3A%2F%2Fwww.naver.com")
            print("브라우저에서 네이버 로그인을 완료해 주세요. ('로그인 상태 유지' 체크 권장)")
            print("로그인이 감지되면 자동으로 종료됩니다... (최대 5분)")
            for _ in range(300):
                await asyncio.sleep(1)
                if await is_logged_in(ctx):
                    break
            else:
                print("로그인이 감지되지 않았습니다. 다시 실행해 주세요.")
                await ctx.close()
                return
            await page.goto("https://www.naver.com")
            await page.wait_for_timeout(1500)
            await save_state(ctx)

        login_id = await read_login_id(page)
        save_login_info(login_id, True)
        keep = await keep_login_checked(ctx)
        print(f"로그인 완료: {login_id or '(아이디 확인 불가)'}  /  로그인 상태 유지: {'적용됨' if keep else '미적용(세션 만료 시 자동 재로그인)'}")
        await ctx.close()


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--set":
        if len(sys.argv) != 4:
            print("사용법: python login.py --set 아이디 비밀번호")
            sys.exit(2)
        set_credentials(sys.argv[2], sys.argv[3])
    asyncio.run(main())
