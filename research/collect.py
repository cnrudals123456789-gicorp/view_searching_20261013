"""Playwright 로 경쟁사 바이럴 원자료를 채널별로 수집한다 → logs/raw/collect_YYYYMMDD_HHMM.json (공개되지 않음).
  python -I research/collect.py                       # 전체 채널, 기간은 logs/research_params.json (없으면 최근 14일)
  python research/collect.py --only naver_blog,reddit --limit 2 --headed     # 점검용

원칙
  - 로그인·CAPTCHA·차단 화면이 보이면 우회하지 않고 그 채널을 즉시 멈춘다. 남은 검색은 manual_check(직접 확인 필요)로 기록한다.
  - 채널 하나가 실패해도 나머지는 계속한다. 요청 사이에 3~8초 무작위 간격을 둔다.
  - 계정 세션은 research/sns_login.py 로 만든 %LOCALAPPDATA%\\view_research\\profiles\\<사이트> 를 쓴다(instagram, x).
"""
import argparse
import hashlib
import json
import random
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import LOGIN_SITES, PROFILES, ROOT, UA  # noqa: E402
from make_prompt import period  # noqa: E402
import sitemap_watch  # noqa: E402

RAW = ROOT / "logs" / "raw"
TARGETS = Path(__file__).with_name("targets.json")
WATCH = ROOT / "logs" / "watch_state.json"       # 공식 페이지별로 이미 본 URL (신규 글 감지용)
WALL_CHANNELS = {"reddit", "x", "instagram", "tiktok"}   # 결과 0건 + 로그인 문구 = 로그인 벽으로 간주
LOGIN_CHANNELS = {"instagram", "x"}          # 세션 필요. tiktok 은 로그인 없이 시도, 막히면 건너뜀


