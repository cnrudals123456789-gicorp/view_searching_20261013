"""competitor.json 백업·검증·중복 점검.
  python -I research/validate.py --backup
  python -I research/validate.py --check    # 문제 있는 항목만 격리(나머지는 살림). 파일 자체가 깨졌을 때만 백업으로 복구, exit 1
  python -I research/validate.py --dupes    # 지난 달 포함 중복 후보 목록 (수정 없이 출력만)

--check 의 격리 규칙
  - 필수 필드 누락 / URL 없음·형식 오류 / 날짜·hl·감정 값 오류 / id·URL 중복인 항목은 파일에서 빼고 logs/competitor_rejected.json 에 사유와 함께 저장
  - 격리 대상이 백업에도 있던 항목(같은 id)이면 삭제하지 않고 백업 버전으로 되돌림
"""
import calendar
import hashlib
import json
import re
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILE = ROOT / "docs" / "competitor.json"
BAK = ROOT / "logs" / "competitor.json.bak"
REJ = ROOT / "logs" / "competitor_rejected.json"
KEEP_DAYS = 30        # 마지막 확인일 기준 보관 기간. 넘으면 폐기
ARCHIVE_DAYS = 365    # 폐기한 URL 해시(재수집 방지용)를 보관하는 기간

# 접근 가능한 것으로 확인된 채널만 필수로 본다(2026-10-19 확인). 로그인·차단 채널(TikTok·X·Dcard·Threads·Pinterest 등)은 제외.
REQUIRED_CHANNELS = [
    "공식홈페이지", "뉴스", "네이버블로그", "네이버카페", "Instagram", "YouTube", "Ameblo", "Note",
    "Yahoo리얼타임", "知恵袋", "PTT", "Pantip", "Reddit",
]
NOVELTY = {None, "new_method", "new_market", "continuation", "other"}
ITEM_KEYS = {"id", "date", "found", "last_seen", "hospital", "channel", "kind", "title", "why", "view", "source", "url", "hl"}
REVIEW_KEYS = {"date", "found", "last_seen", "hospital", "platform", "sentiment", "summary", "url", "author_key"}
HL = {None, "industry", "hospital"}
SENT = {"긍정", "중립", "부정"}
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
URL = re.compile(r"^https?://\S+$")


TRACKING = re.compile(r"^(utm_.*|fbclid|gclid|igsh|igshid|si|feature|ref|ref_src|ref_url|spm|from)$")


def norm_url(u):
    """중복 판별용 주소 정규화: 스킴·www·m·fragment·추적 파라미터·끝 슬래시는 무시하고, 글을 가리키는 파라미터(watch?v=, id=, logNo= 등)는 남긴다"""
    u = (u or "").strip().lower().replace("&amp;", "&")
    u = re.sub(r"^https?://(www\.|m\.)?", "", u).split("#")[0]
    base, _, query = u.partition("?")
    keep = sorted(p for p in query.split("&") if p and not TRACKING.match(p.split("=")[0]))
    m = re.match(r"youtu\.be/([\w-]+)", base)                        # youtu.be/ID == youtube.com/watch?v=ID
    if m:
        return "youtube.com/watch?v=" + m[1]
    return base.rstrip("/") + ("?" + "&".join(keep) if keep else "")


def norm_text(t):
    return re.sub(r"[^0-9a-z가-힣]", "", (t or "").lower())


def all_rows(d, key):
    for ym in sorted(d.get("months", {})):
        for i, r in enumerate(d["months"][ym].get(key, [])):
            yield ym, i, r


def dup_pairs(d, key, text_field):
    """(a, b, 사유) — 같은 URL 이거나 같은 병원·같은 제목이면 중복 후보"""
    seen_url, seen_txt, out = {}, {}, []
    for ym, i, r in all_rows(d, key):
        ref = f"{ym} {key}[{i}]"
        u = norm_url(r.get("url"))
        t = (r.get("hospital"), norm_text(r.get(text_field)))
        if u and u in seen_url:
            out.append((seen_url[u], ref, "같은 URL"))
        elif u:
            seen_url[u] = ref
        if t[1] and t in seen_txt:
            out.append((seen_txt[t], ref, "같은 병원·같은 제목"))
        elif t[1]:
            seen_txt[t] = ref
    return out


