# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# 뷰성형외과 순위 모니터링 (이 PC 운영 + GitHub Pages 공유)

네이버 파워링크(도메인 `viewclinic.com`)·파워컨텐츠(브랜드 `뷰성형외과의원`) PC/MO 순위를 이 PC에서 조회하고, 결과를 GitHub Pages 정적 페이지로 공유한다.
네이버 로그인 세션이 필요해 **조회는 이 PC에서만** 가능하다(GitHub Actions 등에서 실행 불가).

## 데이터 흐름 (여러 파일에 걸친 구조)

```
스케줄러(10:10·16:10) 또는 serve.py 의 [지금 조회하기]
  → run_and_publish.bat            # 'wait_net.py'를 포함한 패키지 bat(자동순위체크.bat)을 찾아 실행(재시도 포함)
      → 순위체크_프로그램/ (rank.py, run.py, settings.json) → results_YYYYMMDD.csv
  → publish.bat                    # build_data.py → docs/data.json → git add/commit/push (logs\publish.log)
  → GitHub Pages (docs/)           # 1–2분 뒤 공개 링크 반영
```

- `build_data.py`: `results_YYYYMMDD.csv`(정규 파일명만, `_구버전`·`_old`·recheck 제외)를 모아 `docs/data.json` 생성. 셀 = `[순위|"미노출"|"영역없음", "1page"|"more"|"none", 비고]`. summary.py의 요약 규칙과 동일하게 유지할 것.
- `docs/index.html`: 단일 파일 대시보드(빌드 없음). `D`=data.json. 왼쪽 회차 표·추이, 오른쪽 `#report` 카드는 엑셀과 같은 `dayModel(date)`/`sheetCells(date)`를 공유한다(화면 = 엑셀). 엑셀은 ExcelJS(cdnjs)로 브라우저에서 생성, 오전/오후는 시각 12시 기준·반일 내 마지막 회차 우선. `#cap` 해시 = 캡처용 보기, 조회 버튼은 127.0.0.1/localhost에서만 노출.
- `serve.py`: 127.0.0.1:8770 로컬 서버(`POST /api/check`, `GET /api/status`, 같은 Origin만 허용, `logs/run.lock`으로 중복 실행 방지). `run_check_page.bat`/바탕화면 바로가기로 실행.
- 패키지(`뷰성형외과_순위담당_20261013/…/순위체크_프로그램`)는 원 운영자 전달본이므로 가급적 수정하지 않는다.

## 자주 쓰는 명령 (PowerShell, 저장소 루트)

```powershell
$env:PYTHONUTF8=1
python serve.py                                   # 로컬 조회 화면 (http://127.0.0.1:8770)
.\run_and_publish.bat dryrun                      # 실제 검색 없이 흐름만 점검
.\run_and_publish.bat                             # 조회 + 게시 (스케줄러와 동일)
.\publish.bat                                     # 게시만 (data.json 재생성 → push)
python -I build_data.py "<순위체크_프로그램 폴더>"   # docs/data.json 만 재생성
python login.py --set 아이디 비밀번호              # (패키지 폴더) 네이버 계정 저장 — 채팅·파일에 기록 금지
powershell -ExecutionPolicy Bypass -File .\작업스케줄러_등록.ps1   # 10:10·16:10 작업 등록
```

테스트 스위트·린터는 없다. 변경 후 `docs/index.html`은 브라우저(또는 헤드리스 Edge)로 열어 확인하고, 게시 후에는 공개 URL이 200인지 확인한다.

## 주의사항

