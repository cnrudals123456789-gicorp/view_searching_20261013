"""
최근 실행 결과를 엑셀/시트에 바로 붙여넣을 수 있는 탭 구분 텍스트로 만듭니다.
키워드 순서는 settings.json 그대로 (파워컨텐츠 = pc_keywords, 파워링크 = keywords).

  python paste.py            # 최신 실행분 파워컨텐츠 블록을 출력하고 클립보드에 복사
  python paste.py --link     # 파워링크 블록
  python paste.py --kw       # 키워드 열 포함 (키워드 \t PC \t MO)
  python paste.py --num      # 더보기 순위도 숫자만 (기본: '더보기 5' 처럼 표기)
  python paste.py --no-clip  # 클립보드 복사 생략

매 실행 후 rank.run 이 write_paste() 로 붙여넣기_최신.txt 를 갱신합니다 (파워컨텐츠, 순위만).
값: 첫 화면 순위 = 숫자 / 더보기 목록 = '더보기 N' / 없으면 '미노출' 또는 '영역없음'
"""
import csv
import sys
from pathlib import Path

from summary import SHEETS, reorder, summarize

BASE_DIR = Path(__file__).resolve().parent
PASTE_FILE = BASE_DIR / "붙여넣기_최신.txt"


def _cell(v, num_only=False):
    if v is None:
        return ""
    val, kind, _ = v
    if kind == "more" and not num_only:
        return f"더보기 {val}"
    return str(val)


def build(rows, base_dir: Path, ad_type="powercontents", with_kw=False, num_only=False):
    """rows(CSV dict) → 탭 구분 문자열. 한 줄 = 한 키워드, 열 = [키워드,] PC, MO"""
    data = reorder(summarize(rows), base_dir)[ad_type]
    order = [k for k in data]
    lines = []
    for kw in order:
        devs = data[kw]
        cells = [_cell(devs.get("pc"), num_only), _cell(devs.get("mobile"), num_only)]
        if with_kw:
            cells.insert(0, kw)
        lines.append("\t".join(cells))
    return "\n".join(lines), order


def write_paste(rows, ts: str, base_dir: Path, log=print):
    """실행 직후 호출: 파워컨텐츠 블록을 붙여넣기_최신.txt 에 저장 (순위만, 헤더 없음)"""
    text, order = build(rows, base_dir, "powercontents")
    if not text:
        return None
    path = base_dir / PASTE_FILE.name
    path.write_text(f"# {ts[:16]} 파워컨텐츠 (PC / MO) — 순서: {', '.join(order)}\n{text}\n", encoding="utf-8")
    log(f"붙여넣기 파일 저장: {path}")
    return path


def latest_rows(base_dir: Path):
    """가장 최근 results_*.csv 의 마지막 실행(timestamp) 행들"""
    files = sorted(base_dir.glob("results_????????.csv"))
    if not files:
        return [], ""
    with open(files[-1], encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return [], ""
    ts = max(r["timestamp"] for r in rows)
    return [r for r in rows if r["timestamp"] == ts], ts


def to_clipboard(text: str):
    """Win32 클립보드에 유니코드로 직접 기록 (clip.exe 는 콘솔 코드페이지에 따라 한글이 깨져서 사용 안 함)"""
    import ctypes
    from ctypes import wintypes
    k32, u32 = ctypes.windll.kernel32, ctypes.windll.user32
    data = text.replace("\n", "\r\n").encode("utf-16le") + b"\x00\x00"
    if not u32.OpenClipboard(None):
        raise OSError("OpenClipboard 실패")
    try:
        u32.EmptyClipboard()
        k32.GlobalAlloc.restype = ctypes.c_void_p
        k32.GlobalLock.restype = ctypes.c_void_p
        k32.GlobalLock.argtypes = k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        h = k32.GlobalAlloc(0x0042, len(data))                     # GMEM_MOVEABLE | GMEM_ZEROINIT
        ctypes.memmove(k32.GlobalLock(h), data, len(data))
        k32.GlobalUnlock(h)
        u32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
        if not u32.SetClipboardData(13, h):                        # CF_UNICODETEXT
            raise OSError("SetClipboardData 실패")
    finally:
        u32.CloseClipboard()


def main():
    args = sys.argv[1:]
    ad_type = "powerlink" if "--link" in args else "powercontents"
    rows, ts = latest_rows(BASE_DIR)
    if not rows:
        print("[!] 결과 파일이 없습니다. 먼저 순위 체크를 실행하세요.")
        sys.exit(1)
    text, order = build(rows, BASE_DIR, ad_type, with_kw="--kw" in args, num_only="--num" in args)
    print(f"[{ts[:16]}] {SHEETS[ad_type]}  (열: {'키워드, ' if '--kw' in args else ''}PC, MO)")
    for kw, line in zip(order, text.split("\n")):
        print(f"  {kw:<10}\t{line}" if "--kw" not in args else f"  {line}")
    if "--no-clip" not in args:
        try:
            to_clipboard(text)
            print(f"→ 클립보드에 복사됨 ({len(order)}줄). 시트의 첫 칸을 선택하고 Ctrl+V")
        except Exception as e:
            print(f"[!] 클립보드 복사 실패: {e}")


if __name__ == "__main__":
    main()
