"""collect.py / sns_login.py 공용 상수. 세션·계정 정보는 저장소 밖(%LOCALAPPDATA%)에만 둔다."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "view_research"
PROFILES = BASE / "profiles"          # 사이트별 브라우저 세션(쿠키) — 비밀번호는 저장하지 않음
ACCOUNTS = BASE / "accounts.json"     # 어떤 별도 계정으로 로그인했는지 확인용(계정 번호·시각만)

# 로그인이 필요한 사이트: 시작 URL, 로그인 완료를 알리는 쿠키, 계정 식별용 쿠키
LOGIN_SITES = {
    "instagram": {"url": "https://www.instagram.com/accounts/login/", "ok_cookie": "sessionid", "id_cookie": "ds_user_id"},
    "x":         {"url": "https://x.com/i/flow/login",                "ok_cookie": "auth_token", "id_cookie": "twid"},
    "tiktok":    {"url": "https://www.tiktok.com/login",              "ok_cookie": "sessionid", "id_cookie": "uid_tt"},
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0.0.0 Safari/537.36")
