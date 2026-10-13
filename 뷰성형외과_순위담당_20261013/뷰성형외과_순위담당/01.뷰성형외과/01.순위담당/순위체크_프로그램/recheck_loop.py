"""미노출 조합 5분 간격 자동 재확인 (자동순위체크.bat 이 run.py 성공 후 호출)

  python recheck_loop.py                # 오전 회차면 15:55, 오후 회차면 22:00 까지
  python recheck_loop.py --until 21:00 --interval 5
  python recheck_loop.py --task 52 --resume   # 중단된 루프 이어받기: 기존 업무에 기록, targets 재생성 없이 재확인

- 첫 회: recheck.py --build --run (오늘 results 마지막 회차의 미노출 조합으로 대상 생성)
- 이후: interval 분마다 recheck.py, 남은 미노출 0 이면 종료
- 진행은 에이전트 리더 대시보드(00.에이전트리더\\board_update.py)에 업무 1건으로 기록
- 실행 중에만 PC 절전 진입을 막음 (SetThreadExecutionState, 종료 시 자동 해제)
디렉터 님 지시(2026-10-01): 뷰 순위 자동화
"""
import argparse
import ctypes
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
from paths import BOARD
PY = sys.executable
ENV = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")


def board(*args):
    try:
        r = subprocess.run([PY, str(BOARD), *args], capture_output=True, text=True, env=ENV, timeout=60)
        return r.stdout.strip()
    except Exception as e:
        print("board 오류", e, flush=True)
        return ""


def keep_awake(on):
    try:
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))
    except Exception:
        pass


def recheck(build):
    cmd = [PY, "recheck.py"] + (["--build", "--run"] if build else [])
    r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, env=ENV)
    log = HERE / "logs" / f"{datetime.now():%Y%m%d}_recheck.log"
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"\n[{datetime.now():%H:%M:%S}] {' '.join(cmd[1:])} exit {r.returncode}\n{r.stderr}\n{r.stdout}")
    lines = r.stdout.strip().splitlines()
    n = None
    if r.returncode == 0 and lines and lines[0].startswith("남은미노출"):
        n = int(lines[0].split()[1])
    return r.returncode, n, lines[1:]


def to_excel():
    """재확인 결과 중 노출로 바뀐 조합을 순위요약 엑셀에 반영 (중복 없음). 반환: 결과 한 줄"""
    try:
        r = subprocess.run([PY, "recheck_excel.py"], cwd=HERE, capture_output=True, text=True, env=ENV, timeout=120)
        return (r.stdout.strip().splitlines() or [f"exit {r.returncode} {r.stderr.strip()[-100:]}"])[0]
    except Exception as e:
        return f"엑셀 반영 오류 {e}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--until", help="HH:MM (기본: 12시 전 시작이면 15:55, 이후면 22:00)")
    ap.add_argument("--interval", type=int, default=5)
    ap.add_argument("--task", help="새 업무를 만들지 않고 이 업무 id에 기록 (중단된 루프 재개용)")
    ap.add_argument("--resume", action="store_true", help="첫 회에도 --build 없이 현재 recheck_targets.json 그대로 재확인")
    a = ap.parse_args()
    now = datetime.now()
    until = a.until or ("15:55" if now.hour < 12 else "22:00")
    end = now.replace(hour=int(until[:2]), minute=int(until[3:]), second=0)
    label = "오전" if now.hour < 12 else "오후"

    task = a.task or board("newtask", "--owner", "뷰)순위담당", "--status", "busy",
                 "--title", f"{now:%m-%d} {label} 미노출 자동 재확인 ({a.interval}분 간격, ~{until})",
                 "--detail", "자동순위체크.bat → recheck_loop.py 자동 실행 (디렉터 님 10-01 자동화 지시)")
    board("agent", "rank", "--status", "busy", "--note", f"{label} 미노출 {a.interval}분 자동 재확인 중 (~{until})")
    keep_awake(True)
    first, prev, n = True, None, None
    build = not a.resume
    try:
        while datetime.now() < end:
            rc, n, remain = recheck(first and build)
            t = datetime.now().strftime("%H:%M")
            if n is None:
                task and board("log", task, f"{t} 재확인 오류(exit {rc}) — 다음 회차 재시도")
            else:
                if first:
                    msg = f"{t} 자동 재확인 {'재개' if a.resume else '시작'}: 미노출 {n}개"
                elif n != prev:
                    msg = f"{t} 재확인: 남은 미노출 {n} (신규 노출 {prev - n})"
                else:
                    msg = f"{t} 재확인: 남은 미노출 {n} (신규 노출 없음)"
                # 2026-10-06 디렉터 님 지시: 신규 노출이 나올 때마다 즉시 엑셀 반영 (루프 종료까지 기다리지 않음)
                if not first and prev is not None and n < prev:
                    msg += " / " + to_excel()
                task and board("log", task, msg)
                print(msg, flush=True)
                prev, first = n, False
                if n == 0:
                    break
            time.sleep(a.interval * 60)
    finally:
        keep_awake(False)
        result = "미노출 전부 노출 확인 → 종료" if n == 0 else f"{until} 종료, 남은 미노출 {prev if prev is not None else '?'}"
        # 2026-10-06 (업무 71): 재확인에서 노출로 바뀐 조합을 순위요약 엑셀에 반영
        xl = to_excel()
        print(xl, flush=True)
        # 2026-10-06 디렉터 님 지시: 재확인 종료 시 최신 순위표를 대시보드에 표로 게시
        try:
            from rank_table import post
            post()
        except Exception as e:
            print("순위표 게시 오류", e, flush=True)
        task and board("log", task, f"{datetime.now():%H:%M} {xl}")
        if task:
            board("task", task, "--status", "done", "--result", result)
        board("agent", "rank", "--status", "idle", "--note", f"{datetime.now():%m-%d %H:%M} {label} 자동 재확인 {result}")


if __name__ == "__main__":
    main()
