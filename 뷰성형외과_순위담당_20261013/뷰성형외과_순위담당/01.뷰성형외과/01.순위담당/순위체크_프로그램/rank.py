"""
로그인된 프로필로 네이버 검색 → 파워링크·파워컨텐츠 노출 순위를 추출해 CSV로 저장합니다.

사용 예:
  python rank.py 다이어트 "강남 피부과"                 # 키워드 직접 입력
  python rank.py -f keywords.txt                       # 파일에서 읽기 (한 줄에 하나)
  python rank.py -f keywords.txt -t themareum.com      # 특정 도메인 순위만 요약 출력
  python rank.py -f keywords.txt -d mobile             # 모바일만 (pc | mobile | both)
  python rank.py -f keywords.txt --headless            # 창 없이 실행
"""
import argparse
import asyncio
import csv
import random
import sys
from datetime import datetime
from urllib.parse import quote

from playwright.async_api import async_playwright
from common import launch, verify_logged_in, load_login_info, BASE_DIR

SEARCH_URL = {
    "pc": "https://search.naver.com/search.naver?where=nexearch&sm=top_hty&fbm=0&ie=utf8&query={q}",
    "mobile": "https://m.search.naver.com/search.naver?query={q}",
}

# 파워링크 li 하나에서 정보를 뽑는 JS (PC/모바일 공통 처리)
EXTRACT_JS = r"""
() => {
  const body = document.querySelector('#power_link_body');
  if (!body) return [];
  // PC: div#power_link_body > ul.lst_type > li.lst / 모바일: ul#power_link_body > li.bx
  const items = body.querySelectorAll(':scope > li, :scope > ul > li');
  const out = [];
  items.forEach((li, idx) => {
    const t = (sel) => Array.from(li.querySelectorAll(sel)).map(e => e.textContent.trim()).filter(Boolean);
    const a = li.querySelector('a[onclick]');
    const onclick = a ? (a.getAttribute('onclick') || '') : '';
    const adId = (onclick.match(/i=(nad-[\w-]+)/) || [])[1] || '';
    const rankAttr = (onclick.match(/[&"]r=(\d+)/) || [])[1] || '';
    const landing = (onclick.match(/\(["']([^"']+)["']\)\+/) || [])[1] || '';
    // 의료광고 등은 화면에 URL 표기가 없으므로 랜딩 URL의 도메인으로 대체
    let host = '';
    try { host = new URL(landing).hostname.replace(/^www\./, ''); } catch (e) {}
    const url = t('.lnk_url, .url')[0] || host;
    out.push({
      rank: rankAttr ? parseInt(rankAttr, 10) : idx + 1,
      site: (t('.site')[0] || url),
      url: url,
      title: t('.lnk_tit, .tit_area .tit').join(' '),
      desc: (t('.link_desc, .desc_area')[0] || ''),
      ad_id: adId,
      landing: landing,
    });
  });
  return out;
}
"""


# 파워링크 '더보기' 페이지 (1페이지 미노출 시 전체 광고 목록에서 순위 탐색)
MORE_URL = {
    "pc": "https://ad.search.naver.com/search.naver?where=ad&query={q}",
    "mobile": "https://m.ad.search.naver.com/search.naver?where=m_expd&query={q}",
}
MORE_MAX_PAGES = 30          # PC 25개/페이지 → 최대 750개
MORE_MAX_CLICKS = 50         # 모바일 15개/클릭 → 최대 765개

EXTRACT_MORE_JS = r"""
() => {
  // PC: li.lst[data-index] / 모바일: li.list_item
  const items = document.querySelectorAll('li.lst[data-index], li.list_item');
  const out = [];
  items.forEach((li, idx) => {
    const t = (sel) => Array.from(li.querySelectorAll(sel)).map(e => e.textContent.trim()).filter(Boolean);
    const html = li.innerHTML;
    const adId = (html.match(/nad-a001-[\w-]+/) || [])[0] || '';
    const landing = (html.match(/(?:urlencode|encodeURIComponent)\(&quot;([^&]+)&quot;\)/) || html.match(/(?:urlencode|encodeURIComponent)\(["']([^"']+)["']\)/) || [])[1] || '';
    let host = '';
    try { host = new URL(landing).hostname.replace(/^www\./, ''); } catch (e) {}
    const url = t('a.url, .url_link')[0] || host;
    out.push({
      rank: idx + 1,
      site: url,
      url: url,
      title: t('.lnk_tit, .tit_area .tit').join(' '),
      desc: (t('.link_desc, .desc')[0] || ''),
      ad_id: adId,
      landing: landing,
    });
  });
  return out;
}
"""


