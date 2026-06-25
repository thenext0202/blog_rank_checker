#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
rank_checker.py - 순위 체커 통합 (공통 시트 연동)

공통 시트의 '순위 체커' 탭에서 체크박스 트리거 →
네이버 메인(통합검색) 순위만 확인 → 결과를 원본 탭 J열에 기록.
  (블로그탭 검색은 제거됨 — 메인 순위만 추적)

체크 일정: 발행일 기준 1·4·7·10·13·16·19·21일차(달력, 3일 간격) = 8회.

순위 체커 탭 구조 (자사+내부 섞여서 관리):
  A: 파라미터값 | B: 키워드 | C: 링크 | D: 실행(체크박스)
  E~L: 메인1 ~ 메인8 (8회차 메인 순위)
  M: 최초체크일 | N: 상태 | O: 발행일

실행 모드:
  python rank_checker.py          # 1회 실행 (체크된 행만)
  python rank_checker.py watch    # 60초 감시 모드 (로컬용)
  python rank_checker.py cron     # 일정 도래 행 자동 (Railway 크론용)
"""

import time
import re
import os
import json
import base64
import urllib.parse
from datetime import datetime, timedelta

import gspread
from google.oauth2.service_account import Credentials
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager


# ━━━━━━━━━━━━━━━━━━━━ 설정 ━━━━━━━━━━━━━━━━━━━━
SPREADSHEET_ID = "1jflcdbmBjQsY4hp8rNULXGGVqb64fGno4kudlTJoqM4"
TAB_SOURCE     = "자사 발행리스트"
TAB_INTERNAL   = "내부 발행리스트"
TAB_CHECKER    = "순위 체커"
CRED_FILE      = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "..", "manuscript_generator", "credentials.json")

# 체크 일정: 발행일로부터 경과 달력일. 슬롯 1~8에 1:1 대응.
#   발행일 다음날=1일차, 3일 간격, 마지막(21일차)만 2일 간격 → 최대 21일
SCHEDULE_DAYS = [1, 4, 7, 10, 13, 16, 19, 21]
NUM_SLOTS = len(SCHEDULE_DAYS)  # 8

# 크론 1회 실행당 순위체크 최대 건수 (시트가 발행일 최신순이라 새 글부터 처리).
# 개편 백로그(슬롯 비어 전부 도래로 잡힌 옛 글)는 매일 이만큼씩 소진된다.
MAX_CRON_PER_RUN = 300

# 자사 발행리스트 열 인덱스 (0-based)
SRC_COL_A = 0   # 발행일 (월/일)
SRC_COL_E = 4   # 키워드
SRC_COL_H = 7   # 파라미터값 (조인키)
SRC_COL_J = 9   # 순위 결과
SRC_COL_M = 12  # 링크 (타겟 URL)
SRC_COL_T = 19  # 구 블탭 표시 (이제 기록 안 함 — 남은 값 클리어용)

# 내부 발행리스트 열 인덱스 (0-based)
INT_COL_A = 0   # 발행일
INT_COL_E = 4   # 키워드
INT_COL_H = 7   # 파라미터값 (조인키)
INT_COL_J = 9   # 순위 결과
INT_COL_M = 12  # 링크 (타겟 URL)
INT_COL_Q = 16  # 구 블탭 표시 (이제 기록 안 함 — 남은 값 클리어용)

# 순위 체커 탭 열 인덱스 (0-based) — 메인 8슬롯
CHK_COL_A = 0    # 파라미터값
CHK_COL_B = 1    # 키워드
CHK_COL_C = 2    # 링크
CHK_COL_D = 3    # 실행 (체크박스)
# E~L = 메인1~메인8 (슬롯). 슬롯 컬럼 문자는 SLOT_COLS 참조.
CHK_SLOT_START = 4   # 메인1 = E열 (0-based 4)
CHK_COL_K = 12   # 최초체크일 (M열)  ※ 변수명은 호환 위해 유지
CHK_COL_L = 13   # 상태 (N열)
CHK_COL_M = 14   # 발행일 (O열, 자사 발행리스트 A열)

# 컬럼 문자 상수 (시트 범위 지정용)
SLOT_COLS = {f"slot{i}": chr(ord("A") + CHK_SLOT_START + i - 1)
             for i in range(1, NUM_SLOTS + 1)}   # slot1=E ... slot8=L
COL_FIRST  = "M"   # 최초체크일
COL_STATUS = "N"   # 상태
COL_PUB    = "O"   # 발행일
COL_LAST   = "O"   # 마지막 열 (범위 끝)
NUM_COLS   = ord(COL_LAST) - ord("A") + 1   # 15

# 노란색 배경 (순위 변동 표시)
LIGHT_YELLOW = {"backgroundColor": {"red": 1, "green": 1, "blue": 0.8}}
WHITE = {"backgroundColor": {"red": 1, "green": 1, "blue": 1}}
# 빨간색 배경 (고아 행 표시 — 발행리스트에서 사라진 파라미터)
LIGHT_RED = {"backgroundColor": {"red": 1, "green": 0.85, "blue": 0.85}}
ORPHAN_LABEL = "고아 (발행리스트 없음)"
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# ────────────────────────────────────────────────
#  Google Sheets 연결
# ────────────────────────────────────────────────

def connect_sheets():
    """공통 시트 연결 → (spreadsheet, ws_source, ws_internal, ws_checker) 반환"""
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds_b64 = os.environ.get("GOOGLE_CREDENTIALS_BASE64")
    if creds_b64:
        info = json.loads(base64.b64decode(creds_b64))
        creds = Credentials.from_service_account_info(info, scopes=scope)
    else:
        creds = Credentials.from_service_account_file(CRED_FILE, scopes=scope)

    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(SPREADSHEET_ID)
    ws_source = spreadsheet.worksheet(TAB_SOURCE)
    ws_internal = spreadsheet.worksheet(TAB_INTERNAL)
    ws_checker = ensure_checker_tab(spreadsheet)
    return spreadsheet, ws_source, ws_internal, ws_checker


# 순위 체커 탭 헤더 (15열, 메인 8슬롯)
CHECKER_HEADER = ["파라미터값", "키워드", "링크", "실행",
                  "메인1", "메인2", "메인3", "메인4",
                  "메인5", "메인6", "메인7", "메인8",
                  "최초체크일", "상태", "발행일"]


def _create_checker_ws(spreadsheet):
    """새 레이아웃(15열)으로 순위 체커 탭 생성 + 헤더 + 체크박스."""
    ws = spreadsheet.add_worksheet(title=TAB_CHECKER, rows=1000, cols=NUM_COLS)
    ws.update(values=[CHECKER_HEADER], range_name=f"A1:{COL_LAST}1")
    set_checkbox(spreadsheet, ws, "D2:D1000")
    print(f"    '{TAB_CHECKER}' 탭 생성 완료 (메인 8슬롯)")
    return ws


def ensure_checker_tab(spreadsheet):
    """순위 체커 탭 반환. 없으면 생성.
    기존 탭이 구 레이아웃(블탭 포함)이면 백업으로 rename 후 새 탭 재생성(데이터 보존)."""
    existing = [ws.title for ws in spreadsheet.worksheets()]
    if TAB_CHECKER not in existing:
        return _create_checker_ws(spreadsheet)

    ws = spreadsheet.worksheet(TAB_CHECKER)
    header = ws.row_values(1)
    if header[:len(CHECKER_HEADER)] == CHECKER_HEADER:
        return ws  # 이미 새 레이아웃

    # 구 레이아웃 감지 → 백업 후 재생성 (삭제 아님, 되돌리기 가능)
    backup = f"{TAB_CHECKER}_백업_{datetime.now().strftime('%Y%m%d')}"
    if backup in existing:
        backup += datetime.now().strftime("_%H%M%S")  # 같은 날 두 번이면 시각 추가
    ws.update_title(backup)
    print(f"    [백업] 구 '{TAB_CHECKER}' 탭 → '{backup}'로 보존")
    return _create_checker_ws(spreadsheet)


def set_checkbox(spreadsheet, ws, range_str):
    """지정 범위에 체크박스 데이터 유효성 적용"""
    sheet_id = ws.id
    m = re.match(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", range_str)
    if not m:
        return
    start_col = ord(m.group(1)) - ord("A")
    start_row = int(m.group(2)) - 1
    end_col = ord(m.group(3)) - ord("A") + 1
    end_row = int(m.group(4))

    body = {
        "requests": [{
            "setDataValidation": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": start_row,
                    "endRowIndex": end_row,
                    "startColumnIndex": start_col,
                    "endColumnIndex": end_col,
                },
                "rule": {
                    "condition": {"type": "BOOLEAN"},
                    "showCustomUi": True,
                },
            }
        }]
    }
    spreadsheet.batch_update(body)


# ────────────────────────────────────────────────
#  탭 동기화: 자사 발행리스트 → 순위 체커
# ────────────────────────────────────────────────

def normalize_date(date_str):
    """'4/10' → '2026-04-10' 형식으로 변환. 이미 YYYY-MM-DD면 그대로."""
    if not date_str:
        return date_str
    d = parse_date(date_str)
    if d:
        return d.strftime("%Y-%m-%d")
    return date_str  # 파싱 실패 시 원본


def sync_tab(ws_source, ws_internal, ws_checker):
    """자사+내부 발행리스트의 (파라미터, 키워드, 링크)를 순위 체커 탭에 동기화"""
    src_rows = ws_source.get_all_values()
    int_rows = ws_internal.get_all_values()
    chk_rows = ws_checker.get_all_values()

    # 파라미터 → (키워드, 링크, 발행일) 매핑 (자사 우선, 내부 보충)
    merged_data = {}
    for row in src_rows[1:]:
        param = _cell(row, SRC_COL_H)
        keyword = _cell(row, SRC_COL_E)
        link = _cell(row, SRC_COL_M)
        pub_date = normalize_date(_cell(row, SRC_COL_A))
        if param:
            merged_data[param] = (keyword, link, pub_date)

    for row in int_rows[1:]:
        param = _cell(row, INT_COL_H)
        keyword = _cell(row, INT_COL_E)
        link = _cell(row, INT_COL_M)
        pub_date = normalize_date(_cell(row, INT_COL_A))
        # 자사에 이미 있는 파라미터는 덮어쓰지 않음
        if param and param not in merged_data:
            merged_data[param] = (keyword, link, pub_date)

    # 체커 탭 기존 파라미터 목록
    chk_params = set()
    for row in chk_rows[1:]:
        p = _cell(row, CHK_COL_A)
        if p:
            chk_params.add(p)

    # 신규 행 추가 (15열: A~O) — 메인 8슬롯(E~L)은 빈칸
    new_rows = []
    for param, (kw, link, pub_date) in merged_data.items():
        if param not in chk_params:
            slots_blank = [""] * NUM_SLOTS          # 메인1~8
            new_rows.append([param, kw, link, False] + slots_blank
                            + ["", "", pub_date])   # 최초체크일, 상태, 발행일
    if new_rows:
        start_row = len(chk_rows) + 1
        end_row = start_row + len(new_rows) - 1
        # 행 수 부족하면 확장
        if end_row > ws_checker.row_count:
            ws_checker.add_rows(end_row - ws_checker.row_count + 100)
        ws_checker.update(
            values=new_rows,
            range_name=f"A{start_row}:{COL_LAST}{end_row}",
        )
        print(f"    동기화: {len(new_rows)}개 신규 행 추가")

    # 기존 행의 키워드/링크/발행일 업데이트 + M열 날짜 형식 정규화
    updates = []
    for idx, row in enumerate(chk_rows[1:], start=2):
        param = _cell(row, CHK_COL_A)
        if param in merged_data:
            src_kw, src_link, src_pub = merged_data[param]
            cur_kw = _cell(row, CHK_COL_B)
            cur_link = _cell(row, CHK_COL_C)
            cur_pub = _cell(row, CHK_COL_M)
            if cur_kw != src_kw or cur_link != src_link:
                updates.append({
                    "range": f"B{idx}:C{idx}",
                    "values": [[src_kw, src_link]],
                })
            # 날짜 형식이 다르면 (4/10 → 2026-04-10) 업데이트 — 발행일은 O열
            if cur_pub != src_pub:
                updates.append({
                    "range": f"{COL_PUB}{idx}",
                    "values": [[src_pub]],
                })

    if updates:
        ws_checker.batch_update(updates)
        print(f"    동기화: {len(updates)}개 행 키워드/링크 업데이트")

    if not new_rows and not updates:
        print("    동기화: 변경 없음")

    # 고아 행 감지/표시 (발행리스트에서 사라진 파라미터 → L열 마킹 + 빨간 배경)
    mark_orphan_rows(ws_checker, chk_rows, merged_data)

    # 발행일(O열) 기준 내림차순 정렬 (최신이 위로)
    sort_by_pub_date(ws_checker)

    return src_rows, int_rows


def mark_orphan_rows(ws_checker, chk_rows, merged_data):
    """순위체커 A열 파라미터가 발행리스트에 없으면 상태열(N)에 고아 표시 + 빨간 배경.
    반대로, 고아였다가 발행리스트에 다시 나타나면 표시/배경 복구."""
    cell_updates = []   # 상태열 텍스트 변경 (batch_update용)
    orphan_rows = []    # 빨간 배경 적용할 행
    recovered_rows = [] # 흰 배경 복구할 행

    for idx, row in enumerate(chk_rows[1:], start=2):
        if not row:
            continue
        param = _cell(row, CHK_COL_A)
        if not param:
            continue
        cur_status = _cell(row, CHK_COL_L)
        is_orphan = param not in merged_data
        was_marked = cur_status.startswith("고아") or cur_status == "오류: 매핑 실패"

        if is_orphan and not was_marked:
            # 새로 고아가 된 행: 상태열 비어있거나 다른 정상 상태였더라도 마킹
            # (단 정상 상태는 덮어쓰지 않음 — 발행 결과 보존)
            if not cur_status:
                cell_updates.append({
                    "range": f"{COL_STATUS}{idx}",
                    "values": [[ORPHAN_LABEL]],
                })
            orphan_rows.append(idx)
        elif is_orphan and was_marked:
            # 이미 마킹된 고아 — 라벨만 통일
            if cur_status != ORPHAN_LABEL:
                cell_updates.append({
                    "range": f"{COL_STATUS}{idx}",
                    "values": [[ORPHAN_LABEL]],
                })
            orphan_rows.append(idx)
        elif not is_orphan and was_marked:
            # 발행리스트에 다시 나타남 — 복구
            cell_updates.append({
                "range": f"{COL_STATUS}{idx}",
                "values": [[""]],
            })
            recovered_rows.append(idx)

    if cell_updates:
        ws_checker.batch_update(cell_updates)

    # 배경색은 format이라 batch가 따로. 행 수 적을 때만 적용 (과도한 API 호출 방지)
    for idx in orphan_rows:
        ws_checker.format(f"A{idx}:{COL_LAST}{idx}", LIGHT_RED)
    for idx in recovered_rows:
        ws_checker.format(f"A{idx}:{COL_LAST}{idx}", WHITE)

    if orphan_rows:
        print(f"    고아 행 감지: {len(orphan_rows)}건 (상태열 빨간색 표시)")
        for idx in orphan_rows[:10]:
            print(f"      행{idx}")
        if len(orphan_rows) > 10:
            print(f"      ... 외 {len(orphan_rows)-10}건")
    if recovered_rows:
        print(f"    고아 복구: {len(recovered_rows)}건 (발행리스트에 다시 나타남)")


def sort_by_pub_date(ws_checker):
    """순위 체커 탭을 발행일(O열) 기준 내림차순 정렬 (서식 유지)"""
    chk_rows = ws_checker.get_all_values()
    if len(chk_rows) <= 2:
        return

    sheet_id = ws_checker.id
    ws_checker.spreadsheet.batch_update({
        "requests": [{
            "sortRange": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 1,  # 헤더 제외
                    "startColumnIndex": 0,
                    "endColumnIndex": NUM_COLS,
                },
                "sortSpecs": [{
                    "dimensionIndex": CHK_COL_M,  # O열(발행일)
                    "sortOrder": "DESCENDING",
                }],
            }
        }]
    })
    print("    정렬: 발행일 최신순")


# ────────────────────────────────────────────────
#  Selenium 브라우저
# ────────────────────────────────────────────────

def create_driver():
    """headless Chrome 생성 (자동화 탐지 우회 포함)"""
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )

    chrome_bin = os.environ.get("CHROME_BIN")
    if chrome_bin:
        opts.binary_location = chrome_bin
        driver = webdriver.Chrome(options=opts)
    else:
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=opts,
        )
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"},
    )
    driver.implicitly_wait(5)
    return driver


# ────────────────────────────────────────────────
#  유틸리티
# ────────────────────────────────────────────────

def _cell(row, col_idx):
    """행 데이터에서 안전하게 값 가져오기"""
    return row[col_idx].strip() if len(row) > col_idx else ""


def clean_keyword(kw: str) -> str:
    """키워드에서 괄호+내용 제거 — '강세일(2)' → '강세일'"""
    return re.sub(r"\(.*?\)", "", kw).strip()


def normalize(url: str) -> str:
    """프로토콜·www·m.·끝 슬래시 제거 후 소문자"""
    url = re.sub(r"^https?://", "", url)
    url = re.sub(r"^(www\.|m\.)", "", url)
    return url.rstrip("/").lower()


def is_match(result_url: str, target_url: str) -> bool:
    """타겟 URL이 결과 URL에 포함되는지 판별"""
    return normalize(target_url) in normalize(result_url)


def is_post_url(url: str) -> bool:
    """네이버 블로그/카페 '실제 글' 주소인지 판별 (대문/글ID 없는 링크 걸러냄).
    blog.naver.com/<블로그ID>/<글ID> 처럼 path가 2개 이상이어야 글로 인정.
    대문(blog.naver.com/vsbears)은 path 1개 → 제외. MAIN_EXTRACT_JS의 기준과 동일."""
    u = (url or "").strip()
    if not u:
        return False
    try:
        path = urllib.parse.urlparse(u if "://" in u else "https://" + u).path
    except Exception:
        return False
    parts = [p for p in path.split("/") if p]
    if "blog.naver.com" in u or "cafe.naver.com" in u:
        return len(parts) >= 2          # 대문(/vsbears)=1 → 제외, /vsbears/2243...=2 → 통과
    if "kin.naver.com" in u:
        return "docId=" in u
    return True                          # 그 외 도메인은 그대로 통과


def scroll_full(driver, max_iter=10, pause=1.5):
    """더 이상 늘어나지 않을 때까지 스크롤"""
    prev = driver.execute_script("return document.body.scrollHeight")
    for _ in range(max_iter):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(pause)
        curr = driver.execute_script("return document.body.scrollHeight")
        if curr == prev:
            break
        prev = curr


def scroll_times(driver, n=3, pause=2.0):
    """고정 n회 스크롤 (무한스크롤 대응)"""
    for _ in range(n):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(pause)


def parse_rank(val: str):
    """'3위' → 3, '순위 밖' → None"""
    m = re.search(r'(\d+)', val)
    return int(m.group(1)) if m else None


def parse_date(date_str):
    """다양한 날짜 형식 파싱 → date 객체. 실패 시 None"""
    if not date_str:
        return None
    # "2026-04-09" 형식
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        pass
    # "4/7" 형식 (월/일) → 올해 기준, 미래면 전년도
    try:
        parts = date_str.split("/")
        if len(parts) == 2:
            month, day = int(parts[0]), int(parts[1])
            today = datetime.now().date()
            d = datetime(today.year, month, day).date()
            if d > today:
                d = datetime(today.year - 1, month, day).date()
            return d
    except (ValueError, IndexError):
        pass
    return None


# ── 메인 슬롯(8개) 헬퍼 + 일정 기반 슬롯 결정 ──

def _slot_values(row):
    """행에서 메인1~8 슬롯 값 8개를 리스트로 반환."""
    return [_cell(row, CHK_SLOT_START + i) for i in range(NUM_SLOTS)]


def _last_filled_before(vals, i):
    """index i 이전(0..i-1)에서 가장 최근에 채워진 슬롯 값. 없으면 None.
    (순위 상승 노란색 비교용 직전값)"""
    for j in range(i - 1, -1, -1):
        if vals[j]:
            return vals[j]
    return None


def due_slot(row, today=None):
    """발행일 기준 일정(SCHEDULE_DAYS)으로 지금 채워야 할 슬롯 결정.
    반환 (slot_name, prev_main_str) 또는 (None, None).
    - 경과 달력일 >= 목표일이고 아직 빈 '가장 이른' 슬롯을 고른다(누락분 따라잡기).
    - 1일차(첫 목표) 전이거나, 도래한 슬롯이 모두 차있으면 None."""
    if today is None:
        today = datetime.now().date()
    pub = parse_date(_cell(row, CHK_COL_M))  # 발행일(O열)
    if pub is None:
        return None, None
    elapsed = (today - pub).days
    if elapsed < SCHEDULE_DAYS[0]:
        return None, None  # 아직 1일차 전
    vals = _slot_values(row)
    for i, target in enumerate(SCHEDULE_DAYS):
        if not vals[i] and elapsed >= target:
            return f"slot{i+1}", _last_filled_before(vals, i)
    return None, None


# ────────────────────────────────────────────────
#  검색 결과 추출 (JavaScript)
# ────────────────────────────────────────────────

MAIN_EXTRACT_JS = """
    var pack = document.getElementById('main_pack') || document.body;
    var sections = pack.querySelectorAll('.api_subject_bx');
    var targets = ['blog.naver.com', 'cafe.naver.com', 'kin.naver.com'];
    var results = [];

    for (var s = 0; s < sections.length; s++) {
        var sec = sections[s];

        var titleEl = sec.querySelector('.tit_area .tit, .api_title, h2, .title_area .tit');
        var titleText = titleEl ? titleEl.textContent.trim() : '';
        if (titleText.indexOf('AI') !== -1) continue;

        var cls = (sec.className || '').toLowerCase();
        var daa = sec.getAttribute('data-ad-area');
        if (daa !== null || cls.indexOf('ad_area') !== -1 || cls.indexOf('type_ad') !== -1 ||
            cls.indexOf('sponsored') !== -1 || cls.indexOf('powerlink') !== -1) continue;

        var links = sec.querySelectorAll('a[href]');
        var found = null;
        for (var i = 0; i < links.length; i++) {
            var href = links[i].href;
            if (!href || href.indexOf('http') !== 0) continue;

            var matched = false;
            for (var j = 0; j < targets.length; j++) {
                if (href.indexOf(targets[j]) !== -1) { matched = true; break; }
            }
            if (!matched) continue;

            var pathParts = new URL(href).pathname.split('/').filter(function(p){return p;});
            if (href.indexOf('blog.naver.com') !== -1 && pathParts.length < 2) continue;
            if (href.indexOf('cafe.naver.com') !== -1 && pathParts.length < 2) continue;
            if (href.indexOf('kin.naver.com') !== -1 && href.indexOf('docId=') === -1) continue;

            found = href;
            break;
        }
        if (found) results.push([found, titleText || '기타']);
    }
    return results;
