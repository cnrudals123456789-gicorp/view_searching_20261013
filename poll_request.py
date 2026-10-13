"""공개 페이지의 '조회 요청'을 이 PC가 가져와 처리한다. (작업 스케줄러가 2분마다 실행)

  docs/request.json 의 status 가 'pending' 이면 → 'running' 으로 바꾸고 run_and_publish.bat 실행
  → 끝나면 'done'/'error' 와 last_run_at 을 기록해 푸시. 요청은 Cloudflare Worker 가 GitHub API 로 기록한다.
이 PC 는 인터넷에 열려 있지 않다. GitHub 에서 가져가기(pull)만 한다.

  python poll_request.py                     # 평소 (스케줄러)
  python poll_request.py --dry-run --req X   # 판단만 출력. 파일 X 를 request.json 대신 사용, git·조회 안 함
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

for _s in (sys.stdout, sys.stderr):          # 스케줄러·cp949 콘솔에서도 한글 로그가 죽지 않게
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
REQ = ROOT / "docs" / "request.json"
LOGDIR = ROOT / "logs"
LOCK = LOGDIR / "run.lock"           # serve.py 의 수동 조회와 겹치지 않게 하는 잠금
COOLDOWN_MIN = 30                    # Worker 와 같은 값
STALE_MIN = 90                       # 이 시간이 지난 잠금·running 은 멈춘 것으로 본다
KST = timezone(timedelta(hours=9))


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(msg):
    LOGDIR.mkdir(exist_ok=True)
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    with open(LOGDIR / "poll.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")


def age_min(iso):
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 60
    except (TypeError, ValueError):
        return None


def decide(req, lock_age=None):
    """요청 상태를 보고 (행동, 사유) 를 돌려준다. 행동: 'run' | 'skip' | 'reject' | 'recover'"""
    if lock_age is not None and lock_age < STALE_MIN:
        return "skip", f"다른 조회가 진행 중 (잠금 {lock_age:.0f}분 전)"
    st = req.get("status")
    if st == "running":
        a = age_min(req.get("started_at"))
        if a is not None and a > STALE_MIN:
            return "recover", f"running 상태가 {a:.0f}분 지속 — 멈춘 것으로 처리"
        return "skip", "running"
    if st != "pending":
        return "skip", f"status={st}"
    last = age_min(req.get("last_run_at"))
    if last is not None and last < COOLDOWN_MIN:
        return "reject", f"쿨다운 {COOLDOWN_MIN - last:.0f}분 남음"
    return "run", "새 요청"


def save(req, path, message, use_git):
    path.write_text(json.dumps(req, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not use_git:
        return
    git("add", "docs/request.json")
    if git("commit", "-m", message).returncode == 0:
        r = git("push")
        if r.returncode != 0:
            log(f"[!] push 실패: {r.stderr.strip()[:200]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--req", help="request.json 대신 쓸 파일 (시험용)")
    a = ap.parse_args()
    path = Path(a.req) if a.req else REQ
    use_git = not a.dry_run

    lock_age = None
    if LOCK.exists():
        lock_age = (datetime.now().timestamp() - LOCK.stat().st_mtime) / 60
    if use_git:
        r = git("pull", "--rebase", "--autostash", "-q")
        if r.returncode != 0:
            log(f"[!] git pull 실패: {r.stderr.strip()[:200]}")
            return 1
    if not path.exists():
        return 0
    req = json.loads(path.read_text(encoding="utf-8-sig"))
    action, why = decide(req, lock_age)
    if action == "skip":
        if req.get("status") == "pending":      # 대기 중인 요청이 막혀 있을 때만 기록
            log(f"대기: {why}")
        return 0
    log(f"요청 {req.get('id', '')[:8]} → {action}: {why}")
    if action == "reject":
        req.update(status="rejected", message=why, finished_at=now_iso())
        save(req, path, "조회 요청 거절 (쿨다운)", use_git)
        return 0
    if action == "recover":
        req.update(status="error", message=why, finished_at=now_iso())
        save(req, path, "조회 요청 복구 처리", use_git)
        return 0

    # run
    req.update(status="running", started_at=now_iso(), message="PC 에서 조회 중")
    save(req, path, "조회 시작", use_git)
    if a.dry_run:
        log("[dry-run] 조회 실행 생략")
        return 0
    LOCK.parent.mkdir(exist_ok=True)
    LOCK.write_text(now_iso(), encoding="utf-8")
    code = -1
    try:
        env = dict(os.environ, PYTHONUTF8="1")
        code = subprocess.run(["cmd.exe", "/d", "/c", str(ROOT / "run_and_publish.bat")], cwd=str(ROOT), env=env).returncode
    except Exception as e:                       # noqa: BLE001
        log(f"[!] 실행 오류: {e}")
    finally:
        LOCK.unlink(missing_ok=True)
    git("pull", "--rebase", "--autostash", "-q")
    req = json.loads(path.read_text(encoding="utf-8-sig"))
    req.update(status="done" if code == 0 else "error", finished_at=now_iso(),
               message="조회 완료" if code == 0 else f"조회 실패 (exit {code})")
    if code == 0:
        req["last_run_at"] = req["finished_at"]
    save(req, path, f"조회 {req['status']}", use_git)
    log(f"완료: {req['status']} (exit {code})")
    return 0 if code == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