async def fetch_ads(page, device: str, keyword: str):
    await page.goto(SEARCH_URL[device].format(q=quote(keyword)), wait_until="domcontentloaded")
    try:
        await page.wait_for_selector("#power_link_body", timeout=6000)
    except Exception:
        pass
    await page.wait_for_timeout(1200)
    ads = await page.evaluate(EXTRACT_JS)
    # 더보기 링크(referenceId 포함)를 같이 가져온다. 없으면 기본 URL 사용
    more = await page.evaluate(
        "() => (Array.from(document.querySelectorAll('a.group_more, a')).find(a => /ad\\.search\\.naver\\.com/.test(a.href)) || {}).href || ''")
    return ads, (more or MORE_URL[device].format(q=quote(keyword)))


def _match(ad, target):
    return bool(target) and (target in ad["url"].lower() or target in ad["landing"].lower())


async def search_more(page, device: str, more_url: str, target: str):
    """더보기 목록을 끝까지 훑어 target의 순위를 찾는다. (ads_seen, hit_rank, total_listed)"""
    seen = []
    if device == "pc":
        for n in range(1, MORE_MAX_PAGES + 1):
            url = more_url + ("&" if "?" in more_url else "?") + f"pagingIndex={n}"
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(800)
            ads = await page.evaluate(EXTRACT_MORE_JS)
            if not ads:
                break
            for ad in ads:
                ad["rank"] = len(seen) + 1
                seen.append(ad)
                if _match(ad, target):
                    return seen, ad["rank"], None
            has_next = await page.evaluate("() => !!document.querySelector('a.next')")
            if not has_next or len(ads) < 25:
                break
        return seen, None, len(seen)
    else:
        await page.goto(more_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(1000)
        total = await page.evaluate("() => parseInt((document.querySelector('#_total_count') || {}).textContent || '0', 10)")
        for _ in range(MORE_MAX_CLICKS + 1):
            ads = await page.evaluate(EXTRACT_MORE_JS)
            for ad in ads[len(seen):]:
                ad["rank"] = len(seen) + 1
                seen.append(ad)
                if _match(ad, target):
                    return seen, ad["rank"], total
            btn = await page.query_selector("#_get_more")
            if not btn or not await btn.is_visible() or (total and len(seen) >= total):
                break
            before = len(ads)
            await btn.click()
            try:
                await page.wait_for_function(f"() => document.querySelectorAll('li.list_item').length > {before}", timeout=6000)
            except Exception:
                break
            await page.wait_for_timeout(500)
        return seen, None, total or len(seen)


# ---------- 파워컨텐츠 ('키워드' 관련 브랜드 콘텐츠 블록) ----------
# 파워컨텐츠 블록은 두 가지 형태가 있다:
#  ① "'키워드' 관련 브랜드 콘텐츠" (data-block-id에 powercontents, 항목에 data-nlog-params로 ad_id/순위 있음)
#  ② "건강·의학 관련 브랜드 콘텐츠" 같은 카테고리형 (review 템플릿, ad_id는 페이지 내부 데이터에만 있음)
# → 제목(h2)에 '브랜드 콘텐츠'가 들어간 블록을 루트로 잡고, 항목은 ._fe_view_power_content 로 공통 처리
PC_ROOT_JS = r"""
() => {
  let root = document.querySelector('[data-block-id*="powercontents"]');
  if (root) return root;
  const h2 = Array.from(document.querySelectorAll('h2')).find(h => /브랜드 콘텐츠/.test(h.textContent));
  if (!h2) return null;
  root = h2.closest('._fe_view_root, [data-fender-root], section, .sc_new');
  return root && root.querySelector('._fe_view_power_content') ? root : null;
}
"""

EXTRACT_PC_JS = r"""
(onlyOutsideRoot) => {
  const findRoot = %s;
  const root = findRoot();
  if (!root) return null;
  const clean = (s) => (s || '').replace(/새 창 열림/g, '').trim();
  // ② 형태용: 페이지 데이터에서 순위→광고ID 매핑 ("i":"nad-a001-03-…","r":N)
  const idByRank = {};
  const html = document.documentElement.innerHTML;
  const re = /"i":"(nad-a001-03-\d+)","r":(\d+)/g; let m;
  while ((m = re.exec(html)) !== null) { if (!idByRank[m[2]]) idByRank[m[2]] = m[1]; }
  const items = Array.from(document.querySelectorAll('._fe_view_power_content'))
    .filter(it => onlyOutsideRoot ? !root.contains(it) : root.contains(it));
  return items.map((it, idx) => {
    const nlog = it.querySelector('[data-nlog-params]');
    let p = {}; try { p = JSON.parse(nlog.getAttribute('data-nlog-params')); } catch (e) {}
    const rank = parseInt(p.cr_rank_legacy || (idx + 1), 10);
    const src = clean((it.querySelector('.sds-comps-profile-info-title-text') || {}).textContent);
    const title = clean((it.querySelector('[class*="headline"]') || {}).textContent);
    const desc = clean((it.querySelector('[class*="ellipsis4"], [class*="ellipsis3"], [class*="ellipsis2"]') || {}).textContent);
    return { rank: rank, site: src, url: '', title: title, desc: desc,
             ad_id: p.ad_id || (onlyOutsideRoot ? '' : (idByRank[String(rank)] || '')), landing: '' };
  });
}
""" % PC_ROOT_JS

LAYER_ITEMS_JS = r"""
() => { const findRoot = %s; const r = findRoot();
  return Array.from(document.querySelectorAll('._fe_view_power_content')).some(it => r && !r.contains(it)); }
""" % PC_ROOT_JS

LAYER_NEXT_JS = r"""
() => { const findRoot = %s; const r = findRoot();
  const layerItem = Array.from(document.querySelectorAll('._fe_view_power_content')).find(it => r && !r.contains(it));
  if (!layerItem) return false;
  let box = layerItem; for (let i = 0; i < 12 && box.parentElement; i++) box = box.parentElement;
  const btn = Array.from(box.querySelectorAll('a, button')).find(e => /^다음/.test(e.textContent.trim()) && !e.disabled && e.getBoundingClientRect().width > 0 && !/disabled|off/.test(e.className));
  if (!btn) return false; btn.click(); return true; }
""" % PC_ROOT_JS

def _match_pc(ad, name):
    """파워컨텐츠는 도메인이 없으므로 브랜드명/제목/설명 텍스트로 매칭 (공백 무시)"""
    if not name:
        return False
    n = name.replace(" ", "").lower()
    hay = (ad["site"] + ad["title"] + ad["desc"]).replace(" ", "").lower()
    return n in hay


async def fetch_powercontents(page):
    """현재 검색 결과 페이지의 파워컨텐츠 첫 화면 목록. 블록이 없으면 None"""
    return await page.evaluate(EXTRACT_PC_JS, False)


async def expand_powercontents(page):
    """'브랜드 콘텐츠 더보기' 레이어를 열어 전체 목록을 가져온다. 더보기가 없으면 첫 화면 목록 반환"""
    root = await page.evaluate_handle(PC_ROOT_JS)
    root = root.as_element()
    if not root:
        return []
    more = await root.query_selector('a:has-text("더보기")')
    if not more:
        return await page.evaluate(EXTRACT_PC_JS, False) or []
    await more.scroll_into_view_if_needed()
    await more.click()
    try:
        await page.wait_for_function(LAYER_ITEMS_JS, timeout=6000)
    except Exception:
        return await page.evaluate(EXTRACT_PC_JS, False) or []
    await page.wait_for_timeout(800)
    seen = await page.evaluate(EXTRACT_PC_JS, True) or []
    # 레이어 안에 '다음' 페이지가 있으면 계속 넘긴다 (10개 단위)
    for _ in range(20):
        nxt = await page.evaluate(LAYER_NEXT_JS)
        if not nxt:
            break
        await page.wait_for_timeout(1200)
        more_items = await page.evaluate(EXTRACT_PC_JS, True) or []
        known = {(a["site"], a["title"]) for a in seen}
        new = [a for a in more_items if (a["site"], a["title"]) not in known]
        if not new:
            break
        seen.extend(new)
    for i, a in enumerate(seen, 1):
        a["rank"] = i
    return seen


class NotLoggedIn(RuntimeError):
    pass


def _row(ts, device, kw, ad_type, source, rank, total, ad=None, hit=False):
    ad = ad or {}
    return dict(timestamp=ts, device=device, keyword=kw, ad_type=ad_type, source=source, rank=rank, total=total,
                site=ad.get("site", ""), url=ad.get("url", ""), title=ad.get("title", ""), desc=ad.get("desc", ""),
                ad_id=ad.get("ad_id", ""), landing=ad.get("landing", ""), target_hit="Y" if hit else "")


async def run(keywords, devices, target, headless, delay, out_path, deep=True, log=print,
              types=("powerlink", "powercontents"), pc_target="", pc_keywords=None):
    """순위 체크 실행. log(msg)로 진행 상황을 보고하고 저장한 rows를 반환한다.
    keywords: 파워링크 키워드 / pc_keywords: 파워컨텐츠 키워드 (None이면 keywords와 동일)
    target: 파워링크 매칭용 도메인 / pc_target: 파워컨텐츠 매칭용 브랜드명(비우면 target 사용)"""
    rows = []
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pc_target = (pc_target or target or "").strip()
    pl_set = set(keywords) if "powerlink" in types else set()
    pc_set = set(keywords if pc_keywords is None else pc_keywords) if "powercontents" in types else set()
    # 두 목록의 합집합을 순서대로 (같은 키워드는 페이지를 한 번만 연다)
    all_keywords = list(dict.fromkeys(list(keywords) + list(pc_keywords or [])))
    all_keywords = [k for k in all_keywords if k in pl_set or k in pc_set]
    async with async_playwright() as p:
        for device in devices:
            ctx = await launch(p, device, headless)
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            if not await verify_logged_in(ctx, page):
                await ctx.close()
                raise NotLoggedIn("네이버 로그인 세션이 없거나 만료되었고 자동 로그인도 실패했습니다. "
                                  "credentials.json(아이디/비밀번호)을 확인하거나 login.py로 직접 로그인하세요.")
            if device == devices[0]:
                log(f"로그인 계정: {load_login_info().get('id') or '(아이디 확인 불가)'}")

            for i, kw in enumerate(all_keywords):
                do_pl, do_pc = kw in pl_set, kw in pc_set
                ads, more_url = await fetch_ads(page, device, kw)
                # 같은 페이지에서 파워컨텐츠도 먼저 읽어둔다 (더보기 탐색으로 페이지를 떠나기 전에)
                pcs = await fetch_powercontents(page) if do_pc else None
                pc_hit = ""
                if do_pc:
                    if pcs is None:
                        rows.append(_row(ts, device, kw, "powercontents", "1page", "", -1))
                        log(f"[{device}] {kw} 파워컨텐츠: 노출 영역 없음")
                    else:
                        for ad in pcs:
                            m = _match_pc(ad, pc_target)
                            if m and not pc_hit:
                                pc_hit = ad["rank"]
                            rows.append(_row(ts, device, kw, "powercontents", "1page", ad["rank"], len(pcs), ad, m))
                        if pc_target:
                            log(f"[{device}] {kw} 파워컨텐츠: 첫 화면 {len(pcs)}개 / '{pc_target}' 순위 = {pc_hit if pc_hit else '미노출'}")
                        else:
                            log(f"[{device}] {kw} 파워컨텐츠: {len(pcs)}개 → " + ", ".join(f"{a['rank']}.{a['site']}" for a in pcs))
                        if pc_target and not pc_hit and deep:
                            allpc = await expand_powercontents(page)
                            found = next((a for a in allpc if _match_pc(a, pc_target)), None)
                            if found:
                                rows.append(_row(ts, device, kw, "powercontents", "more", found["rank"], len(allpc), found, True))
                                log(f"        └ 더보기 목록: {found['rank']}위 (전체 {len(allpc)}개)")
                            else:
                                rows.append(_row(ts, device, kw, "powercontents", "more", "", len(allpc)))
                                log(f"        └ 더보기 목록 {len(allpc)}개 전부 확인: 미노출")

                if do_pl:
                    hit = ""
                    if not ads:
                        rows.append(_row(ts, device, kw, "powerlink", "1page", "", 0))
                        log(f"[{device}] {kw} 파워링크: 1페이지 광고 없음")
                    else:
                        for ad in ads:
                            m = _match(ad, target)
                            if m and not hit:
                                hit = ad["rank"]
                            rows.append(_row(ts, device, kw, "powerlink", "1page", ad["rank"], len(ads), ad, m))
                        if target:
                            log(f"[{device}] {kw} 파워링크: 1페이지 {len(ads)}개 / '{target}' 순위 = {hit if hit else '미노출'}")
                        else:
                            log(f"[{device}] {kw} 파워링크: {len(ads)}개 → " + ", ".join(f"{a['rank']}.{a['site'] or a['url']}" for a in ads))

                    # 1페이지에 없으면 '더보기' 전체 목록에서 탐색
                    if target and not hit and deep:
                        seen, more_rank, total_more = await search_more(page, device, more_url, target)
                        if more_rank:
                            rows.append(_row(ts, device, kw, "powerlink", "more", more_rank, total_more or "", seen[more_rank - 1], True))
                            log(f"        └ 더보기 목록: {more_rank}위" + (f" (전체 {total_more}개)" if total_more else ""))
                        else:
                            rows.append(_row(ts, device, kw, "powerlink", "more", "", len(seen)))
                            log(f"        └ 더보기 목록 {len(seen)}개 전부 확인: 미노출 (광고 없음)")

                if i < len(all_keywords) - 1:
                    await asyncio.sleep(random.uniform(delay, delay * 2))
            await ctx.close()

    fields = ["timestamp", "device", "keyword", "ad_type", "source", "rank", "total", "site", "url", "title", "desc",
              "ad_id", "landing", "target_hit"]
    # 기존 파일의 컬럼 구조가 다르면(버전 업) 옛 파일을 옆으로 옮기고 새로 만든다
    if out_path.exists():
        with open(out_path, encoding="utf-8-sig", newline="") as f:
            old_header = next(csv.reader(f), [])
        if old_header != fields:
            backup = out_path.with_name(out_path.stem + "_old" + out_path.suffix)
            n = 1
            while backup.exists():
                n += 1
                backup = out_path.with_name(f"{out_path.stem}_old{n}{out_path.suffix}")
            out_path.rename(backup)
            log(f"컬럼 구조가 바뀌어 기존 파일을 {backup.name} 으로 옮겼습니다.")
    new_file = not out_path.exists()
    with open(out_path, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new_file:
            w.writeheader()
        w.writerows(rows)
    log(f"저장: {out_path}  ({len(rows)}행)")
    # 요약 엑셀(순위요약_YYYY-MM.xlsx)에 세로로 누적. 실패해도 CSV는 이미 저장됐으므로 경고만.
    if target or pc_target:
        try:
            from summary import append_summary
            append_summary(rows, ts, out_path.parent, log=log)
        except Exception as e:
            log(f"[!] 엑셀 요약 저장 실패: {type(e).__name__}: {e}")
        # 붙여넣기용 텍스트(붙여넣기_최신.txt)도 갱신. 파워컨텐츠는 settings.json 의 pc_keywords 순서.
        try:
            from paste import write_paste
            write_paste(rows, ts, out_path.parent, log=log)
        except Exception as e:
            log(f"[!] 붙여넣기 파일 저장 실패: {type(e).__name__}: {e}")
    return rows

def main():
    ap = argparse.ArgumentParser(description="네이버 파워링크 순위 체크 (로그인 세션 기반)")
    ap.add_argument("keywords", nargs="*", help="검색 키워드")
    ap.add_argument("-f", "--file", help="키워드 파일 (한 줄에 하나)")
    ap.add_argument("-t", "--target", default="", help="순위를 확인할 도메인 (예: example.com)")
    ap.add_argument("-d", "--device", choices=["pc", "mobile", "both"], default="both")
    ap.add_argument("-o", "--out", help="결과 CSV 경로 (기본: results_YYYYMMDD.csv)")
    ap.add_argument("--headless", action="store_true", help="브라우저 창 없이 실행")
    ap.add_argument("--delay", type=float, default=3.0, help="키워드 간 최소 대기 초 (기본 3)")
    ap.add_argument("--no-deep", action="store_true", help="1페이지 미노출 시 '더보기' 목록 탐색을 끄기")
    ap.add_argument("--types", default="powerlink,powercontents", help="수집 광고 유형 (powerlink,powercontents)")
    ap.add_argument("--pc-target", default="", help="파워컨텐츠 매칭용 브랜드명 (예: 뷰성형외과). 비우면 -t 값 사용")
    ap.add_argument("--pc-file", help="파워컨텐츠 전용 키워드 파일 (지정하면 파워링크는 -f/키워드, 파워컨텐츠는 이 파일)")
    a = ap.parse_args()

    keywords = list(a.keywords)
    if a.file:
        with open(a.file, encoding="utf-8-sig") as f:   # 메모장 저장 시 붙는 BOM 무시
            keywords += [l.strip() for l in f if l.strip() and not l.startswith("#")]
    pc_keywords = None
    if a.pc_file:
        with open(a.pc_file, encoding="utf-8-sig") as f:
            pc_keywords = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    if not keywords and not pc_keywords:
        ap.error("키워드를 입력하거나 -f 파일을 지정하세요.")

    devices = ["pc", "mobile"] if a.device == "both" else [a.device]
    out_path = BASE_DIR / (a.out or f"results_{datetime.now():%Y%m%d}.csv")
    try:
        asyncio.run(run(keywords, devices, a.target.lower(), a.headless, a.delay, out_path, deep=not a.no_deep,
                        types=tuple(t.strip() for t in a.types.split(",") if t.strip()), pc_target=a.pc_target,
                        pc_keywords=pc_keywords))
    except NotLoggedIn as e:
        print("[!]", e, " →  python login.py")
        sys.exit(1)


if __name__ == "__main__":
    main()
