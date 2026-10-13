"""
파워링크 순위 체크 로컬 웹 대시보드.
  python app.py   →  http://127.0.0.1:8765  (브라우저 자동 실행)
크롤링은 이 PC의 로그인된 브라우저 프로필로 돌아가므로 외부 공개용이 아닌 로컬 전용입니다.
"""
import asyncio
import csv
import json
import subprocess
import sys
import threading
import webbrowser
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

import rank
from common import BASE_DIR, STATE_FILE, load_login_info, load_credentials

HOST, PORT = "127.0.0.1", 8765
SETTINGS_FILE = BASE_DIR / "settings.json"
WEB_DIR = BASE_DIR / "web"

app = Flask(__name__, static_folder=None)

# ---------- 설정 ----------
DEFAULT_SETTINGS = {"keywords": [], "pc_keywords": [], "target": "", "pc_target": "", "device": "both", "headless": True,
                    "delay": 3.0, "types": ["powerlink", "powercontents"]}


def load_settings():
    s = dict(DEFAULT_SETTINGS)
    if SETTINGS_FILE.exists():
        try:
            s.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
        if "pc_keywords" not in json.loads(SETTINGS_FILE.read_text(encoding="utf-8")):   # 구버전 설정: 한 목록 → 둘 다
            s["pc_keywords"] = list(s["keywords"])
    elif (BASE_DIR / "keywords.txt").exists():      # 처음 실행 시 keywords.txt 이어받기
        with open(BASE_DIR / "keywords.txt", encoding="utf-8-sig") as f:
            s["keywords"] = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    return s


def save_settings(s):
    SETTINGS_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- 실행 상태 ----------
job = {"running": False, "log": [], "started": None, "finished": None, "error": None, "login_ok": None}
job_lock = threading.Lock()


def _log(msg):
    job["log"].append(f"{datetime.now():%H:%M:%S}  {msg}")


def _worker(keywords, devices, target, headless, delay, types, pc_target, pc_keywords):
    out_path = BASE_DIR / f"results_{datetime.now():%Y%m%d}.csv"
    try:
        asyncio.run(rank.run(keywords, devices, target, headless, delay, out_path, deep=True, log=_log,
                             types=tuple(types), pc_target=pc_target, pc_keywords=pc_keywords))
        job["login_ok"] = True
        job["error"] = None
    except rank.NotLoggedIn as e:
        job["login_ok"] = False
        job["error"] = str(e)
        _log(f"[!] {e}")
    except Exception as e:
        job["error"] = f"{type(e).__name__}: {e}"
        _log(f"[!] 오류: {job['error']}")
    finally:
        job["running"] = False
        job["finished"] = datetime.now().isoformat(timespec="seconds")


