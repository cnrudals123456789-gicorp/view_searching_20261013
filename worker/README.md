# 공개 페이지 '조회 요청' Worker 설치 (1회)

1. **GitHub 토큰 만들기** — GitHub → Settings → Developer settings → Fine-grained tokens → Generate
   - Repository access: *Only select repositories* → `view_searching_20261013`
   - Permissions: **Contents: Read and write** (다른 권한 없음), 만료는 90일 정도로
2. **Cloudflare 가입** (무료) → 터미널에서
   ```
   cd worker
   npx wrangler login
   npx wrangler secret put GITHUB_TOKEN     # 위 토큰을 여기에만 붙여넣기 (대화·파일에 쓰지 않기)
   npx wrangler deploy
   ```
3. 배포 후 나오는 주소(`https://view-rank-request.<계정>.workers.dev`)를 `docs/config.js` 의 `RANK_API` 에 넣고 푸시
4. 이 PC 에서 `powershell -ExecutionPolicy Bypass -File ..\작업스케줄러_등록.ps1` (2분마다 요청 확인 작업 포함)

## 규칙
- 마지막 조회 완료 후 30분(COOLDOWN_MIN) 안에는 거절, 하루 12회(DAILY_CAP, KST) 상한
- 요청은 `docs/request.json` 에만 기록. 토큰은 Worker 비밀값에만 존재
- 토큰이 노출됐다면 GitHub 에서 즉시 폐기(Revoke) 후 새로 발급
