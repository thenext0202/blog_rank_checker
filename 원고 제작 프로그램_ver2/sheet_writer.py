"""원고 작성기 — 구글 시트 연동 (읽기/쓰기)"""
import gspread
from google.oauth2.service_account import Credentials
from config import get_credentials_path

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# 완성원고 탭 헤더
HEADERS = ["번호", "키워드", "제품명", "날짜", "medium", "제품링크",
           "완성원고", "페르소나 분석(A)", "블록 구성(B)"]


def connect_sheet(sheet_id):
    """구글 시트 연결"""
    cred_path = get_credentials_path()
    creds = Credentials.from_service_account_file(cred_path, scopes=SCOPES)
    gc = gspread.authorize(creds)
    return gc.open_by_key(sheet_id)


def _get_next_row(ws):
    """마지막 데이터 행 다음 행 번호 반환"""
    values = ws.col_values(1)  # A열 기준
    return len(values) + 1


def _get_next_number(ws):
    """마지막 번호 + 1 반환 (A열이 번호)"""
    values = ws.col_values(1)
    nums = []
    for v in values[1:]:
        try:
            nums.append(int(v))
        except (ValueError, TypeError):
            pass
    return max(nums, default=0) + 1


def write_manuscript(spreadsheet, keyword, product_name, date, medium,
                     product_link, phase_c, phase_a="", phase_b=""):
    """
    '완성원고' 탭에 원고 + Phase A/B 분석 결과 기입.

    시트 구조: 번호 | 키워드 | 제품명 | 날짜 | medium | 제품링크 | 완성원고 | Phase A | Phase B
    """
    try:
        ws = spreadsheet.worksheet("완성원고")
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title="완성원고", rows=1000, cols=len(HEADERS))
        ws.update(f"A1:{chr(64+len(HEADERS))}1", [HEADERS])

    next_row = _get_next_row(ws)
    next_num = _get_next_number(ws)

    row_data = [next_num, keyword, product_name, date, medium, product_link,
                phase_c, phase_a, phase_b]
    end_col = chr(64 + len(row_data))
    cell_range = f"A{next_row}:{end_col}{next_row}"
    ws.update(cell_range, [row_data], value_input_option="USER_ENTERED")

    return next_row