# ---------- 결과 읽기 ----------
def load_results():
    """모든 results_*.csv → 실행(timestamp) 단위로 정리"""
    rows = []
    for f in sorted(BASE_DIR.glob("results_*.csv")):
        with open(f, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                if not r.get("source"):        # 구버전 파일 호환
                    r["source"] = "1page"
                if not r.get("ad_type"):
                    r["ad_type"] = "powerlink"
                rows.append(r)
    runs = OrderedDict()
    for r in rows:
        run = runs.setdefault(r["timestamp"], {"timestamp": r["timestamp"], "items": OrderedDict()})
        key = (r["keyword"], r["device"], r["ad_type"])
        item = run["items"].setdefault(key, {"keyword": r["keyword"], "device": r["device"], "ad_type": r["ad_type"],
                                             "page1": [], "page1_total": 0, "hit_page1": None, "no_block": False,
                                             "hit_more": None, "more_total": None, "more_checked": False})
        if r["source"] == "1page":
            if r["total"] == "-1":
                item["no_block"] = True
            elif r["rank"]:
                item["page1"].append({"rank": int(r["rank"]), "site": r["site"], "url": r["url"],
                                      "title": r["title"], "landing": r["landing"], "hit": r["target_hit"] == "Y"})
                item["page1_total"] = int(r["total"] or 0)
                if r["target_hit"] == "Y" and item["hit_page1"] is None:
                    item["hit_page1"] = int(r["rank"])
        else:
            item["more_checked"] = True
            if r["target_hit"] == "Y" and r["rank"]:
                item["hit_more"] = int(r["rank"])
                item["more_total"] = int(r["total"]) if r["total"] else None
            elif r["total"]:
                item["more_total"] = int(r["total"])
    out = []
    for run in runs.values():
        out.append({"timestamp": run["timestamp"], "items": list(run["items"].values())})
    out.sort(key=lambda x: x["timestamp"], reverse=True)
    return out


# ---------- 라우트 ----------
@app.get("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/api/settings")
def api_get_settings():
    return jsonify(load_settings())


@app.post("/api/settings")
def api_save_settings():
    s = load_settings()
    body = request.get_json(force=True) or {}
    for k in DEFAULT_SETTINGS:
        if k in body:
            s[k] = body[k]
    s["keywords"] = [k.strip() for k in s["keywords"] if k.strip()]
    s["pc_keywords"] = [k.strip() for k in s.get("pc_keywords", []) if k.strip()]
    s["target"] = s["target"].strip().lower()
    save_settings(s)
    return jsonify(s)


@app.get("/api/status")
def api_status():
    logged = STATE_FILE.exists() and "NID_AUT" in STATE_FILE.read_text(encoding="utf-8")
    info = load_login_info()
    # 비밀번호는 절대 내보내지 않는다 — 아이디와 확인 시각만
    return jsonify({**job, "login_file": logged, "login_id": info.get("id", ""), "login_checked_at": info.get("checked_at", ""),
                    "auto_login": bool(load_credentials())})


@app.post("/api/run")
def api_run():
    with job_lock:
        if job["running"]:
            return jsonify({"ok": False, "msg": "이미 실행 중입니다."}), 409
        body = request.get_json(force=True) or {}
        s = load_settings()
        keywords = [k.strip() for k in body.get("keywords", s["keywords"]) if k.strip()]
        pc_keywords = [k.strip() for k in body.get("pc_keywords", s.get("pc_keywords", [])) if k.strip()]
        target = (body.get("target", s["target"]) or "").strip().lower()
        device = body.get("device", s["device"])
        headless = bool(body.get("headless", s["headless"]))
        delay = float(body.get("delay", s["delay"]) or 3)
        pc_target = (body.get("pc_target", s.get("pc_target", "")) or "").strip()
        types = [t for t in body.get("types", s.get("types")) or [] if t in ("powerlink", "powercontents")]
        if not types:
            return jsonify({"ok": False, "msg": "광고 유형을 하나 이상 선택하세요."}), 400
        if ("powerlink" in types and not keywords) and ("powercontents" in types and not pc_keywords):
            return jsonify({"ok": False, "msg": "키워드를 입력하세요."}), 400
        if "powerlink" not in types: keywords = []
        if "powercontents" not in types: pc_keywords = []
        if not keywords and not pc_keywords:
            return jsonify({"ok": False, "msg": "선택한 유형의 키워드를 입력하세요."}), 400
        save_settings({**s, "keywords": body.get("keywords", s["keywords"]), "pc_keywords": body.get("pc_keywords", s.get("pc_keywords", [])),
                       "target": target, "pc_target": pc_target, "device": device, "headless": headless, "delay": delay, "types": types})
        devices = ["pc", "mobile"] if device == "both" else [device]
        job.update(running=True, log=[], started=datetime.now().isoformat(timespec="seconds"), finished=None, error=None)
        _log(f"시작: 파워링크 {len(keywords)}개 / 파워컨텐츠 {len(pc_keywords)}개 / 기기 {', '.join(devices)} / 도메인 {target or '(없음)'} / 브랜드명 {pc_target or target or '(없음)'}")
        threading.Thread(target=_worker, args=(keywords, devices, target, headless, delay, types, pc_target, pc_keywords), daemon=True).start()
    return jsonify({"ok": True})


@app.get("/api/results")
def api_results():
    limit = int(request.args.get("limit", 200))
    return jsonify(load_results()[:limit])


@app.post("/api/login")
def api_login():
    """별도 창으로 login.py 실행 (credentials.json이 있으면 자동 로그인, 없으면 수동 로그인 창)"""
    if job["running"]:
        return jsonify({"ok": False, "msg": "순위 체크가 끝난 뒤 실행하세요."}), 409
    subprocess.Popen([sys.executable, str(BASE_DIR / "login.py")], cwd=str(BASE_DIR),
                     creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
    return jsonify({"ok": True})


if __name__ == "__main__":
    url = f"http://{HOST}:{PORT}"
    print(f"파워링크 순위 대시보드: {url}   (종료: Ctrl+C 또는 창 닫기)")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host=HOST, port=PORT, debug=False, threaded=True)
