"""Google Sheets 연동 모듈 — 발행 대기 행 읽기 + URL 기록"""

import os

import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


def connect(sheet_id: str, tab_name: str, cred_path: str):
    """시트에 연결하여 Worksheet 반환"""
    if not os.path.exists(cred_path):
        print(f"[오류] 인증 파일이 없습니다: {cred_path}")
        print("  credentials.json 파일을 확인해주세요.")
        return None

    try:
        creds = Credentials.from_service_account_file(cred_path, scopes=SCOPES)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(sheet_id)
        ws = spreadsheet.worksheet(tab_name)
        print(f"[OK] 시트 연결: {spreadsheet.title} / {tab_name}")
        return ws
    except Exception as e:
        print(f"[오류] 시트 연결 실패: {e}")
        print("  시트 ID와 탭 이름을 확인하고, 서비스 계정에 편집자 공유가 되어있는지 확인하세요.")
        return None


def _col_to_index(col_letter: str) -> int:
    """열 문자 → 0기반 인덱스 (A=0, B=1, ...)"""
    return ord(col_letter.upper()) - ord("A")


def get_pending_rows(ws, config: dict) -> list:
    """E열이 비어있는 행만 반환. [{row_num, blog_id, keyword, title, template_name}]"""
    all_rows = ws.get_all_values()

    blog_id_idx = _col_to_index(config["blog_id_col"])
    keyword_idx = _col_to_index(config["keyword_col"])
    title_idx = _col_to_index(config["title_col"])
    url_idx = _col_to_index(config["publish_url_col"])
    # 템플릿명 열 (기본값: keyword_col과 동일)
    template_col = config.get("template_name_col", config["keyword_col"])
    template_idx = _col_to_index(template_col)
    # 카테고리 열 (선택사항)
    category_col = config.get("category_col", "")
    category_idx = _col_to_index(category_col) if category_col else -1
    # 공개 여부 열 (선택사항)
    public_col = config.get("public_col", "")
    public_idx = _col_to_index(public_col) if public_col else -1
    start_row = config.get("start_row", 2)

    all_indices = [blog_id_idx, keyword_idx, title_idx, url_idx, template_idx]
    if category_idx >= 0:
        all_indices.append(category_idx)
    if public_idx >= 0:
        all_indices.append(public_idx)

    pending = []
    for i, row in enumerate(all_rows):
        row_num = i + 1  # 1기반
        if row_num < start_row:
            continue

        # 열 범위 벗어나면 건너뜀
        if len(row) <= max(all_indices):
            continue

        blog_id = row[blog_id_idx].strip()
        title = row[title_idx].strip()
        url_val = row[url_idx].strip()
        template_name = row[template_idx].strip()

        # 카테고리 값
        category = ""
        if category_idx >= 0 and len(row) > category_idx:
            category = row[category_idx].strip()

        # 공개 여부 (TRUE/체크/O/공개 → True, 그 외 → False)
        is_public = False
        if public_idx >= 0 and len(row) > public_idx:
            val = row[public_idx].strip().upper()
            is_public = val in ("TRUE", "O", "공개", "Y", "YES", "1", "체크")

        # 블로그ID + 제목이 있고, 발행 링크가 비어있는 행만
        if blog_id and title and not url_val:
            pending.append({
                "row_num": row_num,
                "blog_id": blog_id,
                "keyword": row[keyword_idx].strip(),
                "title": title,
                "template_name": template_name or title,
                "category": category,
                "is_public": is_public,
            })

    return pending


def write_url(ws, row_num: int, col_letter: str, url: str):
    """발행 URL을 시트에 기록"""
    cell = f"{col_letter.upper()}{row_num}"
    ws.update_acell(cell, url)
    print(f"  시트 {cell}에 URL 기록 완료")
