"""로컬 조회 서버: 웹 화면의 '조회하기' 버튼을 누르면 이 PC에서 순위 체크 → 웹 게시까지 실행한다.
  python serve.py        →  http://127.0.0.1:8770  (브라우저 자동 실행, 이 PC 에서만 접속 가능)
GitHub Pages 의 공개 화면에는 버튼이 보이지 않는다 (주소가 127.0.0.1 일 때만 표시).
"""
import json
import subprocess
import threading
import webbrowser
from datetime import datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
LOG = ROOT / "logs" / "last_run.log"
JOBS = {"check": ("run_and_publish.bat", "last_run.log", "조회"),
        "research": ("research_and_publish.bat", "last_research.log", "경쟁사 조사")}
LOCK = ROOT / "logs" / "run.lock"       # 조회 중 표시 (화면 새로고침·중복 클릭 대비)
PARAMS = ROOT / "logs" / "research_params.json"   # 경쟁사 조사 기간 (research/make_prompt.py 가 읽음)
HOST, PORT = "127.0.0.1", 8770
MAX_DAYS = 92

state = {"running": False, "started": None, "finished": None, "exit": None, "job": None}
lock = threading.Lock()


def parse_period(body):
    """{"days": N} 또는 {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"} → 검증된 {"from","to"} (오늘 기준, 최대 92일)"""
    today = datetime.now().date()
    if body.get("from") or body.get("to"):
        start = datetime.strptime(str(body.get("from")), "%Y-%m-%d").date()
        end = datetime.strptime(str(body.get("to") or today), "%Y-%m-%d").date()
    else:
        days = int(body.get("days") or 14)
        if days < 1:
            raise ValueError("일수는 1 이상이어야 합니다")
        end, start = today, today - timedelta(days=days - 1)
    if end > today:
        end = today
    if start > end:
        raise ValueError("시작일이 종료일보다 늦습니다")
    if (end - start).days + 1 > MAX_DAYS:
        raise ValueError(f"기간은 최대 {MAX_DAYS}일까지입니다")
    return {"from": start.isoformat(), "to": end.isoformat()}


def worker(job="check"):
    bat, logname, label = JOBS[job]
    LOG.parent.mkdir(exist_ok=True)
    LOCK.write_text(datetime.now().isoformat(), encoding="utf-8")
    with open(LOG.parent / logname, "w", encoding="utf-8", errors="replace") as f:
        f.write(f"[{datetime.now():%H:%M:%S}] {label} 시작\n")
        f.flush()
        try:
            p = subprocess.run(["cmd.exe", "/d", "/c", str(ROOT / bat)], cwd=str(ROOT),
                               stdout=f, stderr=subprocess.STDOUT)
            code = p.returncode
        except Exception as e:                      # noqa: BLE001
            f.write(f"[!] 실행 오류: {e}\n")
            code = -1
        f.write(f"[{datetime.now():%H:%M:%S}] 종료 (exit {code})\n")
    LOCK.unlink(missing_ok=True)
    with lock:
        state.update(running=False, finished=datetime.now().isoformat(timespec="seconds"), exit=code)


def tail(path: Path, n=15):
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except OSError:
        return []


def newest_log():
    """실제 순위 체크 로그(프로그램\\logs\\YYYYMMDD.log)의 마지막 줄들 — 진행 상황 표시용"""
    logs = sorted(ROOT.glob("*/**/순위체크_프로그램/logs/2*.log"), key=lambda p: p.stat().st_mtime)
    logs = [p for p in logs if "dryrun" not in p.name]
    return tail(logs[-1], 12) if logs else []


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(DOCS), **kw)

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/api/status"):
            with lock:
                s = dict(state)
            job = s["job"] or "check"
            extra = [""] + newest_log() if s["running"] and job == "check" else []
            return self._json({**s, "log": tail(LOG.parent / JOBS[job][1]) + extra})
        self.path = self.path.split("?")[0]
        super().do_GET()

    def do_POST(self):
        job = {"/api/check": "check", "/api/research": "research"}.get(self.path)
        if job:
            # 다른 사이트에서 몰래 호출하지 못하게 같은 출처만 허용
            origin = self.headers.get("Origin", "")
            if origin and origin not in (f"http://{HOST}:{PORT}", f"http://localhost:{PORT}"):
                return self._json({"ok": False, "msg": "허용되지 않은 요청"}, 403)
            params = None
            if job == "research":
                try:
                    n = min(int(self.headers.get("Content-Length") or 0), 4096)
                    params = parse_period(json.loads(self.rfile.read(n) or b"{}"))
                except (ValueError, TypeError) as e:
                    return self._json({"ok": False, "msg": f"조사 기간 오류: {e}"}, 400)
            with lock:
                if not state["running"] and LOCK.exists() and (datetime.now().timestamp() - LOCK.stat().st_mtime) < 90 * 60:
                    return self._json({"ok": False, "msg": "다른 조회가 진행 중입니다. 끝난 뒤 다시 눌러 주세요."}, 409)
                if state["running"]:
                    return self._json({"ok": False, "msg": "이미 조회 중입니다."}, 409)
                if params:
                    PARAMS.parent.mkdir(exist_ok=True)
                    PARAMS.write_text(json.dumps(params), encoding="utf-8")
                state.update(running=True, job=job, started=datetime.now().isoformat(timespec="seconds"), finished=None, exit=None)
            threading.Thread(target=worker, args=(job,), daemon=True).start()
            return self._json({"ok": True, "period": params})
        self._json({"ok": False}, 404)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    url = f"http://{HOST}:{PORT}/"
    print(f"뷰성형외과 순위 조회 화면: {url}  (이 창을 닫으면 종료됩니다)")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    ThreadingHTTPServer((HOST, PORT), H).serve_forever()
