# -*- coding: utf-8 -*-
"""블록 체커 탭 연결·읽기·기록. 이 탭 외 다른 탭은 절대 다루지 않는다."""
import os, json, base64, re
import gspread
from google.oauth2.service_account import Credentials

BASE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(BASE, "config.json"), encoding="utf-8") as f:
    CFG = json.load(f)

SHEET_ID = CFG["SHEET_ID"]
TAB_NAME = CFG["TAB_NAME"]
CRED_FILE = os.path.normpath(os.path.join(BASE, CFG["CRED_FILE_REL"]))

HEADER = ["키워드", "실행", "인기글", "인기글 날짜", "스블",
          "스블 주제·날짜", "통검블로그", "통검 날짜", "상태"]


def _client():
    scope = ["https://www.googleapis.com/auth/spreadsheets",
             "https://www.googleapis.com/auth/drive"]
    b64 = os.environ.get("GOOGLE_CREDENTIALS_BASE64")
    if b64:
        creds = Credentials.from_service_account_info(json.loads(base64.b64decode(b64)), scopes=scope)
    else:
        creds = Credentials.from_service_account_file(CRED_FILE, scopes=scope)
    return gspread.authorize(creds)


def connect():
    """블록 체커 탭 워크시트 반환(없으면 생성 + 헤더 + 체크박스)."""
    ss = _client().open_by_key(SHEET_ID)
    titles = [w.title for w in ss.worksheets()]
    if TAB_NAME in titles:
        return ss.worksheet(TAB_NAME)
    ws = ss.add_worksheet(title=TAB_NAME, rows=500, cols=len(HEADER))
    ws.update(values=[HEADER], range_name=f"A1:{chr(ord('A')+len(HEADER)-1)}1")
    _set_checkbox(ss, ws, "B2:B500")
    return ws


def _set_checkbox(ss, ws, range_str):
    m = re.match(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", range_str)
    sc = ord(m.group(1)) - ord("A"); sr = int(m.group(2)) - 1
    ec = ord(m.group(3)) - ord("A") + 1; er = int(m.group(4))
    ss.batch_update({"requests": [{"setDataValidation": {
        "range": {"sheetId": ws.id, "startRowIndex": sr, "endRowIndex": er,
                  "startColumnIndex": sc, "endColumnIndex": ec},
        "rule": {"condition": {"type": "BOOLEAN"}, "showCustomUi": True}}}]})


def parse_targets(rows):
    """get_all_values() 결과 → 체크된(B열 TRUE) + 키워드 있는 행 [(행번호, 키워드)]."""
    out = []
    for idx, row in enumerate(rows[1:], start=2):
        kw = (row[0].strip() if len(row) > 0 else "")
        chk = (row[1].strip().upper() if len(row) > 1 else "")
        if kw and chk in ("TRUE", "O", "V", "Y", "1", "ㅇ"):
            out.append((idx, kw))
    return out


def read_targets(ws):
    """워크시트에서 체크된 대상 행 읽기."""
    return parse_targets(ws.get_all_values())


def clear_checkboxes(ws, row_nums):
    """처리한 행들의 B열 체크 해제."""
    if not row_nums:
        return
    ws.batch_update([{"range": f"B{r}", "values": [[False]]} for r in row_nums])
