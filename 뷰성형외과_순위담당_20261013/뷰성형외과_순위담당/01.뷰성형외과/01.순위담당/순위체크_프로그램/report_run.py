"""
정규 회차(10:10·16:00, 2026-10-12 09:00→10:10 변경) 종료 후 에이전트 리더 대시보드 자동 보고 (자동순위체크.bat 이 마지막에 호출)
  python report_run.py --status ok              # 성공: 오늘 results 마지막 회차 요약 → msg rank
  python report_run.py --status fail --tries 4  # 실패: rank 상태 fail + 업무(실패)·결정필요·알림
  python report_run.py --status ok --dry-run    # 대시보드에 쓰지 않고 보고 내용만 출력 (검증용)
- 요약: 1위 개수, 첫 화면 미노출 수, 직전 회차 대비 상승/하락 주요 키워드
- 직전 정규 회차가 결과 없이 비어 있으면(미실행·실패) 함께 알림
디렉터 님 승인(2026-10-06, 업무 71)
"""
import argparse
import csv
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from summary import SHEETS, summarize

HERE = Path(__file__).resolve().parent
from paths import BOARD
ENV = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
DEV = {"pc": "PC", "mobile": "MO"}
DRY = False


def board(*args):
    if DRY:
        print("[dry-run] board_update.py", " | ".join(args))
        return ""
    try:
        r = subprocess.run([sys.executable, str(BOARD), *args], capture_output=True, text=True, env=ENV, timeout=60)
        return r.stdout.strip()
    except Exception as e:
        print("board 오류", e, flush=True)
        return ""


def load_runs():
    """results_*.csv 전체 → {timestamp: [rows]} (최근 14일 파일만)"""
    runs = {}
    cutoff = f"{datetime.now() - timedelta(days=14):%Y%m%d}"
    for p in sorted(HERE.glob("results_????????.csv")):
        if p.stem[8:] < cutoff:
            continue
        for r in csv.DictReader(open(p, encoding="utf-8-sig")):
            try:
                r["total"] = int(r["total"])
            except ValueError:
                pass
            runs.setdefault(r["timestamp"], []).append(r)
    return runs


def flat(rows):
    """{(ad_type, keyword, device): (value, kind)}"""
    out = {}
    for t, kws in summarize(rows).items():
        for kw, devs in kws.items():
            for dev, (v, kind, _) in devs.items():
                out[(t, kw, dev)] = (v, kind)
    return out


def label(k):
    t, kw, dev = k
    return f"{kw} {SHEETS[t]}{DEV.get(dev, dev)}"


def slot_now(now):
    """정규 회차(10:10·16:00 직후 1시간 이내)면 회차명, 아니면 '수동'"""
    if (10, 10) <= (now.hour, now.minute) < (11, 10):
        return "10:10 정규"
    if 16 <= now.hour < 17:
        return "16:00 정규"
    return f"{now:%H:%M} 수동"


def prev_slot_missing(runs, now):
    """직전 정규 회차 구간에 결과가 하나도 없으면 그 회차 이름을 돌려준다."""
    if now.hour < 12:
        d = now - timedelta(days=1)
        lo, hi, name = d.replace(hour=15, minute=30), d.replace(hour=23, minute=59), f"{d:%m-%d} 16:00"
    else:
        lo, hi, name = now.replace(hour=9, minute=40), now.replace(hour=15, minute=30), f"{now:%m-%d} 10:10"
    fmt = "%Y-%m-%d %H:%M:%S"
    for ts in runs:
        try:
            if lo <= datetime.strptime(ts, fmt) <= hi:
                return None
        except ValueError:
            pass
    return name