"""


# ────────────────────────────────────────────────
#  순위 체크 (메인 통합검색만)
# ────────────────────────────────────────────────

def check_main(driver, keyword, target_url):
    """통합검색(메인) - 블로그/카페/지식인만 카운트, 광고 제외"""
    driver.get(
        "https://search.naver.com/search.naver?query="
        + urllib.parse.quote(keyword)
    )
    time.sleep(3)
    scroll_full(driver)
    time.sleep(1)

    results = driver.execute_script(MAIN_EXTRACT_JS) or []
    print(f"           [디버그] 메인 결과 {len(results)}개:")
    for i, item in enumerate(results[:10], 1):
        u = item[0] if isinstance(item, list) else item
        sec = item[1] if isinstance(item, list) and len(item) > 1 else ""
        print(f"             {i}. [{sec}] {u}")

    for rank, item in enumerate(results, start=1):
        u = item[0] if isinstance(item, list) else item
        if is_match(u, target_url):
            return rank
    return None


# ────────────────────────────────────────────────
#  슬롯 결정 + 결과 기록
# ────────────────────────────────────────────────

def determine_slot(row):
    """수동/기본: 다음 빈 메인 슬롯 결정. 8슬롯 다 차있으면 None.
    오늘 이미 체크한 슬롯이 있으면 마지막 슬롯 덮어쓰기.
    반환: (슬롯명, 직전 메인 순위) 또는 (None, None)
    """
    vals = _slot_values(row)  # 메인1~8

    # 오늘 이미 체크했으면 마지막 채운 슬롯 덮어쓰기
    status = _cell(row, CHK_COL_L)  # "완료 04/10 11:02" 형식
    today_str = datetime.now().strftime("%m/%d")
    if status.startswith("완료") and today_str in status:
        filled = [k for k, v in enumerate(vals) if v]
        if filled:
            last = filled[-1]
            return f"slot{last+1}", _last_filled_before(vals, last)

    # 다음 빈 슬롯
    for k, v in enumerate(vals):
        if not v:
            return f"slot{k+1}", _last_filled_before(vals, k)
    return None, None


def write_result(ws_source, ws_internal, ws_checker, spreadsheet,
                 source_type, target_row_num, chk_row_num,
                 main_rank, slot, prev_main_str):
    """순위 체커 탭(메인 슬롯) + 원본 탭(J열) 기록 + 노란색(순위 상승).
    블탭은 더 이상 기록하지 않으며, 원본 탭 블탭 표시열(자사 T/내부 Q)은 비운다.
    source_type: "source"(자사) | "internal"(내부)
    """
    main_str = f"{main_rank}위" if main_rank is not None else "순위 밖"
    main_col = SLOT_COLS[slot]   # 단일 열 (예: slot2 → "F")

    # ── 순위 체커 탭: 메인 슬롯 기록 ──
    ws_checker.update(values=[[main_str]], range_name=f"{main_col}{chk_row_num}")

    # 최초체크일 기록 (slot1일 때만)
    if slot == "slot1":
        today_str = datetime.now().strftime("%Y-%m-%d")
        ws_checker.update(values=[[today_str]], range_name=f"{COL_FIRST}{chk_row_num}")

    # ── 순위 상승 비교 (직전 채워진 슬롯과 비교) → 노란색 ──
    if prev_main_str:
        prev_main = parse_rank(prev_main_str)
        # 순위 상승 = 숫자가 줄어들거나, 순위 밖 → 순위 진입
        main_up = (main_rank is not None and
                   (prev_main is None or main_rank < prev_main))
        # 기존 노란색 초기화 후 상승 시에만 칠함
        ws_checker.format(f"{main_col}{chk_row_num}", LIGHT_YELLOW if main_up else WHITE)
        if main_up:
            print(f"           메인 순위 상승! ({prev_main_str} → {main_str}) 노란색")

    # ── 원본 탭: J열(메인 순위)만 기록 + 블탭 표시열 클리어 ──
    if source_type == "internal":
        target_ws = ws_internal
        blog_flag_col = "Q"
        label = "내부"
    else:
        target_ws = ws_source
        blog_flag_col = "T"
        label = "자사"

    # 메인 순위가 있으면 J열 기록, 옛 블탭 표시는 항상 비움
    if main_rank is not None:
        target_ws.update(values=[[main_str]], range_name=f"J{target_row_num}")
    target_ws.update(values=[[""]], range_name=f"{blog_flag_col}{target_row_num}")

    # 원본 탭 J열 순위 상승 시 노란색
    if prev_main_str:
        prev_j = parse_rank(prev_main_str)
        j_up = (main_rank is not None and
                (prev_j is None or main_rank < prev_j))
        target_ws.format(f"J{target_row_num}", LIGHT_YELLOW if j_up else WHITE)

    return main_str, label


def build_param_row_map(src_rows, int_rows):
    """파라미터값 → (source_type, 행번호) 매핑. 자사 우선, 내부 보충"""
    param_map = {}
    for idx, row in enumerate(src_rows[1:], start=2):
        param = _cell(row, SRC_COL_H)
        if param:
            param_map[param] = ("source", idx)
    for idx, row in enumerate(int_rows[1:], start=2):
        param = _cell(row, INT_COL_H)
        if param and param not in param_map:
            param_map[param] = ("internal", idx)
    return param_map


# ────────────────────────────────────────────────
#  행 처리
# ────────────────────────────────────────────────

def process_rows(ws_source, ws_internal, ws_checker, spreadsheet, driver, targets, param_map):
    """대상 행들의 순위 체크 + 결과 기록"""
    for i, (chk_row_num, param, kw, link, slot, prev_main, row_data) in enumerate(targets):
        mapping = param_map.get(param)
        if not mapping:
            print(f"\n  [{i+1}/{len(targets)}] {param} — 자사/내부 발행리스트에서 행 못 찾음, 스킵")
            ws_checker.update(values=[[ORPHAN_LABEL]], range_name=f"{COL_STATUS}{chk_row_num}")
            ws_checker.format(f"A{chk_row_num}:{COL_LAST}{chk_row_num}", LIGHT_RED)
            continue
        source_type, target_row_num = mapping

        if not kw or not link:
            print(f"\n  [{i+1}/{len(targets)}] {param} — 키워드 또는 링크 없음, 스킵")
            ws_checker.update(values=[["스킵(데이터 없음)"]], range_name=f"{COL_STATUS}{chk_row_num}")
            continue

        # 글ID 없는 대문 URL(예: .../vsbears)이면 순위 검색 전에 차단 — 슬롯 비운 채 스킵
        # (타겟 빌더에서 이미 걸러지므로 사실상 안 타는 안전망)
        if not is_post_url(link):
            print(f"\n  [{i+1}/{len(targets)}] {param} — 글 주소 미확정(대문 URL), 스킵")
            ws_checker.update(values=[["대기(글 주소 미확정)"]], range_name=f"{COL_STATUS}{chk_row_num}")
            continue

        slot_label = slot.replace("slot", "")
        origin_label = "내부" if source_type == "internal" else "자사"
        print(f"\n  [{i+1}/{len(targets)}] [{origin_label}] 키워드: {kw}")
        print(f"           타겟: {link}")
        print(f"           기록 위치: 메인{slot_label}")

        try:
            # 괄호 제거된 키워드로 검색
            search_kw = clean_keyword(kw)

            # 메인(통합검색) 체크 — 메인만 본다
            print("           메인 검색 중...", end=" ", flush=True)
            main_rank = check_main(driver, search_kw, link)
            main_str = f"{main_rank}위" if main_rank else "순위 밖"
            print(main_str)

            write_result(
                ws_source, ws_internal, ws_checker, spreadsheet,
                source_type, target_row_num, chk_row_num,
                main_rank, slot, prev_main,
            )

            # 상태 업데이트
            now = datetime.now().strftime("%m/%d %H:%M")
            ws_checker.update(values=[[f"완료 {now}"]], range_name=f"{COL_STATUS}{chk_row_num}")

        except Exception as e:
            print(f"\n           [!] 오류: {e}")
            ws_checker.update(values=[[f"오류: {e}"]], range_name=f"{COL_STATUS}{chk_row_num}")
            try:
                driver.quit()
            except Exception:
                pass
            driver = create_driver()

        time.sleep(2)

    return driver


# ────────────────────────────────────────────────
#  대상 행 수집
# ────────────────────────────────────────────────

def has_any_checked(chk_rows):
    """D열에 체크된 행이 하나라도 있는지 확인 + 체크 해제 대상 반환"""
    clear_rows = []
    for idx, row in enumerate(chk_rows[1:], start=2):
        val = _cell(row, CHK_COL_D).strip().upper()
        if val in ("TRUE", "O", "V", "Y", "1", "ㅇ"):
            clear_rows.append(idx)
    return len(clear_rows) > 0, clear_rows


def get_checked_targets(chk_rows, clear_rows):
    """수동 체크된 행 중 빈 슬롯 있는 행만 (일정 필터 없음 — 다음 빈 슬롯에 기록)"""
    checked_set = set(clear_rows)
    targets = []
    for idx, row in enumerate(chk_rows[1:], start=2):
        if idx not in checked_set:
            continue
        param = _cell(row, CHK_COL_A)
        kw = _cell(row, CHK_COL_B)
        link = _cell(row, CHK_COL_C)
        # 글ID 없는 대문 URL(예: .../vsbears)은 건너뜀 — 오탐 방지 + 슬롯 보존
        if not param or not kw or not link or not is_post_url(link):
            continue
        slot, prev_main = determine_slot(row)
        if slot is None:
            continue
        targets.append((idx, param, kw, link, slot, prev_main, row))
    return targets


def get_cron_targets(chk_rows):
    """일정 도래(발행일 기준 1·4·7…21일차) + 빈 슬롯 있는 행만"""
    targets = []
    today = datetime.now().date()

    for idx, row in enumerate(chk_rows[1:], start=2):
        param = _cell(row, CHK_COL_A)
        kw = _cell(row, CHK_COL_B)
        link = _cell(row, CHK_COL_C)
        # 글ID 없는 대문 URL(예: .../vsbears)은 건너뜀 — 오탐 방지 + 슬롯 보존
        # (발행 자동화가 M열에 실제 글 주소를 채우면 다음 실행 sync가 C열을 갱신 → 그때 정상 체크)
        if not param or not kw or not link or not is_post_url(link):
            continue

        # 발행일 경과일이 일정에 도달한 가장 이른 빈 슬롯
        slot, prev_main = due_slot(row, today=today)
        if slot is None:
            continue  # 아직 도래 안 함 / 8슬롯 다 참 / 발행일 없음

        targets.append((idx, param, kw, link, slot, prev_main, row))

    return targets


# ────────────────────────────────────────────────
#  실행 모드
# ────────────────────────────────────────────────

def run_once(mode="manual"):
    """1회 실행: 동기화 → 대상 행 처리"""
    print("=" * 50)
    print("  네이버 순위 체커 (통합)")
    print(f"  모드: {mode}")
    print("=" * 50)

    print("\n[1] Google Sheets 연결 중...")
    spreadsheet, ws_source, ws_internal, ws_checker = connect_sheets()

    print("\n[2] 탭 동기화...")
    src_rows, int_rows = sync_tab(ws_source, ws_internal, ws_checker)

    # 체커 탭 다시 읽기 (동기화 후)
    chk_rows = ws_checker.get_all_values()

    if mode == "cron":
        targets = get_cron_targets(chk_rows)
        total_due = len(targets)
        if total_due > MAX_CRON_PER_RUN:
            targets = targets[:MAX_CRON_PER_RUN]   # 최신순 → 새 글부터, 나머지는 다음 실행
            print(f"    크론 모드: 일정 도래 {total_due}개 중 상한 {MAX_CRON_PER_RUN}개 처리"
                  f" (나머지 {total_due - MAX_CRON_PER_RUN}개는 다음 실행에서)")
        else:
            print(f"    크론 모드: 일정 도래(1·4·7…21일차) 대상 {total_due}개")
    else:
        # 체크된 행만 대상 (일정 필터 없이 다음 빈 슬롯에 기록)
        triggered, clear_rows = has_any_checked(chk_rows)
        if not triggered:
            print("    처리 대상이 없습니다. D열에 체크해주세요.")
            return
        # 체크 해제
        updates = [{"range": f"D{r}", "values": [[False]]} for r in clear_rows]
        ws_checker.batch_update(updates)
        # 체크된 행만 대상 (일정 필터 없이 다음 빈 슬롯에 기록)
        targets = get_checked_targets(chk_rows, clear_rows)

    if not targets:
        print("    처리 대상이 없습니다.")
        return

    print(f"    {len(targets)}개 처리 대상")

    param_map = build_param_row_map(src_rows, int_rows)

    print("\n[3] 브라우저 준비 중...")
    driver = create_driver()
    print("    준비 완료!")

    print("\n[4] 순위 검색 시작")
    print("-" * 50)

    try:
        driver = process_rows(ws_source, ws_internal, ws_checker, spreadsheet,
                              driver, targets, param_map)
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    print("\n" + "=" * 50)
    print("  모든 키워드 처리 완료!")
    print("=" * 50)


def watch(interval=60):
    """시트를 주기적으로 감시하며 체크박스 체크 시 자동 실행 (기본 60초)"""
    print("=" * 50)
    print("  네이버 순위 체커 (통합) - 감시 모드")
    print(f"  {interval}초마다 시트를 확인합니다.")
    print("  순위 체커 탭 D열에 체크하면 자동 실행!")
    print("  종료: Ctrl+C")
    print("=" * 50)

    driver = None
    # 운영 시간: 10시 ~ 14시 (KST)
    OP_START_HOUR = 10
    OP_END_HOUR = 14

    try:
        while True:
            # 운영 시간 종료 → watch 모드 종료
            if datetime.now().hour >= OP_END_HOUR:
                print(f"\n\n  운영 시간 종료 ({OP_END_HOUR}시) — watch 모드 종료")
                break

            try:
                spreadsheet, ws_source, ws_internal, ws_checker = connect_sheets()
                src_rows, int_rows = sync_tab(ws_source, ws_internal, ws_checker)
                chk_rows = ws_checker.get_all_values()
            except Exception as e:
                now = datetime.now().strftime("%H:%M:%S")
                print(f"\n  [{now}] 시트 연결 오류: {e}")
                time.sleep(60)
                continue

            triggered, clear_rows = has_any_checked(chk_rows)

            if not triggered:
                now = datetime.now().strftime("%H:%M:%S")
                print(f"\r  [{now}] 대기 중... (체크된 행 없음)", end="", flush=True)
                time.sleep(interval)
                continue

            # 체크 해제
            updates = [{"range": f"D{r}", "values": [[False]]} for r in clear_rows]
            ws_checker.batch_update(updates)

            # 체크 = 트리거, 실제 대상은 일정 도래(1·4·7…21일차) 전체
            targets = get_cron_targets(chk_rows)
            if not targets:
                print(f"\n\n  >> 체크 감지했으나 처리할 대상 없음 (모두 8슬롯 완료/일정 전)")
                time.sleep(interval)
                continue

            print(f"\n\n  >> 체크 감지! 일정 도래 {len(targets)}개 처리 시작")

            param_map = build_param_row_map(src_rows, int_rows)

            if driver is None:
                print("  브라우저 준비 중...")
                driver = create_driver()
                print("  준비 완료!")

            driver = process_rows(ws_source, ws_internal, ws_checker, spreadsheet,
                                  driver, targets, param_map)
            print("\n  처리 완료! 다시 대기 중...")

    except KeyboardInterrupt:
        print("\n\n  감시 모드 종료!")
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "main"
    if cmd == "watch":
        watch()
    elif cmd == "cron":
        run_once(mode="cron")
    else:
        run_once(mode="manual")