def entry_problems(kind, r):
    """항목 하나의 문제 사유 목록 (없으면 빈 리스트)"""
    p = []
    if not isinstance(r, dict):
        return ["객체가 아님"]
    miss = (ITEM_KEYS if kind == "items" else REVIEW_KEYS) - r.keys()
    if miss:
        p.append(f"필드 누락: {sorted(miss)}")
    if not URL.match(str(r.get("url") or "")):
        p.append(f"url 없음/형식 오류(출처 URL 필수): {r.get('url')!r}")
    for k in ("found", "last_seen"):
        if r.get(k) and not DATE.match(str(r[k])):
            p.append(f"{k} 날짜 형식 오류: {r[k]}")
    if r.get("found") and r.get("last_seen") and r["last_seen"] < r["found"]:
        p.append("last_seen 이 found 보다 빠름")
    if kind == "items":
        if r.get("hl") not in HL:
            p.append(f"hl 값 오류: {r.get('hl')}")
        if r.get("hl") and not r.get("hl_reason"):
            p.append("hl_reason 없음")
        if r.get("novelty") not in NOVELTY:                          # 없으면(None) 기존 항목으로 보고 통과
            p.append(f"novelty 값 오류: {r.get('novelty')}")
        if str(r.get("novelty") or "").startswith("new_") and not r.get("novelty_reason"):
            p.append("novelty_reason 없음(신규로 판정했으면 무엇이 처음인지 근거 필요)")
    elif r.get("sentiment") not in SENT:
        p.append(f"sentiment 값 오류: {r.get('sentiment')}")
    return p


def quarantine(d, base):
    """문제 항목을 빼서 (정리된 d, 격리 목록) 반환. 백업에 같은 id 가 있으면 백업 버전으로 되돌린다."""
    old = {}
    for key in ("items", "reviews"):
        for _, _, r in all_rows(base or {}, key):
            if isinstance(r, dict) and r.get("id"):
                old[(key, r["id"])] = r
    rejected, seen_id, seen_url = [], set(), set()
    for ym in sorted(d["months"]):
        m = d["months"][ym]
        if not isinstance(m, dict):
            rejected.append({"month": ym, "kind": "month", "reasons": ["월 데이터가 객체가 아님"], "data": m})
            continue
        for key in ("items", "reviews"):
            keep = []
            for r in m.get(key, []):
                reasons = entry_problems(key, r)
                if isinstance(r, dict):
                    if key == "items" and r.get("id") in seen_id:
                        reasons.append(f"id 중복: {r['id']}")
                    u = norm_url(r.get("url"))
                    if u and (key, u) in seen_url:
                        reasons.append("같은 URL 이 이미 있음(중복)")
                    if u and url_hash(u) in d.get("seen_urls", {}):
                        reasons.append("보관 기간이 지나 폐기된 자료의 URL(재수집 불필요)")
                if reasons:
                    rejected.append({"month": ym, "kind": key, "reasons": reasons, "data": r})
                    prev = old.get((key, r.get("id"))) if isinstance(r, dict) else None
                    if prev and not entry_problems(key, prev):
                        keep.append(prev)
                        rejected[-1]["restored_from_backup"] = True
                        r = prev
                    else:
                        continue
                if key == "items":
                    seen_id.add(r.get("id"))
                if norm_url(r.get("url")):
                    seen_url.add((key, norm_url(r.get("url"))))
                if r not in keep:
                    keep.append(r)
            m[key] = keep
        runs = [x for x in m.get("runs", []) if isinstance(x, dict) and DATE.match(str(x.get("date", "")))]
        if len(runs) != len(m.get("runs", [])):
            rejected.append({"month": ym, "kind": "runs", "reasons": ["runs 날짜 형식 오류 항목 제거"], "data": None})
        if "runs" in m:
            m["runs"] = runs
    return d, rejected


def url_hash(u):
    return hashlib.sha1(norm_url(u).encode("utf-8")).hexdigest()[:10]


def prune(d, today=None):
    """KEEP_DAYS 일(마지막 확인일 last_seen 기준) 넘은 항목·후기를 폐기한다. 폐기한 URL 은 짧은 해시로만 남겨 같은 글이 재수집되지 않게 한다.
    항목이 모두 없어지고 월말이 기준일보다 오래된 달은 통째로 삭제(만족도 집계 포함). (폐기 건수, 삭제한 달 목록) 반환."""
    today = today or date.today()
    cutoff = (today - timedelta(days=KEEP_DAYS)).isoformat()
    arch = d.setdefault("seen_urls", {})
    dropped, gone = 0, []
    for ym in sorted(d["months"]):
        m = d["months"][ym]
        for key in ("items", "reviews"):
            keep = []
            for r in m.get(key, []):
                ref = str(r.get("last_seen") or r.get("found") or r.get("date") or "9999")
                if ref < cutoff:
                    dropped += 1
                    if norm_url(r.get("url")):
                        arch[url_hash(r["url"])] = ref
                else:
                    keep.append(r)
            if key in m:
                m[key] = keep
        y, mo = map(int, ym.split("-"))
        month_end = date(y, mo, calendar.monthrange(y, mo)[1]).isoformat()
        if not m.get("items") and not m.get("reviews") and month_end < cutoff:
            gone.append(ym)
            del d["months"][ym]
    if str(d.get("manual_check_at") or "9999")[:10] < cutoff:      # 한 달 넘은 '직접 확인 필요' 목록은 폐기
        d.pop("manual_check", None)
        d.pop("manual_check_at", None)
    old = (today - timedelta(days=ARCHIVE_DAYS)).isoformat()
    for h in [h for h, ref in arch.items() if ref < old]:
        del arch[h]
    return dropped, gone