def report_ok(now):
    runs = load_runs()
    tss = sorted(runs)
    if not tss or not tss[-1].startswith(f"{now:%Y-%m-%d}"):
        return report_fail(now, 0, "run.py 는 성공했지만 오늘 결과 CSV를 찾지 못함")
    cur_ts = tss[-1]
    cur = flat(runs[cur_ts])
    prev_ts = tss[-2] if len(tss) > 1 else None
    prev = flat(runs[prev_ts]) if prev_ts else {}

    first = [k for k, (v, kind) in cur.items() if v == 1 and kind == "1page"]
    miss = [k for k, (v, kind) in cur.items() if kind != "1page"]
    prev_miss = [k for k, (v, kind) in prev.items() if kind != "1page"]
    ups, downs = [], []
    for k, (v, _) in cur.items():
        pv = prev.get(k, (None, None))[0]
        if isinstance(v, int) and isinstance(pv, int) and v != pv:
            (ups if v < pv else downs).append((abs(v - pv), f"{label(k)} {pv}→{v}"))
        elif isinstance(v, int) and pv == "미노출":
            ups.append((99, f"{label(k)} 미노출→{v}"))
        elif v == "미노출" and isinstance(pv, int):
            downs.append((99, f"{label(k)} {pv}→미노출"))
    top = lambda xs: ", ".join(s for _, s in sorted(xs, key=lambda x: -x[0])[:6]) or "없음"
    n_pl = sum(1 for k in first if k[0] == "powerlink")
    lines = [
        f"[자동보고] {now:%m-%d} {slot_now(now)} 순위체크 완료 (실행 {cur_ts[11:16]}, {len(cur)}조합)",
        f"※ 1위 {len(first)}개 (파워링크 {n_pl} · 파워컨텐츠 {len(first) - n_pl}) / 첫 화면 미노출 {len(miss)}/{len(cur)}"
        + (f" (직전 {len(prev_miss)})" if prev else ""),
        f"▶ 상승 {len(ups)}: {top(ups)}",
        f"▶ 하락 {len(downs)}: {top(downs)}",
        f"비교 기준: 직전 회차 {prev_ts[:16] if prev_ts else '없음'}",
    ]
    gap = prev_slot_missing(runs, now)
    if gap:
        lines.append(f"※ 직전 정규 회차({gap}) 결과 없음 — 미실행 또는 실패, 로그 확인 필요")
    # 2026-10-06 디렉터 님 지시: '모니터링완료_날짜_시각' 엑셀 사본 + 대시보드 순위표
    try:
        from publish_done import publish
        lines.append(f"※ 엑셀: {publish(f'{now:%Y-%m-%d}')}" if not DRY else "※ 엑셀: (dry-run) 모니터링완료 사본 생략")
    except Exception as e:
        lines.append(f"※ 모니터링완료 사본 오류: {e}")
    try:
        from rank_table import markdown
        lines += ["", markdown(f"{now:%Y-%m-%d}")]
    except Exception as e:
        lines.append(f"※ 순위표 생성 오류: {e}")
    text = "\n".join(lines)
    print(text)
    board("msg", "rank", text, "--status", "done")
    board("agent", "rank", "--status", "idle",
          "--note", f"{now:%m-%d} {slot_now(now)} 회차 완료: 1위 {len(first)} / 미노출 {len(miss)}")
    return 0


def last_error(now):
    log = HERE / "logs" / f"{now:%Y%m%d}.log"
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "로그 없음"
    errs = [l.strip() for l in lines if "Error" in l and ":" in l and not l.startswith(" ")]
    return errs[-1].replace("playwright._impl._errors.", "")[:160] if errs else "오류 문구 없음"


def report_fail(now, tries, reason=None):
    reason = reason or last_error(now)
    slot = slot_now(now)
    title = f"{now:%m-%d} {slot} 순위체크 실패 ({tries}회 재시도)"
    text = (f"[자동보고] {title}\n※ 마지막 오류: {reason}\n"
            f"▶ 인터넷/PC 절전 상태 확인 후 수동 재실행 필요 (01.뷰성형외과/01.순위담당 > 순위체크_프로그램 > 순위체크.bat)")
    print(text)
    task = board("newtask", "--owner", "뷰)순위담당", "--status", "fail", "--title", title,
                 "--detail", f"자동순위체크.bat 재시도 모두 실패. 로그 logs\\{now:%Y%m%d}.log", "--result", reason)
    if task and task.isdigit():
        board("decision", task, f"{now:%m-%d} {slot} 순위체크 실패 — 수동 재실행할지 결정 필요")
    board("msg", "rank", text, "--status", "fail")
    board("agent", "rank", "--status", "fail", "--note", f"{now:%m-%d %H:%M} {slot} 회차 실패: {reason[:60]}")
    return 0


def main():
    global DRY
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", choices=["ok", "fail"], required=True)
    ap.add_argument("--tries", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    DRY = a.dry_run
    now = datetime.now()
    return report_ok(now) if a.status == "ok" else report_fail(now, a.tries)


if __name__ == "__main__":
    raise SystemExit(main())
