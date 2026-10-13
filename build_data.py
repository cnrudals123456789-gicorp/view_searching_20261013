"""results_YYYYMMDD.csv 들을 모아 웹 대시보드용 docs/data.json 을 만든다.
사용: python -I build_data.py <순위체크_프로그램 폴더> [출력 data.json 경로]
요약 규칙은 순위체크_프로그램/summary.py 의 summarize() 와 같다 (openpyxl 불필요)."""
import csv, json, re, sys
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

src = Path(sys.argv[1])
out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).parent / "docs" / "data.json"
settings = json.loads((src / "settings.json").read_text(encoding="utf-8"))

runs = OrderedDict()
for f in sorted(src.glob("results_*.csv")):
    if not re.fullmatch(r"results_\d{8}\.csv", f.name):   # _구버전, _old 제외
        continue
    with open(f, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            if not r.get("ad_type"):
                continue
            run = runs.setdefault(r["timestamp"], {t: OrderedDict() for t in ("powerlink", "powercontents")})
            if r["ad_type"] not in run:
                continue
            cell = run[r["ad_type"]].setdefault(r["keyword"], {})
            dev, cur = r["device"], run[r["ad_type"]][r["keyword"]].get(r["device"])
            if r["source"] == "1page":
                if r["total"] == "-1":
                    cell[dev] = ["영역없음", "none", ""]
                elif r["target_hit"] == "Y":
                    cell[dev] = [int(r["rank"]), "1page", f"첫 화면 {r['total']}개 중"]
                elif cur is None:
                    cell[dev] = ["미노출", "none", f"첫 화면 {r['total']}개"]
            elif r["source"] == "more" and (cur is None or cur[1] == "none"):
                if r["target_hit"] == "Y":
                    tot = f"(전체 {r['total']}개)" if r["total"] else ""
                    cell[dev] = [int(r["rank"]), "more", f"더보기 목록 {tot}".strip()]
                else:
                    cell[dev] = ["미노출", "none", f"더보기 {r['total']}개까지 확인"]

order = {"powerlink": settings["keywords"], "powercontents": settings["pc_keywords"]}
data_runs = []
for ts in sorted(runs):
    items = {}
    for t, kws in runs[ts].items():
        if not kws:
            continue
        pref = [k for k in order[t] if k in kws] + [k for k in kws if k not in order[t]]
        items[t] = [[k, kws[k].get("pc"), kws[k].get("mobile")] for k in pref]
    if sum(len(v) for v in items.values()) >= 15:   # 일부 키워드만 돈 시험·재확인 회차 제외
        data_runs.append({"ts": ts[:16], "items": items})

doc = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"), "target": settings["target"],
       "pc_target": settings["pc_target"], "order": order, "runs": data_runs}
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print(f"{out}  runs={len(data_runs)}  {out.stat().st_size//1024}KB")
