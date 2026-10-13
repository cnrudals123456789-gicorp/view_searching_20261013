/**
 * 뷰성형외과 순위 → 구글시트 연동 (에이전트 리더, 2026-10-01)
 * 설치: 확장 프로그램 > Apps Script 에 이 코드 전체 붙여넣기 > 저장
 *       배포 > 새 배포 > 유형: 웹 앱 / 실행: 나 / 액세스: 모든 사용자 > 배포 > 권한 승인 > 웹 앱 URL 복사
 * 비밀 토큰이 맞는 요청만 처리합니다. 이 코드를 다른 사람과 공유하지 마세요.
 */
const SHEET_ID = '1ocBUM7-LJ8LobCMOT3uJZJv0uQqX4bIonBDthdm0ZaY';  // 뷰성형외과_국내_관리시트_GI
const TOKEN = 'CHANGE_ME';  // 전달용: 원래 토큰 제거. 새로 정해 LOCALAPPDATA/naver_powerlink/gsheet_token.txt 와 같게

function doGet(e) { return handle_(e.parameter || {}); }
function doPost(e) { return handle_(JSON.parse(e.postData.contents || '{}')); }

function handle_(p) {
  const out = (o) => ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
  if (p.token !== TOKEN) return out({ ok: false, error: 'unauthorized' });
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet() || SpreadsheetApp.openById(SHEET_ID);
    const sh = p.sheet ? ss.getSheetByName(p.sheet) : null;
    switch (p.action) {
      case 'sheets':   // 탭 목록
        return out({ ok: true, sheets: ss.getSheets().map(s => ({ name: s.getName(), rows: s.getLastRow(), cols: s.getLastColumn(), frozen: s.getFrozenRows() })) });
      case 'find':     // 텍스트가 있는 셀 위치 (예: '날짜')
        return out({ ok: true, hits: sh.createTextFinder(p.text).matchEntireCell(p.whole === 'true' || p.whole === true).findAll().slice(-(+p.limit || 50)).map(r => r.getA1Notation()) });
      case 'read':     // 범위 값·표시값
        const rg = sh.getRange(p.range);
        return out({ ok: true, range: p.range, values: rg.getValues(), display: rg.getDisplayValues(), formulas: rg.getFormulas() });
      case 'write':    // 범위에 값 쓰기 (values: 2차원 배열)
        sh.getRange(p.range).setValues(p.values);
        return out({ ok: true, wrote: p.range });
      case 'copy':     // 서식 포함 블록 복사 (src → dst 좌상단)
        sh.getRange(p.src).copyTo(sh.getRange(p.dst));
        return out({ ok: true, copied: p.src + ' -> ' + p.dst });
      default:
        return out({ ok: false, error: 'unknown action' });
    }
  } catch (err) {
    return out({ ok: false, error: String(err) });
  }
}
