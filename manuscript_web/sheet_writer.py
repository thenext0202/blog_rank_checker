"""구글 시트 기입 — '원고 작성 리스트' 탭 A~L열.

규칙:
- append_rows 금지 → ws.update(range_name, [row]) 로 범위 명시 기입
- 다음 빈 행을 A열 기준으로 찾음
- L열 '원고 다운로드'는 APP_BASE_URL 환경변수 있을 때만 HYPERLINK 수식 기입
"""
import os
import gspread
from google.oauth2.service_account import Credentials
from config import (
    get_credentials_path,
    load_sheet_id,
    DEFAULT_TAB_NAME,
)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# 제품 링크 탭 이름 (A=제품명, B=제품 약어, C=base 링크)
PRODUCT_LINK_TAB = "제품 링크"

# 행 높이 고정값 (픽셀) — 본문이 길어도 시트 행이 늘어나지 않게 고정
ROW_PIXEL_SIZE = 21

# A~M열 헤더 (시트에 이미 작성되어 있음)
HEADERS = [
    "작성일", "제품명", "카테고리", "키워드", "담당자", "제품 링크",
    "제목", "본문", "글자수", "심의 결과", "모델명", "원고 다운로드",
    "파일명",
]


def _open_ws(sheet_id=None, tab_name=None):
    creds = Credentials.from_service_account_file(
        get_credentials_path(), scopes=SCOPES
    )
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(sheet_id or load_sheet_id())
    return sh.worksheet(tab_name or DEFAULT_TAB_NAME)


def load_product_links(sheet_id=None):
    """'제품 링크' 탭에서 {제품명: {"code": 약어, "base_link": URL}} 로드.

    실패 시 빈 dict 반환 (앱 기동 방해하지 않음).
    """
    try:
        ws = _open_ws(sheet_id, PRODUCT_LINK_TAB)
        out = {}
        for row in ws.get_all_values()[1:]:
            if len(row) < 3:
                continue
            name, code, link = row[0].strip(), row[1].strip(), row[2].strip()
            if name and link:
                out[name] = {"code": code, "base_link": link}
        return out
    except Exception as e:
        print(f"[sheet_writer] 제품 링크 로드 실패: {e}")
        return {}


def build_product_link(base_link, nt_medium, date_str, keyword, product_code):
    """base_link에 추적 파라미터 조립.

    - date_str: 'YYYY-MM-DD' 또는 'YYMMDD' 허용 → 출력은 YYMMDD
    - keyword: 쉼표 구분이면 첫 키워드만 사용, 내부 공백 제거
    반환: 'base_link?nt_source=blog&nt_medium=...&nt_detail=YYMMDD키워드&nt_keyword=약어'
    """
    if not base_link:
        return ""
    # 날짜 정규화: YYYY-MM-DD → YYMMDD
    d = (date_str or "").strip()
    if len(d) == 10 and d[4] == '-' and d[7] == '-':
        d = d[2:4] + d[5:7] + d[8:10]
    elif len(d) == 8 and d.isdigit():
        d = d[2:]  # YYYYMMDD → YYMMDD
    # 키워드: 첫 번째만 + 공백 제거
    kw = (keyword or "").split(',')[0].strip().replace(" ", "")
    nt_detail = f"{d}{kw}"
    params = ["nt_source=blog"]
    if nt_medium:
        params.append(f"nt_medium={nt_medium.strip()}")
    if nt_detail:
        params.append(f"nt_detail={nt_detail}")
    if product_code:
        params.append(f"nt_keyword={product_code.strip()}")
    return f"{base_link}?{'&'.join(params)}"


def _next_empty_row(ws):
    """A열 기준 다음 빈 행 번호 (1-based)."""
    col_a = ws.col_values(1)
    return len(col_a) + 1


def _fix_row_height(ws, start_row, end_row=None):
    """행 높이를 ROW_PIXEL_SIZE로 고정 (본문 길어도 행이 늘어나지 않음).

    start_row/end_row는 1-based 행 번호. end_row 생략 시 start_row 한 줄만.
    """
    end_row = end_row or start_row
    try:
        ws.spreadsheet.batch_update({
            "requests": [{
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": ws.id,
                        "dimension": "ROWS",
                        "startIndex": start_row - 1,
                        "endIndex": end_row,
                    },
                    "properties": {"pixelSize": ROW_PIXEL_SIZE},
                    "fields": "pixelSize",
                }
            }]
        })
    except Exception as e:
        print(f"[sheet_writer] 행 높이 고정 실패: {e}")


