# 뷰성형외과 순위담당 에이전트 (전달본, 2026-10-13 기준)

GI코퍼레이션에서 운영하던 **뷰성형외과 네이버 파워링크·파워컨텐츠 순위 자동 체크**를 그대로 옮긴 패키지입니다.
Claude Code는 이 파일을 읽고 아래 "처음 설치" 순서대로 받은 사람의 PC에 세팅한 뒤, "운영 규칙"을 지켜 운영합니다.

## 하는 일
- 로그인한 네이버 계정 기준(연령·성별 타겟팅 반영)으로 키워드를 검색해 **뷰성형외과 광고 순위**를 PC·모바일별로 확인
  - 파워링크: 도메인 `viewclinic.com` 매칭 / 파워컨텐츠: 브랜드명 `뷰성형외과의원` 매칭
  - 첫 화면에 없으면 '더보기' 목록 끝까지 확인
- 매일 **10:10 · 16:00** 자동 실행 (Windows 작업 스케줄러)
- 결과
  - `01.뷰성형외과\01.순위담당\순위요약_YYYY-MM.xlsx` — 월별 누적 엑셀 (아래 형식)
  - `01.뷰성형외과\모니터링완료_YYYY-MM-DD_HHMM.xlsx` — 최신 회차 확인용 사본, 항상 **최신 1개만** 유지
  - `순위체크_프로그램\results_YYYYMMDD.csv` — 원자료 / `붙여넣기_최신.txt` — 파워컨텐츠 붙여넣기용

## 폴더 구조 (이 구조 그대로 둘 것 — 경로를 폴더 이름으로 판단함)
```
01.뷰성형외과\
├ 모니터링완료_*.xlsx            ← 실행하면 생김
└ 01.순위담당\
   ├ 순위요약_2026-10.xlsx        ← 당월 엑셀만 이 위치
   └ 순위체크_프로그램\           ← 코드·설정·CSV 전부
      ├ run.py / rank.py / common.py / login.py   순위 체크 본체
      ├ summary.py                 엑셀 누적 ('순위' 시트 1개)
      ├ publish_done.py            모니터링완료 사본
      ├ paste.py / 붙여넣기.bat     클립보드 복사
      ├ app.py / web\ / 대시보드.bat 웹 대시보드 http://127.0.0.1:8765
      ├ 자동순위체크.bat            스케줄러용 (인터넷 대기 → 실행 → 실패 시 3분 간격 최대 4회)
      ├ 작업스케줄러_등록.ps1        스케줄러 등록
      ├ settings.json              키워드·도메인·브랜드명 (키워드 순서 = 엑셀 순서)
      └ README.md                  상세 사용법
```

## 처음 설치 (Claude Code가 순서대로 진행)
1. Python 3.12 이상 확인 (`python --version`). 없으면 python.org 에서 설치 안내
2. 패키지: `python -m pip install -r requirements.txt` → `python -m playwright install chromium`
3. 네이버 계정 저장: 사용자에게 **본인이 직접** 실행하도록 안내 (비밀번호를 대화에 쓰지 않게)
   - `! python login.py --set 아이디 비밀번호`
   - 저장 위치: `%LOCALAPPDATA%\naver_powerlink\credentials.json` (OneDrive·패키지 밖, 공유 금지)
   - ※ 타겟팅이 계정 연령·성별에 따라 달라지므로, 기존과 같은 순위를 보려면 원래 운영 계정을 쓰는 것이 맞음 (계정 정보는 전달자에게 따로 받을 것)
4. 시험 실행: `순위체크_프로그램` 폴더에서 `PYTHONUTF8=1` 설정 후 `python run.py`
   → 엑셀에 한 회차(26줄) 추가, 모니터링완료 사본 생성 확인
5. 자동 실행: `powershell -ExecutionPolicy Bypass -File .\작업스케줄러_등록.ps1`
   - 절전 중에도 회차가 돌게 전원 설정: `powercfg /setacvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 1` 와 `/setdcvalueindex` 같은 값, 이후 `powercfg /setactive SCHEME_CURRENT`
   - `자동순위체크.bat dryrun` 으로 실제 검색 없이 흐름 확인 가능 (로그 `logs\YYYYMMDD_dryrun.log`)

## 엑셀 형식 (현행, 2026-10-13 지시)
- 시트 **'순위' 1개**: `실행시각 | 구분 | 키워드 | PC순위 | MO순위 | PC비고 | MO비고`
- 한 회차 = 파워링크 15줄(settings.json `keywords` 순) 바로 아래 파워컨텐츠 11줄(`pc_keywords` 순)
  - 결과가 없는 키워드도 빈 칸 행으로 넣어 줄 수 고정 → **PC·MO 두 열을 그대로 복사·붙여넣기**
- 순위 칸은 숫자 또는 `미노출` / `영역없음`. 첫 화면·더보기 구분은 비고 열에만 (색상 표시 안 함)
- 저장할 때마다 자동필터 조건·숨김 행을 해제 (`summary.show_all`) — 필터가 남아 "데이터가 없다"고 보였던 적 있음
- 엑셀을 열어 둔 채 실행되면 `순위요약_YYYY-MM_HHMM.xlsx` 로 따로 저장 → 다음 실행 때 자동 합침

## 운영 규칙 (원 운영자 지시 이력)
- 로그인은 사용자에게 묻지 말고 자동 처리. 매 실행 시 서버 세션 유효성 확인, 만료면 자동 재로그인 (미로그인 검색 시 순위가 실제와 달라짐)
- 미노출이어도 재확인 루프를 돌리지 않고 정규 회차 1회로 종료 (`recheck_loop.py` 는 미사용, 남겨 둠)
- 모니터링완료 사본은 `01.뷰성형외과\` 바로 아래 최신 1개만
- 키워드 추가·순서 변경은 `settings.json` (또는 대시보드) 에서. 엑셀·붙여넣기 순서가 따라 바뀜
- 수정 전 백업은 `01.순위담당\_backup\YYYYMMDD\` 아래 원래 하위 경로 그대로 (파일 옆 .bak 금지)
- 코드에는 절대 경로 대신 `__file__` 기준 상대 경로. 경로에 한글이 있으니 항상 따옴표
- Python 실행 시 `PYTHONUTF8=1` 필수 (없으면 cp949 인코딩 오류로 종료). 한글 이름 bat 는 Bash 말고 PowerShell 로 실행

## 받은 PC에서 없는 것 (정상)
- **계정·세션·토큰은 포함하지 않음**: 네이버 로그인 정보, 브라우저 세션, 구글시트 토큰
- 에이전트 리더 대시보드(`00.에이전트리더\board_update.py`) 없음 → `report_run.py` / `rank_table.py --post` 의 대시보드 보고만 조용히 건너뜀. 순위 체크·엑셀에는 영향 없음
- 구글시트 자동 기록(`gsheet\`)은 미완성 기능. 쓰려면 `gsheet\설치안내.txt` 대로 배포하고 `Code.gs` 의 `TOKEN` 을 새로 정해 `%LOCALAPPDATA%\naver_powerlink\gsheet_token.txt` 와 같게 설정
- 실행 로그(`logs\`)는 제외. 9/18 ~ 10/12 결과 CSV 와 10월 엑셀은 그대로 포함
