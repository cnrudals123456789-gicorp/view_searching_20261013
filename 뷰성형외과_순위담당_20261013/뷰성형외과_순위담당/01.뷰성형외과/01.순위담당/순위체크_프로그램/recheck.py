"""
미노출 조합 재확인 (rank.py / common.py 함수 재사용, 기존 파일 수정 없음)

  python recheck.py                 # recheck_targets.json 의 (키워드, 매체, 기기) 조합만 재체크
  python recheck.py --build         # 오늘 results_YYYYMMDD.csv 마지막 회차로 recheck_targets.json 생성(미노출 목록)
  python recheck.py --build --run   # 생성 직후 바로 재체크
  python recheck.py --deep          # 미노출 시 더보기 목록 순위도 기록 (느림)
  python recheck.py --targets 파일.json

노출 기준: 파워링크 = 1페이지(통합검색 파워링크 영역) 노출, 파워컨텐츠 = 첫 화면 노출.
결과: recheck_YYYYMMDD.csv 에 체크 시각과 함께 누적. 노출된 조합은 targets 파일에서 제거.
표준출력 첫 줄 = "남은미노출 N", 이후 남은 조합 한 줄씩 ("키워드<TAB>매체<TAB>기기").
진행 로그는 표준에러로 출력. 로그인은 common.verify_logged_in 의 자동 로그인 사용.
종료코드: 0 정상 / 1 로그인 실패 / 3 체크 오류(네트워크 등, targets 파일은 그대로 유지)
"""
import argparse
import asyncio
import csv
import json
import random
import sys
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

import rank
from common import launch, verify_logged_in, BASE_DIR
from app import load_settings

TARGETS_FILE = BASE_DIR / "recheck_targets.json"
TYPE_KO = {"powerlink": "파워링크", "powercontents": "파워컨텐츠"}
DEV_KO = {"pc": "PC", "mobile": "MO"}
FIELDS = ["checked_at", "keyword", "ad_type", "device", "status", "rank", "total_1page", "more_rank", "more_total", "note"]


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def print_remain(targets):
    print(f"남은미노출 {len(targets)}")
    for t in targets:
        print(f"{t['keyword']}\t{TYPE_KO[t['ad_type']]}\t{DEV_KO[t['device']]}")
    sys.stdout.flush()


def load_targets(path):
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    items = data.get("targets", []) if isinstance(data, dict) else data
    return [{"keyword": t["keyword"], "ad_type": t["ad_type"], "device": t["device"]}
            for t in items if t.get("keyword") and t.get("ad_type") in TYPE_KO and t.get("device") in DEV_KO]


