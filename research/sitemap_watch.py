"""병원 공식 사이트의 sitemap.xml 에서 '새로 생긴 URL'을 찾는다. Playwright 없이 표준 라이브러리만 쓴다.
- 기준선(logs/watch_state.json 의 "sm:<사이트맵 주소>")과 비교해 처음 보는 URL 만 신규로 본다.
- 기준선이 없는 첫 실행만 lastmod(수정일)가 기간 안인 URL 을 보여 준다 → 레코드 note 에 구분 표시.
- 입력: research/targets.json 의 "sitemaps": {병원: [sitemap.xml 또는 robots.txt 주소, ...]}
"""
import gzip
import re
import ssl
import time
import urllib.request
from datetime import date, datetime

CTX = ssl.create_default_context()
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
SKIP = re.compile(r"\.(jpg|jpeg|png|gif|webp|svg|pdf|css|js)(\?|$)|/(login|logout|join|sitemap|myreg)\b|list\.htm|[?&](p|page|board)=", re.I)
BULK = 40   # 같은 날짜 lastmod 가 이만큼 넘으면 사이트 일괄 갱신으로 보고, 기사처럼 보이는 URL(슬러그에 하이픈 3개 이상)만 남긴다


def get(url, limit=3_000_000):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=15, context=CTX) as r:
        raw = r.read(limit)
        if r.headers.get("Content-Encoding") == "gzip" or url.endswith(".gz"):
            try:
                raw = gzip.decompress(raw)
            except OSError:
                pass
    return raw.decode("utf-8", "ignore")


def sitemap_urls(root, depth=0, seen=None, cap=40):
    """sitemap(또는 robots.txt)에서 [(loc, lastmod)] — 인덱스는 하위 사이트맵을 따라간다(최대 cap 개)"""
    seen = seen if seen is not None else set()
    if root in seen or len(seen) > cap:
        return []
    seen.add(root)
    try:
        t = get(root)
    except Exception:                                  # noqa: BLE001
        return []
    if root.endswith("robots.txt"):
        out = []
        for m in re.findall(r"(?i)sitemap:\s*(\S+)", t):
            out += sitemap_urls(m, depth + 1, seen, cap)
        return out
    if "<sitemapindex" in t and depth < 3:
        out = []
        for loc in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", t):
            out += sitemap_urls(loc, depth + 1, seen, cap)
        return out
    out = []
    for blk in re.findall(r"<url>(.*?)</url>", t, re.S):
        loc = re.search(r"<loc>\s*([^<\s]+)\s*</loc>", blk)
        lm = re.search(r"<lastmod>\s*([^<\s]+)\s*</lastmod>", blk)
        if loc:
            out.append((loc[1], lm[1][:10] if lm else None))
    return out


def page_title(url):
    """(제목, 메타 설명) — 제목이 사이트 공통 문구인 사이트가 있어 설명도 함께 가져온다"""
    try:
        t = get(url, 200_000)
        m = re.search(r"<title[^>]*>(.*?)</title>", t, re.S | re.I)
        d = re.search(r"""<meta[^>]+(?:name|property)=["'](?:description|og:description)["'][^>]+content=["']([^"']*)""", t, re.I)

        def clean(x):
            return re.sub(r"\s+", " ", x.replace("&amp;", "&")).strip()
        return (clean(m[1])[:140] if m else ""), (clean(d[1])[:200] if d else "")
    except Exception:                                  # noqa: BLE001
        return "", ""


def _d(lm):
    try:
        return date.fromisoformat(lm[:10]) if lm else None
    except ValueError:
        return None


def collect(cfg, since, until, state=None, per_hospital=40):
    """(records, summary) — 레코드는 collect.py 의 표준 레코드 형식"""
    records, summary = [], {"status": "ok", "count": 0, "searches": 0, "note": ""}
    state = state if state is not None else {}
    for hospital, roots in cfg.get("sitemaps", {}).items():
        if hospital.startswith("_"):
            continue
        hits, fresh = {}, set()
        for root in roots:
            summary["searches"] += 1
            urls = [(loc, lm) for loc, lm in sitemap_urls(root) if not SKIP.search(loc)]
            if not urls:
                continue
            key = "sm:" + root
            prev = set(state.get(key, []))
            state[key] = sorted(prev | {loc for loc, _ in urls})
            if prev:                                   # 기준선이 있으면 '새로 생긴 URL'만 신규(수정일 잡음 없음)
                for loc, lm in urls:
                    if loc not in prev and loc not in hits:
                        hits[loc] = _d(lm) or until
                        fresh.add(loc)
                continue
            for loc, lm in urls:                       # 첫 실행: 기준선 저장 + lastmod 가 기간 안인 URL(수정일 기준)
                d = _d(lm)
                if d and since <= d <= until and loc not in hits:
                    hits[loc] = d
        by_day = {}
        for loc, d in hits.items():
            by_day.setdefault(d, []).append(loc)
        bulk_days = {d for d, v in by_day.items() if len(v) > BULK and not set(v) & fresh}
        hits = {loc: d for loc, d in hits.items()
                if d not in bulk_days or re.search(r"/(k-medi|blog|ab-blog|column|medical-column|news|notice|bbs)\b", loc)}
        if bulk_days:
            summary["note"] += f"{hospital}: {', '.join(sorted(x.isoformat() for x in bulk_days))} 일괄 갱신 의심(블로그·K-medi·뉴스·칼럼 경로만 유지). "
        for loc, d in sorted(hits.items(), key=lambda x: x[1], reverse=True)[:per_hospital]:
            time.sleep(0.7)
            title, desc = page_title(loc)
            records.append({"channel": "sitemap", "hospital": hospital, "query": "sitemap", "url": loc, "date": d.isoformat(),
                            "title": title or loc.rsplit("/", 1)[-1][:80], "text": (title + " — " + desc)[:300], "engagement": "",
                            "note": ("사이트맵에 새로 생긴 URL(이전 수집에 없음)" if loc in fresh
                                     else "사이트맵 lastmod(수정일일 수 있음, 게시일 아님)"), "author_key": ""})
            summary["count"] += 1
        if len(hits) > per_hospital:
            summary["note"] += f"{hospital} {len(hits)}건 중 최근 {per_hospital}건만. "
    return records, summary