def _hyperlink_formula(row, download_base_url=None):
    """L열 원고 다운로드 HYPERLINK 수식.

    download_base_url(또는 APP_BASE_URL 환경변수) + /download_row/N 링크 생성.
    시트에서 클릭 → 서버가 H열 본문으로 .docx 즉석 생성해 반환.
    base가 없으면 빈 문자열 (시트 링크 미사용).
    """
    base = (download_base_url or os.environ.get("APP_BASE_URL", "")).strip().rstrip("/")
    if not base:
        return ""
    return f'=HYPERLINK("{base}/download_row/{row}", "원고 다운로드")'


def write_row(
    write_date, product_name, category, keyword, writer_name, product_link,
    title, body, char_count, review, model_name,
    sheet_id=None, tab_name=None, download_base_url=None,
    filename="",
):
    """한 건 기입. 기입한 행 번호 반환.

    download_base_url(예: http://localhost:5000)이 주어지면 L열에
    /download_row/N HYPERLINK 수식 기입. 시트 클릭 시 서버가 .docx 서빙.
    filename: M열 '파일명' (담당자_YYMMDD키워드_카테고리_제품코드).
    """
    ws = _open_ws(sheet_id, tab_name)
    row = _next_empty_row(ws)
    if row < 2:
        row = 2  # 1행은 헤더 보호

    values = [
        write_date, product_name, category, keyword, writer_name, product_link,
        title, body, char_count, review, model_name,
        _hyperlink_formula(row, download_base_url),
        filename,
    ]
    range_name = f"A{row}:M{row}"
    ws.update(range_name, [values], value_input_option="USER_ENTERED")
    _fix_row_height(ws, row)
    return row


def update_l_column_bulk(
    download_base_url, sheet_id=None, tab_name=None, dry_run=False,
):
    """기존 행들의 L열 HYPERLINK를 /download_row/N 링크로 일괄 갱신.

    - 1행(헤더)은 건너뜀
    - H열(본문)이 있는 행만 대상 (빈 행/미완성 행 보호)
    - 기존 L열 값은 덮어씌움 (과거 Drive URL 교체용)
    Returns: {"count": 갱신 행 수, "rows": [행 번호 리스트]}
    """
    ws = _open_ws(sheet_id, tab_name)
    all_vals = ws.get_all_values()
    if len(all_vals) < 2:
        return {"count": 0, "rows": []}

    target_rows = []
    updates = []
    for i, row in enumerate(all_vals):
        r_num = i + 1
        if r_num == 1:
            continue
        body = row[7] if len(row) > 7 else ''  # H열 = 본문
        if not body.strip():
            continue
        target_rows.append(r_num)
        if not dry_run:
            updates.append({
                "range": f"L{r_num}",
                "values": [[_hyperlink_formula(r_num, download_base_url)]],
            })

    if updates:
        ws.batch_update(updates, value_input_option="USER_ENTERED")

    return {"count": len(target_rows), "rows": target_rows}


def write_rows_batch(rows, sheet_id=None, tab_name=None, download_base_url=None):
    """여러 건 일괄 기입. 각 row는 write_row와 같은 순서의 리스트.

    download_base_url: L열 /download_row/N 링크 기반. 없으면 빈 L열.
    각 row는 A~K(11개) 또는 A~K+M파일명(12개) 형태 허용.
    반환: 기입한 첫 행 번호와 마지막 행 번호 (first, last)
    """
    if not rows:
        return 0, 0
    ws = _open_ws(sheet_id, tab_name)
    start = _next_empty_row(ws)
    if start < 2:
        start = 2

    built = []
    for i, r in enumerate(rows):
        row_num = start + i
        base = list(r)
        filename = base.pop(11) if len(base) >= 12 else ""
        # base는 A~K(11개), L은 HYPERLINK, M은 파일명
        vals = base + [_hyperlink_formula(row_num, download_base_url), filename]
        built.append(vals)

    end = start + len(built) - 1
    range_name = f"A{start}:M{end}"
    ws.update(range_name, built, value_input_option="USER_ENTERED")
    _fix_row_height(ws, start, end)
    return start, end
