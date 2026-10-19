"""원자료에서 '새로운 것' 후보를 점수로 골라낸다 → logs/raw/triage_YYYYMMDD_HHMM.json (공개되지 않음)
광고주 관심사 두 가지에 맞춘 신호로 점수를 매긴다.
  - new_method: 새 마케팅·바이럴 방식 (AI·AEO, 가이드 허브, 시리즈, 인플루언서·콜라보, 모니터 모집, 플랫폼 키워드 …)
  - new_market: 새 해외시장·유입 경로 (국가·도시, 현지 상담회·설명회, 에이전시·제휴, 메신저 상담, 공항·호텔 …)
  python -I research/triage.py [collect_*.json]      # 인자가 없으면 가장 최근 수집 결과
"""
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "logs" / "raw"
TOP_N = 60

NEW = (r"신규|새로운|오픈|론칭|런칭|출시|도입|최초|단독|협약|MOU|업무협약|제휴|파트너십|\bnew\b|launch|introduc|"
       r"first[- ](ever|in korea|time)|for the first time|exclusive|partnership|grand open|opening soon|"
       r"新登場|新規|初めて|日本初|提携|オープン|開院|限定")
METHOD = (r"챗봇|chatbot|가이드|guide|허브|hub|라이브러리|library|시리즈|series|인플루언서|influencer|콜라보|collab|"
          r"챌린지|challenge|밈|meme|숏폼|릴스|reels?|쇼츠|shorts|모니터|monitor|モニター|体験談|브이로그|vlog|인터뷰|interview|"
          r"강남언니|カンナムオンニ|gangnam unni|리얼 ?리뷰|real review|before.?after|경품|giveaway|이벤트|event|キャンペーン|プレゼント|"
          r"아이돌|idol|アイドル|넷플릭스|netflix|연예인|celebrit")
MARKET = (r"일본|도쿄|東京|오사카|大阪|나고야|名古屋|후쿠오카|福岡|태국|(?<![ァ-ヶー])タイ(?![ァ-ヶー])|ไทย|베트남|vietnam|"
          r"인도네시아|indonesia|대만|台湾|台灣|중국|미국|USA|중동|두바이|dubai|사우디|몽골|카자흐|러시아|russia|싱가포르|singapore|"
          r"말레이|malaysia|필리핀|상담회|설명회|カウンセリング会|相談会|説明会|consultation (day|event)|에이전시|agency|代理店|"
          r"WhatsApp|Zalo|위챗|wechat|영상상담|video (call|consult)|オンライン相談|"
          r"공항|airport|空港|픽업|pick.?up|送迎|호텔|hotel|ホテル|명동|明洞|myeongdong|관광|tourism|medical travel|観光|비자|visa|VAT|부가세")
METHOD_CS = r"\bAI\b|\bAEO\b|\bGEO\b|\bKOL\b"             # 약어는 대소문자 구분(surgeon 안의 geo 같은 오탐 방지)
MARKET_CS = r"\bLINE\b|\bLA\b|\bUS\b"                   # 대소문자를 구분해야 오탐이 없는 신호(메신저 LINE, 지명 LA·US)
CH_WEIGHT = {"sitemap": 1.5, "official": 1.5, "instagram": 1.5, "naver_news": 1.5, "yahoo_rt": 1.0, "ameblo": 1.0, "note": 1.0,
             "youtube": 0.5, "reddit": 0.0, "chiebukuro": 0.0, "ptt": 0.0, "pantip": 0.0, "naver_blog": -1.0, "naver_cafe": -1.0}


def score(r):
    txt = f"{r.get('title', '')} {r.get('text', '')} {r.get('note', '')}"
    sig = {"new": sorted({m.group(0).lower() for m in re.finditer(NEW, txt, re.I)}),
           "method": sorted({m.group(0).lower() for m in re.finditer(METHOD, txt, re.I)}
                            | {m.group(0) for m in re.finditer(METHOD_CS, txt)}),
           "market": sorted({m.group(0).lower() for m in re.finditer(MARKET, txt, re.I)}
                            | {m.group(0) for m in re.finditer(MARKET_CS, txt)})}
    s = CH_WEIGHT.get(r.get("channel"), 0.0)
    s += min(len(sig["new"]), 3) * 1.5 + min(len(sig["method"]), 3) * 1.0 + min(len(sig["market"]), 3) * 1.0
    if "새로 생긴 URL" in r.get("note", "") or "신규 URL" in r.get("note", ""):
        s += 3                                         # 이전 수집에 없던 공식 페이지 = 가장 강한 신호
    if r.get("hospital") not in ("(일반)", None):
        s += 0.5
    kind = "new_market" if len(sig["market"]) > len(sig["method"]) else ("new_method" if sig["method"] else "")
    return round(s, 2), kind, sig


def main():
    # -I 실행에서는 PYTHONUTF8이 무시되므로 출력 인코딩을 고정한다
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    src =Path(sys.argv[1]) if len(sys.argv) > 1 else sorted(RAW.glob("collect_*.json"))[-1]
    d = json.loads(src.read_text(encoding="utf-8"))
    rows = []
    for i, r in enumerate(d.get("records", [])):
        s, kind, sig = score(r)
        rows.append({"i": i, "score": s, "guess": kind, "signals": sig, "channel": r.get("channel"), "hospital": r.get("hospital"),
                     "date": r.get("date"), "url": r.get("url"), "title": (r.get("title") or "")[:120], "note": r.get("note", "")})
    rows.sort(key=lambda x: x["score"], reverse=True)
    top = [x for x in rows if x["score"] >= 3][:TOP_N]
    out = RAW / src.name.replace("collect_", "triage_")
    out.write_text(json.dumps({"source": src.name, "at": datetime.now().strftime("%Y-%m-%d %H:%M"), "total": len(rows),
                               "candidates": top, "by_channel": Counter(x["channel"] for x in top),
                               "by_hospital": Counter(x["hospital"] for x in top)}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[선별] 원자료 {len(rows)}건 → 후보 {len(top)}건 → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