def save_targets(path, targets, source):
    data = {"updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "source": source,
            "rule": "파워링크=1페이지, 파워컨텐츠=첫 화면 노출 시 목록에서 제거", "targets": targets}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def build_from_results(settings):
    """오늘 results CSV의 마지막 회차(timestamp)에서 1페이지/첫 화면 미노출 조합을 만든다."""
    res = BASE_DIR / f"results_{datetime.now():%Y%m%d}.csv"
    if not res.exists():
        raise SystemExit(f"[!] {res.name} 이 없습니다. 먼저 python run.py 로 전체 체크를 실행하세요.")
    with open(res, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    last_ts = max(r["timestamp"] for r in rows)
    rows = [r for r in rows if r["timestamp"] == last_ts]
    hit = {(r["keyword"], r["ad_type"], r["device"]) for r in rows if r["source"] == "1page" and r["target_hit"] == "Y"}
    devices = ["pc", "mobile"] if settings.get("device", "both") == "both" else [settings["device"]]
    types = settings.get("types") or ["powerlink", "powercontents"]
    targets = []
    for ad_type, kws in (("powerlink", settings.get("keywords", [])), ("powercontents", settings.get("pc_keywords", []))):
        if ad_type not in types:
            continue
        for dev in devices:
            for kw in kws:
                if (kw, ad_type, dev) not in hit:
                    targets.append({"keyword": kw, "ad_type": ad_type, "device": dev})
    return targets, f"{res.name} @ {last_ts}"


async def check(targets, settings, headless, delay, deep):
    target = (settings.get("target") or "").lower()
    pc_target = (settings.get("pc_target") or target).strip()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    results = []
    async with async_playwright() as p:
        for device in ("pc", "mobile"):
            mine = [t for t in targets if t["device"] == device]
            if not mine:
                continue
            ctx = await launch(p, device, headless)
            try:
                page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                if not await verify_logged_in(ctx, page):
                    raise rank.NotLoggedIn("네이버 로그인 실패 (자동 로그인 포함)")
                kws = list(dict.fromkeys(t["keyword"] for t in mine))
                for i, kw in enumerate(kws):
                    types = {t["ad_type"] for t in mine if t["keyword"] == kw}
                    ads, more_url = await rank.fetch_ads(page, device, kw)
                    # 파워컨텐츠는 같은 검색 페이지에서 먼저 읽는다 (더보기 탐색으로 페이지를 떠나기 전)
                    if "powercontents" in types:
                        pcs = await rank.fetch_powercontents(page)
                        r = dict(checked_at=ts, keyword=kw, ad_type="powercontents", device=device, status="미노출",
                                 rank="", total_1page=len(pcs) if pcs is not None else -1,
                                 more_rank="", more_total="", note="")
                        if pcs is None:
                            r["note"] = "노출 영역 없음"
                        else:
                            h = next((a for a in pcs if rank._match_pc(a, pc_target)), None)
                            if h:
                                r.update(status="노출", rank=h["rank"])
                            elif deep:
                                allpc = await rank.expand_powercontents(page)
                                f = next((a for a in allpc if rank._match_pc(a, pc_target)), None)
                                r.update(more_rank=f["rank"] if f else "", more_total=len(allpc))
                        results.append(r)
                        log(f"[{DEV_KO[device]}] {kw} 파워컨텐츠: {r['status']} {r['rank']}".rstrip()
                            + (f" (더보기 {r['more_rank']}위)" if r["more_rank"] else ""))
                    if "powerlink" in types:
                        r = dict(checked_at=ts, keyword=kw, ad_type="powerlink", device=device, status="미노출",
                                 rank="", total_1page=len(ads), more_rank="", more_total="",
                                 note="" if ads else "1페이지 광고 없음")
                        h = next((a for a in ads if rank._match(a, target)), None)
                        if h:
                            r.update(status="노출", rank=h["rank"])
                        elif deep:
                            seen, mr, tot = await rank.search_more(page, device, more_url, target)
                            r.update(more_rank=mr or "", more_total=tot or len(seen))
                        results.append(r)
                        log(f"[{DEV_KO[device]}] {kw} 파워링크: {r['status']} {r['rank']}".rstrip()
                            + (f" (더보기 {r['more_rank']}위)" if r["more_rank"] else ""))
                    if i < len(kws) - 1:
                        await asyncio.sleep(random.uniform(delay, delay * 2))
            finally:
                await ctx.close()
    return results


def main():
    ap = argparse.ArgumentParser(description="미노출 조합 재확인")
    ap.add_argument("--targets", default=str(TARGETS_FILE))
    ap.add_argument("--build", action="store_true", help="오늘 results CSV 마지막 회차로 targets 생성")
    ap.add_argument("--run", action="store_true", help="--build 후 바로 재체크")
    ap.add_argument("--deep", action="store_true", help="미노출 시 더보기 순위도 기록 (느림)")
    ap.add_argument("--show", action="store_true", help="브라우저 창 표시")
    a = ap.parse_args()
    tpath = Path(a.targets)
    s = load_settings()

    if a.build:
        targets, src = build_from_results(s)
        save_targets(tpath, targets, src)
        log(f"targets 생성: {len(targets)}개 ({src})")
        if not a.run:
            print_remain(targets)
            return

    targets = load_targets(tpath)
    if not targets:
        print_remain([])
        return
    headless = False if a.show else bool(s.get("headless", True))
    try:
        results = asyncio.run(check(targets, s, headless, float(s.get("delay", 1) or 1), a.deep))
    except rank.NotLoggedIn as e:
        log(f"[!] {e}")
        print_remain(targets)
        sys.exit(1)
    except Exception as e:
        msg = str(e).splitlines()[0] if str(e) else ""
        log(f"[!] 체크 오류: {type(e).__name__}: {msg}")
        print_remain(targets)
        sys.exit(3)

    out = BASE_DIR / f"recheck_{datetime.now():%Y%m%d}.csv"
    new = not out.exists()
    with open(out, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerows(results)
    shown = {(r["keyword"], r["ad_type"], r["device"]) for r in results if r["status"] == "노출"}
    remain = [t for t in targets if (t["keyword"], t["ad_type"], t["device"]) not in shown]
    save_targets(tpath, remain, f"recheck @ {results[0]['checked_at'] if results else ''}")
    for r in results:
        if r["status"] == "노출":
            log(f"노출 확인, 목록 제외: {r['keyword']} {TYPE_KO[r['ad_type']]} {DEV_KO[r['device']]} {r['rank']}위")
    log(f"저장: {out.name} ({len(results)}행)")
    print_remain(remain)


if __name__ == "__main__":
    main()