- `.bat`은 **ASCII만** 사용(UTF-8 한글이 cmd 파싱을 깨뜨림). `%PKG%` 뒤에 따옴표를 붙일 땐 `"%PKG%."` (끝 `\`가 따옴표를 이스케이프함).
- `.ps1`은 **UTF-8 BOM** 필요(PowerShell 5.1이 BOM 없으면 한글을 깨뜨려 등록 실패).
- 공개 저장소: **원자료 CSV·엑셀·계정/세션·logs는 커밋 금지** (`.gitignore`). 웹에는 `docs/data.json`만 공개된다. 계정은 `%LOCALAPPDATA%\naver_powerlink\credentials.json`에만 둔다.
- 공개 페이지는 보기 전용이다(누구나 조회를 실행하는 기능은 보안상 만들지 않기로 결정).
- 커밋은 `git user.name/email`이 저장소 로컬로 설정되어 있어야 하며, 자동 게시 커밋 메시지는 `rank update …`.
- 조회 결과가 15개 미만인 회차는 `build_data.py`가 제외한다(불완전 회차 방지).

## 경쟁사 동향·만족도 (docs/competitor.json)
- 경쟁 병원의 프로모션·바이럴·SNS 동향을 월별로 누적한다. 대시보드 `[경쟁사 동향]`(`#comp`)과 `[만족도]`(`#sat`) 탭에 표시된다. 소비자의 "좋다/나쁘다" 후기는 동향이 아니라 만족도 탭에서만 다룬다.
- 기준 문서는 `research/지침서.md`, 조사 지시문은 `research/prompt.md`다. 검증·백업·중복 점검은 `python -I research/validate.py --backup|--check|--dupes`로 한다.
- 항목에는 `found`(처음 발견한 조사일)와 `last_seen`(마지막 확인일)을 기록한다. 같은 URL은 모든 달을 통틀어 한 건만 두고, 다시 발견되면 `last_seen`만 갱신한다. 월별 `runs`에 조사 이력(신규·갱신·중복 제외)이 남는다.
- 색 강조(`hl`): `industry`는 기존 업체에 전례 없는 방식, `hospital`은 그 병원의 첫 시도다.
- `.\research_and_publish.bat`: `claude -p`로 웹검색 조사를 하고 검증 후 push한다. 로그는 `logs\research.log`.
- 검증(`validate.py --check`)은 **문제 항목만 격리하고 나머지는 살린다**(URL 없음·필드 누락·값 오류·URL/id 중복). 격리된 항목은 `logs/competitor_rejected.json`에 사유와 함께 남고, 백업에 있던 기존 항목이 망가진 경우엔 백업 버전으로 되돌린다. 파일 전체가 깨졌을 때만 백업으로 통째로 복구한다. 모든 항목에 조사 원문의 직접 URL이 필수다.
- **수동 실행만 한다**: serve.py 화면의 `[경쟁사 조사하기]` 버튼(`POST /api/research`) 또는 위 bat 직접 실행. 스케줄러(`run_and_publish.bat`)에는 연결하지 않는다(결정). 순위 조회와 `logs/run.lock`을 공유해 동시에 하나만 실행된다.
- **수집기(Playwright)**: `research/collect.py`가 조사 전에 채널별 원자료를 `logs/raw/collect_*.json`(공개 안 됨, 7일 보관)에 모은다. 채널은 네이버 블로그·카페, YouTube, Reddit, Instagram, TikTok, Ameblo, Note, Pantip, Dcard이고, 검색어는 `research/targets.json`에서 고친다. 점검은 `python research/collect.py --only reddit --limit 2 --headed`로 한다. 채널 하나가 막혀도 나머지는 계속한다. 요청 사이 3~8초 간격, 전체 25분 상한이 있다.
- **CAPTCHA·로그인·차단은 우회하지 않는다.** 감지되면 그 채널을 멈추고 남은 검색을 `manual_check`로 기록한다. 검증 단계가 이를 `competitor.json`의 `manual_check`로 옮기고, [경쟁사 동향] 탭 맨 위 "직접 확인 필요" 카드(검색 링크 포함)에 표시된다.
- **Instagram 별도 계정**(X는 사용하지 않기로 결정, `targets.json`의 `disabled_channels`에서 `x`를 빼면 다시 켤 수 있다): `python research/sns_login.py instagram` 을 실행하면 창이 열리고 **그 창에서 직접** 로그인한다(아이디·비밀번호를 채팅이나 파일에 적지 않는다). 세션은 `%LOCALAPPDATA%\view_research\profiles\<사이트>`, 계정 번호·시각은 `%LOCALAPPDATA%\view_research\accounts.json`에 남는다. 상태 확인은 `--status`, 세션이 풀리면 다시 로그인한다. TikTok은 계정 없이 시도하고 막히면 직접 확인 목록으로 간다.
- **"새로운 것" 우선 구조**: 광고주 관심사는 **새 마케팅·바이럴 방식**(`novelty: new_method`)과 **새 해외시장·유입 경로**(`new_market`)다. [경쟁사 동향] 맨 위 브리핑에는 이 두 가지만 나오고, 나머지(기존 흐름, 직접 확인 필요, 핵심 움직임, 통계)는 `<details>`로 접혀 있다. `new_*` 항목은 `novelty_reason`이 필수다(`validate.py` 검사).
- **판정 기준선** `research/known_tactics.json`: 30일 보관과 별개로 오래 남는 '알려진 전술' 목록이다(지침서 9장 + 확정된 신규). 같은 병원의 같은 전술이면 `continuation`이다.
- **수집 → 선별 → 분석**: `collect.py`(우선순위 `channel_order`) → `research/triage.py`(신규 신호 점수로 후보 선별, `logs/raw/triage_*.json`) → `make_prompt.py`가 후보를 프롬프트 맨 앞에 넣음 → AI 분석. 사이트맵·공식 페이지·Instagram은 `logs/watch_state.json` 기준선과 비교해 **새로 생긴 URL·게시물만** 신규로 본다.
- **접근 가능한 채널만**(2026-10-19 확인): 공식 사이트·사이트맵, 네이버 뉴스·블로그·카페, Instagram(공식 계정), YouTube, Reddit, Ameblo·Note(공식 계정), 일본 Yahoo!リアルタイム(X 공개 글, 로그인 없음)·知恵袋, 대만 PTT, 태국 Pantip. TikTok·X 직접·Dcard·Threads·Pinterest·중국 SNS·강남언니·바비톡은 쓰지 않는다(`targets.json` `disabled_channels`). 일본어 병원명(`ja`)은 공식 사이트 제목에서 확인한 것만 쓴다.
- **조사 기간**: 버튼 옆 선택창(최근 7일·2주(기본)·30일·3개월·직접 지정, 최대 92일)이 `logs/research_params.json`을 거쳐 `research/make_prompt.py`로 프롬프트 맨 위에 들어간다. 직접 bat을 실행하면 최근 14일이다. 월별 저장은 조사 실행일이 속한 달이고, 기간은 `runs[].period`에 남는다.
- **보관 기간 30일**: 순위(`build_data.py`, 회차 시각 기준)와 경쟁사 자료(`validate.py --check`의 `prune`, 마지막 확인일 `last_seen` 기준)는 한 달이 지나면 웹 자료에서 폐기된다. 폐기된 경쟁사 글의 URL은 짧은 해시로만 `seen_urls`에 365일 남겨 같은 글이 다시 들어오지 않게 한다. 원본 `results_*.csv`는 지우지 않는다(로컬 보관). 이미 푸시된 과거 커밋에는 옛 자료가 남아 있다.
- 이 파일은 공개 페이지(GitHub Pages)에 그대로 올라간다. 개인 식별 정보를 넣지 않는다.

## 에이전트
- 경쟁사 총괄(통합 검토·중복·핵심 요약): `competitor-researcher` (`.claude/agents/competitor-researcher.md`)
- 경쟁사 영역별 담당(각자 조사·정리·검토, 서로의 항목은 수정하지 않음, 순서대로 하나씩 실행):
  `competitor-sns-manager`(SNS), `competitor-web-manager`(홈페이지·뉴스·블로그), `competitor-community-manager`(커뮤니티·후기·만족도)
- 순위 확인·보고: `rank-checker` (`.claude/agents/rank-checker.md`)
- 오류 점검·조치: `rank-troubleshooter` (`.claude/agents/rank-troubleshooter.md`)

## 프로그램 운영 규칙 (원 운영자 전달본)
@뷰성형외과_순위담당_20261013/뷰성형외과_순위담당/CLAUDE.md
