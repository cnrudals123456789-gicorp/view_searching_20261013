"""경로 기준 (2026-10-06 폴더 정리): 프로그램은 '순위체크_프로그램' 하위 폴더, 순위요약 엑셀은 그 위(01.뷰성형외과/01.순위담당) 폴더에 둔다."""
from pathlib import Path

PROG = Path(__file__).resolve().parent
XL_DIR = PROG.parent if PROG.name == "순위체크_프로그램" else PROG          # 순위요약_YYYY-MM.xlsx 위치
BOARD = XL_DIR.parent / "00.에이전트리더" / "board_update.py"               # 에이전트 리더 대시보드
