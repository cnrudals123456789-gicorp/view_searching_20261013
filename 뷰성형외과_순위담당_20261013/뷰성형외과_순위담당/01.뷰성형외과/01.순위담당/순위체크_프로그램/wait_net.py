"""
인터넷 연결 대기 (자동순위체크.bat 이 run.py 전에 호출)
  python wait_net.py                       # 최대 10분, 30초 간격으로 www.naver.com 접속 확인
  python wait_net.py --timeout 60 --interval 10
- 연결되면 exit 0, 시간 내 연결 안 되면 exit 1 (bat 는 그래도 기존 재시도 루프로 진행)
- 대기 중에는 PC 절전 진입을 막음 (절전 해제 직후 네트워크 미연결 → 재절전 방지)
디렉터 님 승인(2026-10-06, 업무 71): 절전 해제 직후 인터넷 미연결로 정규 회차 연속 실패 대응
"""
import argparse
import ctypes
import time
import urllib.request
from datetime import datetime

URL = "https://www.naver.com"


def keep_awake(on):
    try:
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))
    except Exception:
        pass


def online():
    try:
        req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status < 500
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=600, help="최대 대기 초 (기본 600)")
    ap.add_argument("--interval", type=int, default=30, help="확인 간격 초 (기본 30)")
    a = ap.parse_args()
    start = time.time()
    keep_awake(True)
    try:
        tries = 0
        while True:
            tries += 1
            if online():
                if tries > 1:
                    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [net] 인터넷 연결 확인 ({int(time.time() - start)}초 대기)", flush=True)
                return 0
            if time.time() - start + a.interval > a.timeout:
                print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [net] {a.timeout}초 동안 인터넷 미연결", flush=True)
                return 1
            if tries == 1:
                print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [net] 인터넷 미연결 — {a.interval}초 간격으로 최대 {a.timeout}초 대기", flush=True)
            time.sleep(a.interval)
    finally:
        keep_awake(False)


if __name__ == "__main__":
    raise SystemExit(main())
