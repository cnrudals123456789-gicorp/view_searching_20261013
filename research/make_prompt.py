"""조사 기간 머리말 + research/prompt.md → logs/research_prompt.md (research_and_publish.bat 이 claude 에 넘김)
기간은 logs/research_params.json({"from","to"})에서 읽는다. 없거나 손상됐으면 최근 14일.
  python -I research/make_prompt.py
"""
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARAMS = ROOT / "logs" / "research_params.json"
OUT = ROOT / "logs" / "research_prompt.md"
DEFAULT_DAYS = 14
D = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def period():
    today = date.today()
    try:
        p = json.loads(PARAMS.read_text(encoding="utf-8"))
        if D.match(p["from"]) and D.match(p["to"]):
            s, e = (datetime.strptime(p[k], "%Y-%m-%d").date() for k in ("from", "to"))
            if s <= e <= today and (e - s).days < 92:
                return s, e
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return today - timedelta(days=DEFAULT_DAYS - 1), today


def raw_section():
    """가장 최근 수집기 결과(logs/raw/collect_*.json) 안내. 없으면 빈 문자열"""
    files = sorted((ROOT / "logs" / "raw").glob("collect_*.json"))
    if not files:
        return ""
    try:
        c = json.loads(files[-1].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    rows = chr(10).join(f"  - {n}: {v.get('status')} · {v.get('count')}건" + (f" ({v['note']})" if v.get("note") else "")
                     for n, v in c.get("channels", {}).items())
    return f"""## 수집기 원자료 (Playwright가 이미 수집함 — 가장 먼저 읽는다)
- 파일: `{files[-1].relative_to(ROOT).as_posix()}` (수집 {c.get('at')}, 기간 {c.get('period', {}).get('from')} ~ {c.get('period', {}).get('to')})
- 채널별 결과:
{rows}
- `records` 항목의 `url`은 직접 열어 수집한 실제 주소다. **모든 `records`를 읽고** 병원 움직임은 `items`로, 소비자 후기는 `reviews`로 분류한다. 병원과 무관하거나 광고성 잡글은 버린다.
- `date`가 null인 네이버 결과는 기간 필터가 적용된 결과이므로 기간 안으로 본다. 실제 게시일을 알 수 있으면 `date`에 쓴다.
- `coverage`는 위 채널별 결과를 그대로 반영한다: `ok`는 `"날짜 확인·N건"`, `login_required`/`captcha`/`blocked`는 `"확인불가(사유)"`.
- `manual_check`(CAPTCHA·로그인으로 멈춘 검색)는 **네가 처리하지 않는다**. 검증 단계에서 사람이 직접 확인하도록 웹에 표시된다. 해당 채널은 WebSearch로 우회해서 메우려 하지 말고, 이미 직접 확인한 URL만 추가한다.
- 원문 전체나 작성자 계정명은 공개 파일에 옮기지 않는다. 요약만 쓴다.

---

"""


def triage_section():
    """가장 최근 후보 선별 결과(logs/raw/triage_*.json) — '새로운 것' 후보를 먼저 읽게 한다"""
    files = sorted((ROOT / "logs" / "raw").glob("triage_*.json"))
    if not files:
        return ""
    try:
        t = json.loads(files[-1].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    lines = chr(10).join(f"  {i + 1}. [{c['score']}] {c['hospital']} · {c['channel']} · {c['title'][:70]} — {c['url']}"
                         for i, c in enumerate(t.get("candidates", [])[:30]))
    return f"""## '새로운 것' 후보 (먼저 정독한다 — 광고주 관심사 기준으로 점수화됨)
광고주가 궁금해하는 것은 **새 마케팅·바이럴 방식(new_method)** 과 **새 해외시장·유입 경로(new_market)** 다.
- 후보 파일: `{files[-1].relative_to(ROOT).as_posix()}` (원자료 {t.get('total')}건 중 {len(t.get('candidates', []))}건). 아래 후보부터 원문을 열어 확인하고, 나머지 원자료는 훑어본다.
{lines}
- 판정 순서: ① `research/known_tactics.json`(오래 보관되는 '알려진 전술')과 비교 → 같은 병원에 같은 전술이 있으면 `novelty: continuation` → 다른 병원에만 있으면 `new_*` + `hl: hospital` → 어디에도 없고 검색으로도 전례가 없으면 `new_*` + `hl: industry`. 확신이 없으면 한 단계 낮춘다.
- `new_*`로 판정한 항목은 `novelty_reason`에 "무엇이 처음인지 + 비교 근거"를 한 줄로 쓰고, 끝나면 `research/known_tactics.json`에 그 전술을 한 줄 추가한다.

---

"""


def main():
    s, e = period()
    PARAMS.unlink(missing_ok=True)      # 한 번 쓰고 폐기 (다음 직접 실행이 옛 기간을 쓰지 않도록)
    n = (e - s).days + 1
    head = f"""## 이번 조사 기간 (최우선 · 아래 본문의 "최근 7일/30일" 규칙보다 우선한다)
- **조사 기간: {s} ~ {e} ({n}일)**. 오늘은 {date.today()}이다.
- 이 기간에 **게시되었거나 처음 확인된** 병원 움직임·바이럴·후기만 수집한다. 기간보다 오래된 게시물은 넣지 않는다. 다만 기간 중에 새로 알려진 것이라면 게시일을 정확히 적고 포함해도 된다.
- 항목의 `date`(게시일)는 반드시 원문 날짜로 쓴다. `found`/`last_seen`은 오늘 날짜다.
- 월별 저장은 **조사 실행일이 속한 달**(`{date.today():%Y-%m}`)에 한다.
- `runs`에 이번 조사의 기간을 `"period": {{"from": "{s}", "to": "{e}"}}`로 함께 기록한다.
- 기간이 길수록 채널별로 빠짐없이 훑는다. 같은 내용은 중복 규칙대로 합친다.

---

"""
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(head + triage_section() + raw_section() + (Path(__file__).with_name("prompt.md")).read_text(encoding="utf-8"),
                   encoding="utf-8")
    print(f"[기간] {s} ~ {e} ({n}일)")


if __name__ == "__main__":
    main()
