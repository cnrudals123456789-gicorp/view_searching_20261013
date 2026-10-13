# 뷰성형외과 순위 모니터링 (이 PC 운영 + GitHub Pages 공유)

- 순위 체크는 이 PC에서 매일 10:10·16:10 실행 (오전/오후 조회, 엑셀은 웹에서 날짜별로 내려받음) (네이버 로그인 세션 필요 → GitHub에서는 실행 불가)
- 결과는 `build_data.py` → `docs/data.json` → `git push` → GitHub Pages 로 공유 (`publish.bat`, 스케줄러는 `run_and_publish.bat`)
- 공개 저장소이므로 **원자료 CSV·엑셀·계정 정보는 커밋하지 않는다** (`.gitignore` 참조)

## 에이전트
- 순위 확인·보고: `rank-checker` (`.claude/agents/rank-checker.md`)
- 오류 점검·조치: `rank-troubleshooter` (`.claude/agents/rank-troubleshooter.md`)

## 프로그램 운영 규칙 (원 운영자 전달본)
@뷰성형외과_순위담당_20261013/뷰성형외과_순위담당/CLAUDE.md
