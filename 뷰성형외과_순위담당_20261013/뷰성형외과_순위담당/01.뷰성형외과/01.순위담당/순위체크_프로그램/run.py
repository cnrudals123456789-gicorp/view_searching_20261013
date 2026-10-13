"""
대시보드에 저장된 설정(settings.json)으로 순위 체크를 한 번 실행합니다. (매일 실행용)
  python run.py            # settings.json 그대로 (키워드·도메인·브랜드명·PC/모바일·headless)
  python run.py --show     # 브라우저 창을 보면서 실행
로그인 세션이 만료돼 있으면 credentials.json의 계정으로 자동 재로그인한 뒤 진행합니다.
결과는 results_YYYYMMDD.csv 에 누적되고, 대시보드에서도 그대로 보입니다.
"""
import asyncio
import sys
from datetime import datetime

import rank
from app import load_settings, BASE_DIR
from common import load_login_info


def main():
    s = load_settings()
    types = [t for t in s.get("types", []) if t in ("powerlink", "powercontents")] or ["powerlink", "powercontents"]
    keywords = [k.strip() for k in s.get("keywords", []) if k.strip()] if "powerlink" in types else []
    pc_keywords = [k.strip() for k in s.get("pc_keywords", []) if k.strip()] if "powercontents" in types else []
    if not keywords and not pc_keywords:
        print("[!] settings.json에 키워드가 없습니다. 대시보드에서 키워드를 저장한 뒤 실행하세요.")
        sys.exit(2)
    devices = ["pc", "mobile"] if s.get("device", "both") == "both" else [s["device"]]
    headless = False if "--show" in sys.argv else bool(s.get("headless", True))
    out_path = BASE_DIR / f"results_{datetime.now():%Y%m%d}.csv"

    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] 순위 체크 시작 — 파워링크 {len(keywords)}개 / 파워컨텐츠 {len(pc_keywords)}개 / "
          f"기기 {', '.join(devices)} / 도메인 {s.get('target') or '(없음)'} / 브랜드명 {s.get('pc_target') or '(없음)'}")
    try:
        asyncio.run(rank.run(keywords, devices, (s.get("target") or "").lower(), headless, float(s.get("delay", 3) or 3), out_path,
                             deep=True, types=tuple(types), pc_target=s.get("pc_target", ""), pc_keywords=pc_keywords))
    except rank.NotLoggedIn as e:
        print("[!]", e)
        sys.exit(1)
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] 완료 (계정: {load_login_info().get('id') or '?'})")


if __name__ == "__main__":
    main()