class Blocked(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason                  # captcha | login_required | blocked


# ───────────────────────── 날짜 해석 ─────────────────────────
UNIT = {"분": "minutes", "시간": "hours", "일": "days", "주": "weeks", "개월": "months", "달": "months", "년": "years",
        "minute": "minutes", "hour": "hours", "day": "days", "week": "weeks", "month": "months", "year": "years",
        "分": "minutes", "時間": "hours", "日": "days", "週間": "weeks", "か月": "months", "ヶ月": "months", "年": "years"}


def parse_date(text, today=None):
    """본문 안의 첫 날짜 → date. 못 찾으면 None (상대 날짜: '3일 전', '3 days ago', '3日前')"""
    today = today or date.today()
    if not text:
        return None
    m = re.search(r"(20\d{2})[.\-/년\s]+(\d{1,2})[.\-/월\s]+(\d{1,2})", text)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            pass
    m = re.search(r"(\d+)\s*(분|시간|일|주|개월|달|년)\s*전", text) or \
        re.search(r"(\d+)\s*(minute|hour|day|week|month|year)s?\s*ago", text, re.I) or \
        re.search(r"(\d+)\s*(分|時間|日|週間|か月|ヶ月|年)前", text)
    if m:
        n, unit = int(m[1]), UNIT.get(m[2].lower(), "")
        days = {"minutes": 0, "hours": 0, "days": n, "weeks": n * 7, "months": n * 30, "years": n * 365}.get(unit)
        return today - timedelta(days=days) if days is not None else None
    if re.search(r"어제|yesterday|昨日", text, re.I):
        return today - timedelta(days=1)
    if re.search(r"오늘|today|今日", text, re.I):
        return today
    m = re.search(r"(\d{1,2})月(\d{1,2})日", text)               # 일본식 '10月15日' — 연도가 없으면 올해(미래면 작년)
    if m:
        try:
            d = date(today.year, int(m[1]), int(m[2]))
            return d if d <= today else date(today.year - 1, int(m[1]), int(m[2]))
        except ValueError:
            return None
    if re.match(r"\s*\d{1,2}:\d{2}\s*$", text):                   # 시각만 있으면 오늘 글(Yahoo!リアルタイム)
        return today
    return None


def iso_to_date(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone().date()
    except (ValueError, AttributeError):
        return None


# ───────────────────────── 차단 감지 ─────────────────────────
CAPTCHA_SEL = ('iframe[src*="recaptcha"], iframe[src*="captcha"], #captcha_container, '
               '.captcha_verify_container, .captcha-verify-container, #captcha-verify-container-main-page')
CAPTCHA_TEXT = ["자동입력 방지", "보안 문자", "로봇이 아닙니다", "verify you are human", "are you a robot", "captcha",
                "drag the slider", "whoa there, pardner", "blocked by network security", "access denied",
                "unusual traffic", "자동화된 접근", "접근이 제한", "too many requests", "verify to continue"]
LOGIN_TEXT = ["log in to continue", "로그인하여 계속", "sign in to continue", "로그인 후 이용", "log in or sign up",
              "로그인 또는 가입", "log in to see", "로그인하고 더 많은"]
ERROR_TEXT = ["문제가 발생했습니다", "something went wrong", "페이지를 읽어들이지 못했습니다", "페이지를 사용할 수 없습니다"]
LOGIN_URL = ["/accounts/login", "/i/flow/login", "x.com/login", "/login?", "tiktok.com/login"]


def body_text(page):
    try:
        return page.inner_text("body", timeout=4000)[:4000].lower()
    except Exception:                         # noqa: BLE001
        return ""


CHALLENGE_TEXT = ["verify you are human", "just a moment", "attention required", "access denied", "are you a robot",
                  "unusual traffic", "자동화된 접근", "접근이 제한", "too many requests"]


def check_block(page, resp=None, results=None, wall=False, strict=False):
    """strict=True(병원 공식 사이트): 문의 폼의 reCAPTCHA 문구를 차단으로 오인하지 않도록 HTTP 403/429 와 실제 확인 화면만 본다"""
    if resp is not None and resp.status in (403, 429):
        raise Blocked("blocked")
    if strict:
        t = body_text(page)
        if any(k in t for k in CHALLENGE_TEXT):
            raise Blocked("blocked")
        return
    url = page.url.lower()
    if any(u in url for u in LOGIN_URL):
        raise Blocked("login_required")
    try:
        if page.locator(CAPTCHA_SEL).first.is_visible(timeout=500):
            raise Blocked("captcha")
    except Blocked:
        raise
    except Exception:                         # noqa: BLE001
        pass
    t = body_text(page)
    if any(k in t for k in CAPTCHA_TEXT):
        raise Blocked("captcha")
    if results is not None and not results and (any(k in t for k in LOGIN_TEXT)
                                               or (wall and any(k in t for k in ("로그인", "log in", "sign in")))):
        raise Blocked("login_required")
    if results is not None and not results and wall and any(k in t for k in ERROR_TEXT):
        raise Blocked("blocked")                      # 사이트가 오류 화면을 보여줌 — '결과 없음'이 아니므로 직접 확인으로 넘김


def pause(lo=3.0, hi=8.0):
    time.sleep(random.uniform(lo, hi))


def goto(page, url, wait=None, wait_ms=9000):
    resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
    if wait:
        try:
            page.wait_for_selector(wait, timeout=wait_ms)
        except Exception:                     # noqa: BLE001  (결과 0건일 수 있음)
            pass
    else:
        page.wait_for_timeout(2500)
    return resp


# ───────────────────────── 공통 추출 ─────────────────────────
GENERIC_JS = """(o)=>{
  const root=document.querySelector(o.root)||document.body, out=new Map();
  root.querySelectorAll('a[href]').forEach(a=>{
    const h=a.href; if(!/^https?:/.test(h)) return;
    let u; try{u=new URL(h)}catch(e){return}
    if((o.skipHosts||[]).some(s=>u.hostname.endsWith(s))) return;
    if(o.hostRe && !new RegExp(o.hostRe).test(u.hostname+u.pathname)) return;
    const t=(a.innerText||'').trim(); if(t.length<o.minTitle) return;
    let el=a, block='';
    for(let i=0;i<6&&el;i++){ el=el.parentElement; if(el && (el.innerText||'').length>80){block=el.innerText;break} }
    const cur=out.get(h);
    if(!cur||t.length>cur.title.length) out.set(h,{url:h,title:t.slice(0,160),block:(block||t).slice(0,600)});
  });
  return [...out.values()];
}"""


def generic(page, root, host_re, skip=(), min_title=8):
    return page.evaluate(GENERIC_JS, {"root": root, "hostRe": host_re, "skipHosts": list(skip), "minTitle": min_title})


def mk(channel, hospital, q, raw):
    """원본 dict → 표준 레코드 (본문 300자, 작성자는 해시)"""
    text = re.sub(r"\s+", " ", raw.get("block") or raw.get("title") or "").strip()[:300]
    au = (raw.get("author") or "").strip()
    d = raw.get("date")
    return {"channel": channel, "hospital": hospital, "query": q, "url": raw.get("url", ""),
            "date": d.isoformat() if isinstance(d, date) else None,
            "title": re.sub(r"\s+", " ", raw.get("title") or "").strip()[:160], "text": text,
            "engagement": (raw.get("engagement") or "")[:40], "note": raw.get("note", ""),
            "author_key": hashlib.sha1(au.encode("utf-8")).hexdigest()[:10] if au else ""}


def terms_of(cfg, hospital):
    """병원 이름 판별용 검색어(소문자). (일반)은 None = 필터 없음"""
    h = cfg["hospitals"].get(hospital)
    if not h:
        return None
    t = {x.lower() for x in h["ko"] + h["en"] + h.get("ja", [])}
    t |= {" ".join(x.split()[:2]).lower() for x in h["en"]}
    if hospital not in ("ID", "DA", "AB"):                       # 짧은 영문 약칭은 오탐이 많아 접미어 제거 안 함
        t |= {re.sub(r"(성형외과|병원)$", "", x) for x in h["ko"] if len(re.sub(r"(성형외과|병원)$", "", x)) >= 2}
    return t


def date_of(raw):
    d = raw.get("date")
    if isinstance(d, str) and d:
        return iso_to_date(d) or parse_date(d)
    return parse_date(raw.get("block", ""))


# ───────────────────────── 채널 어댑터 ─────────────────────────
def nso(since, until):
    return quote(f"so:dd,p:from{since:%Y%m%d}to{until:%Y%m%d}", safe="")


def url_naver(kind):
    return lambda q, s, u: (f"https://search.naver.com/search.naver?ssc=tab.{kind}.all&sm=tab_opt"
                            f"&query={quote(q)}&nso={nso(s, u)}")


NAVER_SKIP = ("search.naver.com", "help.naver.com", "policy.naver.com", "keep.naver.com", "ader.naver.com",
              "nid.naver.com", "shopping.naver.com", "map.naver.com", "m.naver.com")


def ex_naver_blog(page, q, s, u, n):
    return generic(page, "#main_pack", r"blog\.naver\.com/[^/]+/\d+|blog\.naver\.com/PostView|tistory\.com/\d+|brunch\.co\.kr/@[^/]+/\d+|post\.naver\.com/viewer", NAVER_SKIP, 10)


def ex_naver_cafe(page, q, s, u, n):
    return generic(page, "#main_pack", r"cafe\.naver\.com/[^/]+/\d+|cafe\.naver\.com/ArticleRead", NAVER_SKIP, 10)


def ex_youtube(page, q, s, u, n):
    page.wait_for_timeout(1500)
    return page.evaluate("""(n)=>[...document.querySelectorAll('ytd-video-renderer')].slice(0,n).map(v=>{
        const a=v.querySelector('a#video-title'), meta=[...v.querySelectorAll('#metadata-line span')].map(x=>x.innerText);
        const ch=v.querySelector('ytd-channel-name a'), ds=v.querySelector('.metadata-snippet-text');
        return {url:a?a.href.split('&')[0]:'', title:a?(a.title||a.innerText):'',
                block:meta.join(' | ')+' '+(ds?ds.innerText:''), author:ch?ch.innerText:'', engagement:meta[0]||''}})""", n)


def ex_reddit(page, q, s, u, n):
    page.wait_for_timeout(2500)
    return page.evaluate(r"""(n)=>{const seen=new Map();
      document.querySelectorAll('a[href*="/comments/"]').forEach(a=>{
        const h=a.href.split('?')[0]; if(!/\/r\/[^/]+\/comments\//.test(h)||seen.has(h)) return;
        const t=(a.innerText||'').trim(); if(t.length<12) return;
        let el=a, b='', tm=''; for(let i=0;i<8&&el;i++){el=el.parentElement;
          if(el&&(el.innerText||'').length>120){b=el.innerText; const x=el.querySelector('time'); tm=x?x.getAttribute('datetime'):''; break}}
        seen.set(h,{url:h,title:t.slice(0,160),block:b.slice(0,500),date:tm})});
      return [...seen.values()].slice(0,n)}""", n)


def ex_x(page, q, s, u, n):
    for _ in range(3):
        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(1500)
    return page.evaluate("""(n)=>[...document.querySelectorAll('article')].slice(0,n).map(a=>{
        const tx=a.querySelector('[data-testid="tweetText"]'), t=a.querySelector('time'), l=t?t.closest('a'):null,
              un=a.querySelector('[data-testid="User-Name"]');
        const h=un?(un.innerText.split('\\n').find(x=>x.startsWith('@'))||''):'';
        return {url:l?l.href:'', title:(tx?tx.innerText:'').slice(0,100), block:tx?tx.innerText:'',
                date:t?t.getAttribute('datetime'):'', author:h}})""", n)


def ex_tiktok(page, q, s, u, n):
    page.wait_for_timeout(2500)
    items = page.evaluate("""(n)=>{const seen=new Map();
        document.querySelectorAll('a[href*="/video/"]').forEach(a=>{ if(!seen.has(a.href)){
          let el=a, b=''; for(let i=0;i<4&&el;i++){el=el.parentElement; if(el&&(el.innerText||'').length>10){b=el.innerText;break}}
          seen.set(a.href,{url:a.href.split('?')[0], title:(a.innerText||b).slice(0,100), block:b})}});
        return [...seen.values()].slice(0,n)}""", n)
    for it in items:                           # 영상 ID 의 상위 32비트 = 업로드 시각(초)
        m = re.search(r"/video/(\d+)", it["url"])
        if m:
            it["date"] = datetime.fromtimestamp(int(m[1]) >> 32).astimezone().isoformat()
        m = re.search(r"@([\w.]+)/video", it["url"])
        it["author"] = m[1] if m else ""
    return items


def ex_yahoo_rt(page, q, s, u, n):
    """Yahoo!リアルタイム検索: 로그인 없이 보이는 X 공개 글. 글 주소와 표시 시각(예: '10月15日(木) 15:06', '9:59')을 읽는다"""
    page.wait_for_timeout(2000)
    return page.evaluate(r"""(n)=>{const seen=new Map();
      document.querySelectorAll('a[href]').forEach(a=>{const h=a.href.split('?')[0];
        if(!/(x|twitter)\.com\/[^/]+\/status\/\d+$/.test(h)||seen.has(h)) return;
        let el=a, b=''; for(let i=0;i<7&&el;i++){el=el.parentElement; if(el&&(el.innerText||'').length>60){b=el.innerText;break}}
        const t=(a.innerText||'').trim();
        const au=(h.match(/\.com\/([^/]+)\/status/)||[])[1]||'';
        seen.set(h,{url:h,title:b.replace(/\s+/g,' ').slice(0,100),block:b.slice(0,500),date:/\d{1,2}:\d{2}/.test(t)?t:'',author:au})});
      return [...seen.values()].slice(0,n)}""", n)


def ex_chiebukuro(page, q, s, u, n):
    """Yahoo!知恵袋: 질문 주소와 '質問日時： 2026/9/19' 날짜"""
    return [dict(r, date=(re.search(r"20\d\d/\d{1,2}/\d{1,2}", r["block"]) or [""])[0].replace("/", "-"))
            for r in generic(page, "body", r"chiebukuro\.yahoo\.co\.jp/qa/question_detail/q\d+", (), 8)][:n]


def ex_ptt(page, q, s, u, n):
    """PTT facelift 게시판 검색 목록: 행마다 제목·작성자·날짜(월/일)"""
    rows = page.evaluate(r"""(n)=>[...document.querySelectorAll('div.r-ent')].slice(0,n).map(r=>{
        const a=r.querySelector('.title a'), d=r.querySelector('.date'), au=r.querySelector('.author');
        return {url:a?a.href:'', title:a?a.innerText.trim():'', block:a?a.innerText.trim():'', md:d?d.innerText.trim():'', author:au?au.innerText.trim():''}})""", n)
    today = date.today()
    for r in rows:
        m = re.match(r"(\d{1,2})/(\d{1,2})", r.pop("md", ""))
        if m:
            d = date(today.year, int(m[1]), int(m[2]))
            r["date"] = (d if d <= today else date(today.year - 1, int(m[1]), int(m[2]))).isoformat()
    return [r for r in rows if r["url"]]


def ex_naver_news(page, q, s, u, n):
    """네이버 뉴스(기간 필터·최신순): 언론사 기사 링크"""
    return generic(page, "#main_pack", r"^(?!.*search\.naver\.com).+/.{6,}", NAVER_SKIP + ("naver.com",), 15)[: n * 2]


def ex_instagram(page, tag, s, u, n):
    links = page.evaluate("""(n)=>[...new Set([...document.querySelectorAll('a[href*="/p/"],a[href*="/reel/"]')].map(a=>a.href))].slice(0,n)""", n)
    seen = set(STATE.get("ig:" + tag, []))
    STATE["ig:" + tag] = sorted(seen | {h.split("?")[0] for h in links})      # 다음엔 새 게시물만 연다
    links = [h for h in links if h.split("?")[0] not in seen]
    out = []
    for href in links:
        pause(2, 4)
        goto(page, href)
        check_block(page)
        d = page.evaluate("""()=>{const t=document.querySelector('time'), m=document.querySelector('meta[property="og:description"]'),
              ti=document.querySelector('meta[property="og:title"]');
              return {date:t?t.getAttribute('datetime'):'', block:m?m.content:'', title:ti?ti.content:''}}""")
        au = re.match(r"(.+?) on Instagram|(.+?)님의 Instagram", d.get("title") or "")
        d.update(url=href.split("?")[0], author=tag)
        out.append(d)
    return out


def ex_official(page, q, s, u, n):
    """공식 사이트 목록 페이지: 같은 사이트의 글 링크를 모은다 (Note·Ameblo 는 계정 경로까지 일치해야 함)"""
    host = re.sub(r"^https?://([^/]+).*", r"\1", page.url)
    path = re.sub(r"^https?://[^/]+", "", q).split("/")[1:2]
    if host in ("note.com", "ameblo.jp") and path:
        pat = re.escape(host) + "/" + re.escape(path[0]) + r"/(n/|entry-)"
    else:
        pat = re.escape(host) + r"/.+"
    page.wait_for_timeout(1500)
    raws = generic(page, "body", pat, (), 12)
    bad = re.compile(r"/(login|logout|join|member|privacy|terms|sitemap|search)\b|#|\.(jpg|png|pdf)$", re.I)
    return [r for r in raws if not bad.search(r["url"]) and r["url"].rstrip("/") != q.rstrip("/")]


def url_generic(fmt):
    return lambda q, s, u: fmt.format(q=quote(q), s=s.isoformat(), u=(u + timedelta(days=1)).isoformat(),
                                      qq=quote(f'"{q}"'), qs=quote(f'"{q}" since:{s.isoformat()} until:{(u + timedelta(days=1)).isoformat()}'))


def ex_hostre(host_re, root="body", min_title=8):
    return lambda page, q, s, u, n: generic(page, root, host_re, (), min_title)


CHANNELS = {
    # name: (kind, url_builder, wait_selector, extractor, query_key)
    "naver_blog": ("public", url_naver("blog"), "#main_pack", ex_naver_blog, "ko_en"),
    "naver_cafe": ("public", url_naver("cafe"), "#main_pack", ex_naver_cafe, "ko_en"),
    "youtube":    ("public", url_generic("https://www.youtube.com/results?search_query={q}&sp=CAI%3D"), "ytd-video-renderer", ex_youtube, "ko_en"),
    "reddit":     ("public", url_generic("https://www.reddit.com/search/?q={qq}&sort=new&t=month"), "a[href*='/comments/']", ex_reddit, "en"),
    "x":          ("login",  url_generic("https://x.com/search?q={qs}&f=live"), "article", ex_x, "ko_en"),
    "instagram":  ("login",  url_generic("https://www.instagram.com/{q}/"), "a[href*='/p/'], a[href*='/reel/']", ex_instagram, "ig"),
    "official":   ("public", lambda q, s, u: q, None, ex_official, "pages"),
    "tiktok":     ("public", url_generic("https://www.tiktok.com/search/video?q={q}"), "a[href*='/video/']", ex_tiktok, "ko_en"),
    "ameblo":     ("public", url_generic("https://search.ameba.jp/search/entry/{q}.html"), None, ex_hostre(r"ameblo\.jp/[^/]+/entry-"), "jp"),
    "note":       ("public", url_generic("https://note.com/search?q={q}&context=note&sort=new"), "a[href*='/n/n']", ex_hostre(r"note\.(com|jp)/[^/]+/n/|note\.jp/n/"), "jp"),
    "pantip":     ("public", url_generic("https://pantip.com/search?q={q}"), "a[href*='/topic/']", ex_hostre(r"pantip\.com/topic/\d+$"), "th"),
    "dcard":      ("public", url_generic("https://www.dcard.tw/search?query={q}&sort=latest"), None, ex_hostre(r"dcard\.tw/f/[^/]+/p/"), "tw"),
    "naver_news": ("public", url_naver("news"), "#main_pack", ex_naver_news, "ko"),
    "yahoo_rt":   ("public", url_generic("https://search.yahoo.co.jp/realtime/search?p={q}"), "a[href*='/status/']", ex_yahoo_rt, "ja"),
    "chiebukuro": ("public", url_generic("https://chiebukuro.yahoo.co.jp/search?p={q}&flg=3&sort=2"), "a[href*='question_detail']", ex_chiebukuro, "ja_q"),
    "ptt":        ("public", url_generic("https://www.ptt.cc/bbs/facelift/search?q={q}"), "div.r-ent", ex_ptt, "tw"),
}
WAIT_MS = {"pantip": 15000}                     # 결과가 늦게 그려지는 사이트는 선택자 대기 시간을 늘린다
STATE = {}                                      # logs/watch_state.json: 공식 페이지·사이트맵·Instagram 별로 이미 본 URL


# ───────────────────────── 검색어 구성 ─────────────────────────
def build_queries(cfg, key):
    """[(병원, 검색어)] — 병원별 검색어 뒤에 (일반) 검색어"""
    out = []
    groups = [(h, v) for h, v in cfg["hospitals"].items()] + [("(일반)", cfg["general"])]
    if key in ("ja", "ja_q", "tw", "th"):                              # 해외 커뮤니티는 병원명이 드물어 일반 검색어(신규 신호어)를 먼저
        groups = groups[-1:] + groups[:-1]
    for h, v in groups:
        ko, en, tags = v.get("ko", []), v.get("en", []), v.get("tags", [])
        ja = v.get("ja", [])
        if key == "ko_en":
            qs = ko + en
        elif key == "ko":                                      # 국내 채널(네이버): 국문 병원명만
            qs = ko
        elif key == "ja":                                      # 일본 채널: 공식 일본어 표기(확인된 것만). (일반)은 신규 신호어 조합
            qs = ja if h != "(일반)" else ["韓国整形 モニター募集", "韓国整形 相談会", "韓国美容 新登場"]
        elif key == "ja_q":                                    # 知恵袋: 질문은 넓은 검색어라야 최근 글이 잡힘
            qs = ja if h != "(일반)" else ["韓国整形", "韓国 美容外科", "韓国 整形 口コミ"]
        elif key == "en":
            qs = en
        elif key == "tags":
            qs = tags
        elif key == "pages":                                   # 공식 사이트 목록 페이지(병원, 주소)
            qs = cfg.get("official_pages", {}).get(h, []) if h != "(일반)" else []
        elif key == "ig":                                      # 병원 공식 계정(프로필 방문)
            qs = cfg.get("instagram", {}).get(h, [])
        elif key == "jp":
            qs = [f"{e} 韓国整形" for e in en] if h != "(일반)" else ["韓国 美容整形 口コミ"]
        elif key == "th":
            qs = [f"{e} เกาหลี ศัลยกรรม" for e in en] if h != "(일반)" else ["ศัลยกรรมเกาหลี รีวิว"]
        elif key == "tw":                                      # PTT facelift 게시판 안 검색: 영문 병원명, (일반)은 '韓國'
            qs = [e for e in en] if h != "(일반)" else ["韓國"]
        else:
            qs = []
        out += [(h, q) for q in qs]
    if key == "pages":                                         # 병원이 아닌 감시 대상(예: (에이전시) 상담회 목록)
        for h, qs in cfg.get("official_pages", {}).items():
            if not h.startswith("_") and h not in cfg["hospitals"]:
                out += [(h, q) for q in qs]
    return out


# ───────────────────────── 실행 ─────────────────────────
def run_channel(name, ctx_for, cfg, s, u, args, deadline, rec_all, manual, summary):
    kind, url_of, wait, extract, qkey = CHANNELS[name]
    lim = cfg["limits"]
    max_q = args.limit or lim.get("per_channel", {}).get(name) or (
        lim["login_searches_per_channel"] if name in LOGIN_CHANNELS else lim["official_pages_per_run"] if name == "official" else lim["public_searches_per_channel"])
    n_posts = 6 if name == "instagram" else (30 if name == "official" else lim["posts_per_search"])   # 프로필 격자 한 화면(고정 게시물 포함)
    queries = build_queries(cfg, qkey)[:max_q]
    st = {"status": "ok", "count": 0, "searches": 0, "note": ""}
    summary[name] = st
    stop_reason = None
    ctx = ctx_for(name)
    if ctx is None:                                # 로그인 필요한데 세션이 없음
        stop_reason = "login_required"
    page = ctx.new_page() if ctx is not None else None
    errors = 0
    seen_urls = {r["url"] for r in rec_all}
    watch = STATE
    new_urls = {}
    for hospital, q in queries:
        url = url_of(q, s, u)
        terms = None if name in ("instagram", "official") else terms_of(cfg, hospital)   # 공식 계정 게시물은 병원명이 없어도 대상
        if stop_reason or time.time() > deadline:
            manual.append({"channel": name, "hospital": hospital, "query": q, "url": url,
                           "reason": stop_reason or "timeout", "at": datetime.now().strftime("%Y-%m-%d %H:%M")})
            continue
        try:
            resp = goto(page, url, wait, WAIT_MS.get(name, 9000))
            check_block(page, resp, strict=name == "official")
            raws = extract(page, q, s, u, n_posts)
            check_block(page, None, raws, wall=name in WALL_CHANNELS, strict=name == "official")
            st["searches"] += 1
            errors = 0
            for raw in raws[:n_posts * 3]:
                if not raw.get("url") or raw["url"] in seen_urls:
                    continue
                if terms and not any(t in f"{raw.get('title', '')} {raw.get('block', '')} {raw.get('author', '')}".lower() for t in terms):
                    continue                                   # 병원 이름이 없는 결과는 제외
                d = date_of(raw)
                if d and not (s <= d <= u):
                    continue
                if name == "official":
                    prev = watch.get(q)                       # 이전 수집에서 본 URL 목록(없으면 이번이 기준선)
                    new_urls.setdefault(q, []).append(raw["url"])
                    if d is None:
                        if prev is None or raw["url"] in prev:
                            continue                          # 날짜도 없고 신규도 아니면 제외
                        raw["note"] = "이전 수집에 없던 신규 URL(게시일 미표시)"
                if d is None and name.startswith("naver"):
                    raw["note"] = "네이버 기간 필터 적용(게시일 미표시)"
                raw["date"] = d
                seen_urls.add(raw["url"])
                rec_all.append(mk(name, hospital, q, raw))
                st["count"] += 1
        except Blocked as b:
            if name == "official":                       # 사이트마다 따로 막힐 수 있으므로 다음 페이지는 계속 시도
                st["note"] = f"일부 페이지 {b.reason}: {q[:60]}"
                manual.append({"channel": name, "hospital": hospital, "query": q, "url": q, "reason": b.reason,
                               "at": datetime.now().strftime("%Y-%m-%d %H:%M")})
                pause()
                continue
            stop_reason = b.reason
            st["status"] = b.reason
            st["note"] = f"'{q}' 검색에서 {b.reason} 감지 — 이후 검색 중단"
            manual.append({"channel": name, "hospital": hospital, "query": q, "url": url, "reason": b.reason,
                           "at": datetime.now().strftime("%Y-%m-%d %H:%M")})
        except Exception as e:                     # noqa: BLE001
            errors += 1
            st["note"] = f"{type(e).__name__}: {str(e)[:120]}"
            try:
                RAW.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(RAW / f"{name}_error.png"))
            except Exception:                      # noqa: BLE001
                pass
            if errors >= 3:
                stop_reason = "error"
                st["status"] = "error"
        pause()
    if stop_reason == "login_required" and ctx is None:
        st["status"] = "login_required"
        st["note"] = "로그인 세션 없음 — python research/sns_login.py " + name
    if st["status"] == "ok" and time.time() > deadline:
        st["status"] = "timeout"
    if name == "official" and new_urls:                       # 다음 수집의 기준선(저장은 main 끝에서 한 번)
        for k, v in new_urls.items():
            STATE[k] = sorted(set(STATE.get(k, [])) | set(v))
    if page:
        page.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--limit", type=int, default=0, help="채널당 검색 횟수 상한(점검용)")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright
    cfg = json.loads(TARGETS.read_text(encoding="utf-8"))
    s, u = period()
    off = set(cfg.get("disabled_channels", []))                 # targets.json 에서 끈 채널(--only 로 직접 지정하면 실행)
    order = cfg.get("channel_order", list(CHANNELS))             # 중요한 채널부터: 시간 상한에 걸려도 먼저 끝나게
    pool = [n for n in order if n in CHANNELS] + [n for n in CHANNELS if n not in order]
    names = [n for n in pool if (n in args.only.split(",") if args.only else n not in off)]
    if WATCH.exists():
        STATE.update(json.loads(WATCH.read_text(encoding="utf-8")))
    deadline = time.time() + cfg["limits"]["total_minutes"] * 60
    rec_all, manual, summary = [], [], {}
    if not args.only or "sitemap" in args.only.split(","):          # 사이트맵: 새로 생긴 URL(첫 실행은 lastmod 기준) 수집
        try:
            recs, st = sitemap_watch.collect(cfg, s, u, STATE)
            rec_all += recs
            summary["sitemap"] = st
            print(f"  sitemap     {st['status']:15s} {st['count']:3d}건  {st['note']}")
        except Exception as e:                                      # noqa: BLE001
            summary["sitemap"] = {"status": "error", "count": 0, "searches": 0, "note": f"{type(e).__name__}: {str(e)[:120]}"}
    print(f"[수집] 기간 {s} ~ {u}, 채널 {len(names)}개")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        public = browser.new_context(user_agent=UA, locale="ko-KR", viewport={"width": 1280, "height": 900})
        persistent = {}

        def ctx_for(name):
            if name not in LOGIN_CHANNELS:
                return public
            if name in persistent:
                return persistent[name]
            prof = PROFILES / name
            if not prof.exists():
                return None
            persistent[name] = p.chromium.launch_persistent_context(
                str(prof), headless=not args.headed, user_agent=UA, locale="ko-KR", viewport={"width": 1280, "height": 900})
            return persistent[name]

        for name in names:
            try:
                run_channel(name, ctx_for, cfg, s, u, args, deadline, rec_all, manual, summary)
            except Exception as e:                 # noqa: BLE001
                summary[name] = {"status": "error", "count": 0, "searches": 0, "note": f"{type(e).__name__}: {str(e)[:120]}"}
            st = summary[name]
            print(f"  {name:11s} {st['status']:15s} {st['count']:3d}건  {st['note']}")
        for c in persistent.values():
            c.close()
        browser.close()

    WATCH.parent.mkdir(parents=True, exist_ok=True)
    WATCH.write_text(json.dumps(STATE, ensure_ascii=False), encoding="utf-8")   # 다음 수집의 '이미 본 URL' 기준선
    RAW.mkdir(parents=True, exist_ok=True)
    out = RAW / f"collect_{datetime.now():%Y%m%d_%H%M}.json"
    out.write_text(json.dumps({"at": datetime.now().strftime("%Y-%m-%d %H:%M"), "period": {"from": s.isoformat(), "to": u.isoformat()},
                               "channels": summary, "manual_check": manual, "records": rec_all},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    for old in RAW.glob("collect_*.json"):         # 원자료는 7일만 보관
        if time.time() - old.stat().st_mtime > 7 * 86400:
            old.unlink()
    print(f"[수집] 레코드 {len(rec_all)}건, 직접 확인 필요 {len(manual)}건 → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