def merge_manual(d):
    """최신 수집 결과의 manual_check(CAPTCHA·로그인 등으로 직접 확인이 필요한 검색)를 최상위 manual_check 로 교체해 넣는다.
    이미 반영한 수집 결과(manual_check_at 이 같거나 더 새로움)면 건드리지 않는다. 반영했으면 True."""
    files = sorted((ROOT / "logs" / "raw").glob("collect_*.json"))
    if not files:
        return False
    try:
        c = json.loads(files[-1].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    at = str(c.get("at") or "")
    if not at or at <= str(d.get("manual_check_at") or ""):
        return False
    keep = ("channel", "hospital", "query", "url", "reason", "at")
    d["manual_check"] = [{k: x.get(k, "") for k in keep} for x in c.get("manual_check", [])
                         if isinstance(x, dict) and URL.match(str(x.get("url") or ""))]
    d["manual_check_at"] = at
    return True


def warnings(d):
    w = []
    for a, b, why in dup_pairs(d, "items", "title") + dup_pairs(d, "reviews", "summary"):
        w.append(f"중복 의심: {a} ~ {b} ({why})")
    if d.get("months"):
        last = max(d["months"])
        cov = d["months"][last].get("coverage", {})
        miss = [c for c in REQUIRED_CHANNELS if c not in cov]
        if miss:
            w.append(f"{last} coverage 에 없는 채널: {', '.join(miss)}")
        if not d["months"][last].get("runs"):
            w.append(f"{last} runs(조사 이력) 비어 있음")
    return w


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def restore(msg):
    print("[검증 실패]", msg)
    if BAK.exists():
        shutil.copyfile(BAK, FILE)
        print("[복구] 백업으로 되돌림")
    return 1


def main():
    # -I 실행에서는 PYTHONUTF8이 무시되므로 일본어·중국어 채널명 출력이 cp949에서 깨지지 않게 한다
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8", errors="replace")
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "--backup":
        BAK.parent.mkdir(exist_ok=True)
        if FILE.exists():
            shutil.copyfile(FILE, BAK)
        return 0
    if mode == "--dupes":
        try:
            d = load(FILE)
        except (OSError, ValueError) as e:
            print("읽기/파싱 실패:", e)
            return 1
        for w in warnings(d):
            if w.startswith("중복"):
                print(w)
        return 0
    if mode == "--check":
        try:
            d = load(FILE)
        except (OSError, ValueError) as e:
            return restore(f"읽기/파싱 실패: {e}")
        if not isinstance(d, dict) or not isinstance(d.get("months"), dict):
            return restore("최상위 months 객체가 없음")
        try:
            base = load(BAK) if BAK.exists() else None
        except (OSError, ValueError):
            base = None
        d, rejected = quarantine(d, base)
        dropped, gone = prune(d)
        merged = merge_manual(d)
        if rejected:
            REJ.parent.mkdir(exist_ok=True)
            REJ.write_text(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), "rejected": rejected},
                                      ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[격리] 문제 항목 {len(rejected)}건을 제외하고 나머지는 살렸습니다 (사유: logs/competitor_rejected.json)")
            for r in rejected:
                print("  -", r["month"], r["kind"], "; ".join(r["reasons"]), "(백업 버전으로 복구)" if r.get("restored_from_backup") else "")
        if dropped or gone:
            print(f"[폐기] 마지막 확인일이 {KEEP_DAYS}일 넘은 자료 {dropped}건 삭제" + (f", 빈 달 삭제: {', '.join(gone)}" if gone else ""))
        if merged:
            print(f"[직접 확인 필요] 수집 결과 {len(d.get('manual_check', []))}건 반영 ({d['manual_check_at']})")
        if rejected or dropped or gone or merged:
            FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for w in warnings(d):
            print("[경고]", w)
        print("[검증 통과]")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
