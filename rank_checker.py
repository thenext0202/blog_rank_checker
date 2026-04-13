#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
rank_checker.py - 순위 체커 통합 (공통 시트 연동)

공통 시트의 '순위 체커' 탭에서 체크박스 트리거 →
네이버 메인(통합검색) 순위 우선 확인 → 없으면 블로그탭 →
결과를 자사 발행리스트 J열에 기록, 블로그탭이면 T열에 "블탭"

순위 체커 탭 구조:
  A: 파라미터값 | B: 키워드 | C: 링크 | D: 실행(체크박스)
  E: 메인1 | F: 블탭1 | G: 메인2 | H: 블탭2 | I: 메인3 | J: 블탭3
  K: 최초체크일 | L: 상태

실행 모드:
  python rank_checker.py          # 1회 실행 (체크된 행만)
  python rank_checker.py watch    # 60초 감시 모드 (로컬용)
  python rank_checker.py cron     # 3영업일 이내 행 자동 (Railway 크론용)
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
TAB_CHECKER    = "순위 체커"
CRED_FILE      = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "..", "manuscript_generator", "credentials.json")
BLOG_TAB_LIMIT = 10  # 블로그탭 순위 체크 상한

# 자사 발행리스트 열 인덱스 (0-based)
SRC_COL_A = 0   # 발행일 (월/일)
SRC_COL_E = 4   # 키워드
SRC_COL_H = 7   # 파라미터값 (조인키)
SRC_COL_J = 9   # 순위 결과
SRC_COL_M = 12  # 링크 (타겟 URL)
SRC_COL_T = 19  # 블탭 표시

# 순위 체커 탭 열 인덱스 (0-based)
CHK_COL_A = 0   # 파라미터값
CHK_COL_B = 1   # 키워드
CHK_COL_C = 2   # 링크
CHK_COL_D = 3   # 실행 (체크박스)
CHK_COL_E = 4   # 메인1
CHK_COL_F = 5   # 블탭1
CHK_COL_G = 6   # 메인2
CHK_COL_H = 7   # 블탭2
CHK_COL_I = 8   # 메인3
CHK_COL_J = 9   # 블탭3
CHK_COL_K = 10  # 최초체크일
CHK_COL_L = 11  # 상태
CHK_COL_M = 12  # 발행일 (자사 발행리스트 A열)

# 노란색 배경 (순위 변동 표시)
LIGHT_YELLOW = {"backgroundColor": {"red": 1, "green": 1, "blue": 0.8}}
WHITE = {"backgroundColor": {"red": 1, "green": 1, "blue": 1}}
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# ────────────────────────────────────────────────
#  Google Sheets 연결
# ────────────────────────────────────────────────

def connect_sheets():
    """공통 시트 연결 → (spreadsheet, ws_source, ws_checker) 반환"""
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
    ws_checker = ensure_checker_tab(spreadsheet)
    return spreadsheet, ws_source, ws_checker


def ensure_checker_tab(spreadsheet):
    """순위 체커 탭이 없으면 생성, 있으면 반환"""
    existing = [ws.title for ws in spreadsheet.worksheets()]
    if TAB_CHECKER in existing:
        return spreadsheet.worksheet(TAB_CHECKER)

    ws = spreadsheet.add_worksheet(title=TAB_CHECKER, rows=1000, cols=13)
    ws.update(
        values=[["파라미터값", "키워드", "링크", "실행",
                 "메인1", "블탭1", "메인2", "블탭2", "메인3", "블탭3",
                 "최초체크일", "상태", "발행일"]],
        range_name="A1:M1",
    )
    # D열 체크박스
    set_checkbox(spreadsheet, ws, "D2:D1000")
    print(f"    '{TAB_CHECKER}' 탭 생성 완료")
    return ws


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


def sync_tab(ws_source, ws_checker):
    """자사 발행리스트의 (파라미터, 키워드, 링크)를 순위 체커 탭에 동기화"""
    src_rows = ws_source.get_all_values()
    chk_rows = ws_checker.get_all_values()

    # 소스에서 유효한 행 추출 (H열 파라미터 있는 행만)
    src_data = {}
    for row in src_rows[1:]:
        param = _cell(row, SRC_COL_H)
        keyword = _cell(row, SRC_COL_E)
        link = _cell(row, SRC_COL_M)
        pub_date = normalize_date(_cell(row, SRC_COL_A))  # YYYY-MM-DD로 변환
        if param:
            src_data[param] = (keyword, link, pub_date)

    # 체커 탭 기존 파라미터 목록
    chk_params = set()
    for row in chk_rows[1:]:
        p = _cell(row, CHK_COL_A)
        if p:
            chk_params.add(p)

    # 신규 행 추가 (13열: A~M)
    new_rows = []
    for param, (kw, link, pub_date) in src_data.items():
        if param not in chk_params:
            new_rows.append([param, kw, link, False,
                             "", "", "", "", "", "", "", "", pub_date])

    if new_rows:
        start_row = len(chk_rows) + 1
        end_row = start_row + len(new_rows) - 1
        # 행 수 부족하면 확장
        if end_row > ws_checker.row_count:
            ws_checker.add_rows(end_row - ws_checker.row_count + 100)
        ws_checker.update(
            values=new_rows,
            range_name=f"A{start_row}:M{end_row}",
        )
        print(f"    동기화: {len(new_rows)}개 신규 행 추가")

    # 기존 행의 키워드/링크/발행일 업데이트 + M열 날짜 형식 정규화
    updates = []
    for idx, row in enumerate(chk_rows[1:], start=2):
        param = _cell(row, CHK_COL_A)
        if param in src_data:
            src_kw, src_link, src_pub = src_data[param]
            cur_kw = _cell(row, CHK_COL_B)
            cur_link = _cell(row, CHK_COL_C)
            cur_pub = _cell(row, CHK_COL_M)
            if cur_kw != src_kw or cur_link != src_link:
                updates.append({
                    "range": f"B{idx}:C{idx}",
                    "values": [[src_kw, src_link]],
                })
            # 날짜 형식이 다르면 (4/10 → 2026-04-10) 업데이트
            if cur_pub != src_pub:
                updates.append({
                    "range": f"M{idx}",
                    "values": [[src_pub]],
                })

    if updates:
        ws_checker.batch_update(updates)
        print(f"    동기화: {len(updates)}개 행 키워드/링크 업데이트")

    if not new_rows and not updates:
        print("    동기화: 변경 없음")

    # 발행일(M열) 기준 내림차순 정렬 (최신이 위로)
    sort_by_pub_date(ws_checker)

    return src_rows


def sort_by_pub_date(ws_checker):
    """순위 체커 탭을 발행일(M열) 기준 내림차순 정렬 (서식 유지)"""
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
                    "endColumnIndex": 13,
                },
                "sortSpecs": [{
                    "dimensionIndex": CHK_COL_M,  # M열(발행일)
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


def get_business_days_ago(n, today=None):
    """오늘로부터 n영업일 전 날짜 반환 (주말 건너뜀)"""
    if today is None:
        today = datetime.now().date()
    count = 0
    d = today
    while count < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:  # 월~금
            count += 1
    return d


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


def is_within_check_range(date_str, today=None):
    """발행일이 체크 대상 범위인지 (어제부터 영업일 3일 거슬러)"""
    check_date = parse_date(date_str)
    if check_date is None:
        return False
    if today is None:
        today = datetime.now().date()
    # 어제부터 영업일 3일 전까지
    end = today - timedelta(days=1)  # 어제
    start = get_business_days_ago(3, today)
    return start <= check_date <= end


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

BLOG_EXTRACT_JS = """
    var results = [];

    var container = document.querySelector('.fds-ugc-single-intention-item-list-tab');
    if (container) {
        var children = container.children;
        for (var i = 0; i < children.length; i++) {
            var child = children[i];

            var isAd = false;
            var el = child;
            while (el && el !== container) {
                var cls = (el.className || '').toLowerCase();
                var daa = el.getAttribute('data-ad-area');
                if (daa !== null || cls.indexOf('ad_area') !== -1 || cls.indexOf('type_ad') !== -1 ||
                    cls.indexOf('sponsored') !== -1 || cls.indexOf('powerlink') !== -1 ||
                    cls.indexOf('brand_ad') !== -1 || cls.indexOf('spw_recom') !== -1) {
                    isAd = true;
                    break;
                }
                el = el.parentElement;
            }
            if (isAd) continue;

            var blogLinks = child.querySelectorAll('a[href*="blog.naver.com"]');
            for (var j = 0; j < blogLinks.length; j++) {
                var href = blogLinks[j].href;
                if (!href || href.indexOf('http') !== 0) continue;
                var pathParts = new URL(href).pathname.split('/').filter(function(p){return p;});
                if (pathParts.length < 2) continue;
                results.push(href);
                break;
            }
        }
        return results;
    }

    var allLinks = document.querySelectorAll('a[href*="blog.naver.com"]');
    var seen = {};
    for (var i = 0; i < allLinks.length; i++) {
        var href = allLinks[i].href;
        if (!href || href.indexOf('http') !== 0) continue;
        var pathParts = new URL(href).pathname.split('/').filter(function(p){return p;});
        if (pathParts.length < 2) continue;
        var norm = href.toLowerCase();
        if (seen[norm]) continue;
        seen[norm] = true;

        var el = allLinks[i];
        var isAd = false;
        while (el) {
            var cls = (el.className || '').toLowerCase();
            var daa = el.getAttribute('data-ad-area');
            if (daa !== null || cls.indexOf('ad_area') !== -1 || cls.indexOf('type_ad') !== -1 ||
                cls.indexOf('sponsored') !== -1 || cls.indexOf('powerlink') !== -1 ||
                cls.indexOf('brand_ad') !== -1 || cls.indexOf('spw_recom') !== -1) {
                isAd = true;
                break;
            }
            el = el.parentElement;
        }
        if (isAd) continue;

        results.push(href);
    }
    return results;
"""


# ────────────────────────────────────────────────
#  순위 체크
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


def check_blog(driver, keyword, target_url):
    """블로그탭 - BLOG_TAB_LIMIT위까지만 체크"""
    driver.get(
        "https://search.naver.com/search.naver?ssc=tab.blog.all&sm=tab_jum&query="
        + urllib.parse.quote(keyword)
    )
    time.sleep(3)
    scroll_times(driver, n=2, pause=2.0)
    time.sleep(1)

    results = driver.execute_script(BLOG_EXTRACT_JS) or []
    print(f"           [디버그] 블로그탭 결과 {len(results)}개:")
    for i, u in enumerate(results[:BLOG_TAB_LIMIT], 1):
        print(f"             {i}. {u}")

    for rank, url in enumerate(results, start=1):
        if rank > BLOG_TAB_LIMIT:
            break
        if is_match(url, target_url):
            return rank
    return None


# ────────────────────────────────────────────────
#  슬롯 결정 + 결과 기록
# ────────────────────────────────────────────────

def determine_slot(row):
    """행 데이터를 보고 기록할 슬롯 결정. 모두 차있으면 None.
    오늘 이미 체크한 슬롯이 있으면 같은 슬롯 덮어쓰기.
    반환: (슬롯명, 이전 메인 순위, 이전 블탭 순위) 또는 (None, None, None)
    """
    e = _cell(row, CHK_COL_E)  # 메인1
    f = _cell(row, CHK_COL_F)  # 블탭1
    g = _cell(row, CHK_COL_G)  # 메인2
    h = _cell(row, CHK_COL_H)  # 블탭2
    i = _cell(row, CHK_COL_I)  # 메인3
    j = _cell(row, CHK_COL_J)  # 블탭3

    # 오늘 이미 체크했으면 같은 슬롯 덮어쓰기
    status = _cell(row, CHK_COL_L)  # "완료 04/10 11:02" 형식
    today_str = datetime.now().strftime("%m/%d")
    if status.startswith("완료") and today_str in status:
        # 마지막으로 기록된 슬롯 찾기 (가장 뒤에 값이 있는 슬롯)
        if i or j:
            return "slot3", g, h
        elif g or h:
            return "slot2", e, f
        elif e or f:
            return "slot1", None, None

    if not e and not f:
        return "slot1", None, None
    elif not g and not h:
        return "slot2", e, f
    elif not i and not j:
        return "slot3", g, h
    else:
        return None, None, None


# 슬롯 → (메인 열, 블탭 열) 매핑
SLOT_COLS = {
    "slot1": ("E", "F"),
    "slot2": ("G", "H"),
    "slot3": ("I", "J"),
}


def write_result(ws_source, ws_checker, spreadsheet,
                 src_row_num, chk_row_num,
                 main_rank, blog_rank, slot,
                 prev_main_str, prev_blog_str):
    """순위 체커 탭(메인+블탭) + 자사 발행리스트(J열+T열) 기록 + 노란색"""
    main_str = f"{main_rank}위" if main_rank is not None else "순위 밖"
    blog_str = f"{blog_rank}위" if blog_rank is not None else "순위 밖"

    main_col, blog_col = SLOT_COLS[slot]

    # ── 순위 체커 탭: 메인 + 블탭 기록 ──
    ws_checker.update(
        values=[[main_str, blog_str]],
        range_name=f"{main_col}{chk_row_num}:{blog_col}{chk_row_num}",
    )

    # 최초체크일 기록 (slot1일 때만)
    if slot == "slot1":
        today_str = datetime.now().strftime("%Y-%m-%d")
        ws_checker.update(values=[[today_str]], range_name=f"K{chk_row_num}")

    # ── 순위 상승 비교 (slot2, slot3) → 노란색 ──
    if slot in ("slot2", "slot3") and prev_main_str:
        prev_main = parse_rank(prev_main_str)
        prev_blog = parse_rank(prev_blog_str)

        # 순위 상승 = 숫자가 줄어들거나, 순위 밖 → 순위 진입
        main_up = (main_rank is not None and
                   (prev_main is None or main_rank < prev_main))
        blog_up = (blog_rank is not None and
                   (prev_blog is None or blog_rank < prev_blog))

        # 기존 노란색 초기화
        ws_checker.format(f"{main_col}{chk_row_num}:{blog_col}{chk_row_num}", WHITE)

        if main_up:
            ws_checker.format(f"{main_col}{chk_row_num}", LIGHT_YELLOW)
            print(f"           메인 순위 상승! ({prev_main_str} → {main_str}) 노란색")
        if blog_up:
            ws_checker.format(f"{blog_col}{chk_row_num}", LIGHT_YELLOW)
            print(f"           블탭 순위 상승! ({prev_blog_str} → {blog_str}) 노란색")

    # ── 자사 발행리스트: J열(순위) + T열(블탭) ──
    # 메인 우선 → 없으면 블로그탭 → 둘 다 없으면 기입 안 함
    if main_rank is not None:
        ws_source.update(values=[[main_str]], range_name=f"J{src_row_num}")
        ws_source.update(values=[[""]], range_name=f"T{src_row_num}")
    elif blog_rank is not None:
        ws_source.update(values=[[blog_str]], range_name=f"J{src_row_num}")
        ws_source.update(values=[["블탭"]], range_name=f"T{src_row_num}")

    # 자사 발행리스트 J열 순위 상승 시 노란색
    if slot in ("slot2", "slot3") and prev_main_str:
        prev_j = parse_rank(prev_main_str) if parse_rank(prev_main_str) else parse_rank(prev_blog_str)
        curr_j = main_rank if main_rank is not None else blog_rank
        # 순위 상승일 때만 노란색
        j_up = (curr_j is not None and
                (prev_j is None or curr_j < prev_j))
        ws_source.format(f"J{src_row_num}", LIGHT_YELLOW if j_up else WHITE)

    return main_str, blog_str


def build_param_row_map(src_rows):
    """자사 발행리스트에서 파라미터값 → 행번호 매핑"""
    param_map = {}
    for idx, row in enumerate(src_rows[1:], start=2):
        param = _cell(row, SRC_COL_H)
        if param:
            param_map[param] = idx
    return param_map


# ────────────────────────────────────────────────
#  행 처리
# ────────────────────────────────────────────────

def process_rows(ws_source, ws_checker, spreadsheet, driver, targets, param_map):
    """대상 행들의 순위 체크 + 결과 기록"""
    for i, (chk_row_num, param, kw, link, slot, prev_main, prev_blog, row_data) in enumerate(targets):
        src_row_num = param_map.get(param)
        if not src_row_num:
            print(f"\n  [{i+1}/{len(targets)}] {param} — 자사 발행리스트에서 행 못 찾음, 스킵")
            ws_checker.update(values=[["오류: 매핑 실패"]], range_name=f"L{chk_row_num}")
            continue

        if not kw or not link:
            print(f"\n  [{i+1}/{len(targets)}] {param} — 키워드 또는 링크 없음, 스킵")
            ws_checker.update(values=[["스킵(데이터 없음)"]], range_name=f"L{chk_row_num}")
            continue

        slot_label = slot.replace("slot", "")
        print(f"\n  [{i+1}/{len(targets)}] 키워드: {kw}")
        print(f"           타겟: {link}")
        print(f"           기록 위치: {slot_label}차")

        try:
            # 괄호 제거된 키워드로 검색
            search_kw = clean_keyword(kw)

            # 메인(통합검색) 체크
            print("           메인 검색 중...", end=" ", flush=True)
            main_rank = check_main(driver, search_kw, link)
            main_str = f"{main_rank}위" if main_rank else "순위 밖"
            print(main_str)

            # 블로그탭도 항상 체크
            print("           블로그탭 검색 중...", end=" ", flush=True)
            blog_rank = check_blog(driver, search_kw, link)
            blog_str = f"{blog_rank}위" if blog_rank else "순위 밖"
            print(blog_str)

            write_result(
                ws_source, ws_checker, spreadsheet,
                src_row_num, chk_row_num,
                main_rank, blog_rank, slot, prev_main, prev_blog,
            )

            # 상태 업데이트
            now = datetime.now().strftime("%m/%d %H:%M")
            ws_checker.update(values=[[f"완료 {now}"]], range_name=f"L{chk_row_num}")

        except Exception as e:
            print(f"\n           [!] 오류: {e}")
            ws_checker.update(values=[[f"오류: {e}"]], range_name=f"L{chk_row_num}")
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
    """수동 체크된 행 중 빈 슬롯 있는 행만 (3영업일 필터 없음)"""
    checked_set = set(clear_rows)
    targets = []
    for idx, row in enumerate(chk_rows[1:], start=2):
        if idx not in checked_set:
            continue
        param = _cell(row, CHK_COL_A)
        kw = _cell(row, CHK_COL_B)
        link = _cell(row, CHK_COL_C)
        if not param or not kw or not link:
            continue
        slot, prev_main, prev_blog = determine_slot(row)
        if slot is None:
            continue
        targets.append((idx, param, kw, link, slot, prev_main, prev_blog, row))
    return targets


def get_cron_targets(chk_rows):
    """3영업일 이내(발행일 기준) + 빈 슬롯 있는 행만"""
    targets = []
    today = datetime.now().date()

    for idx, row in enumerate(chk_rows[1:], start=2):
        param = _cell(row, CHK_COL_A)
        kw = _cell(row, CHK_COL_B)
        link = _cell(row, CHK_COL_C)
        pub_date = _cell(row, CHK_COL_M)  # 발행일 (자사 발행리스트 A열)
        if not param or not kw or not link:
            continue

        slot, prev_main, prev_blog = determine_slot(row)
        if slot is None:
            continue  # 3슬롯 다 참

        # 발행일이 3영업일 이내가 아니면 스킵
        if not is_within_check_range(pub_date, today=today):
            continue

        # slot2, slot3은 추가로 최초체크일도 확인
        if slot in ("slot2", "slot3"):
            first_date = _cell(row, CHK_COL_K)
            if not is_within_check_range(first_date, today=today):
                continue

        targets.append((idx, param, kw, link, slot, prev_main, prev_blog, row))

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
    spreadsheet, ws_source, ws_checker = connect_sheets()

    print("\n[2] 탭 동기화...")
    src_rows = sync_tab(ws_source, ws_checker)

    # 체커 탭 다시 읽기 (동기화 후)
    chk_rows = ws_checker.get_all_values()

    if mode == "cron":
        targets = get_cron_targets(chk_rows)
        print(f"    크론 모드: 3영업일 이내 대상 {len(targets)}개")
    else:
        # 체크 1개라도 있으면 → 3영업일 룰로 전체 대상 수집
        triggered, clear_rows = has_any_checked(chk_rows)
        if not triggered:
            print("    처리 대상이 없습니다. D열에 체크해주세요.")
            return
        # 체크 해제
        updates = [{"range": f"D{r}", "values": [[False]]} for r in clear_rows]
        ws_checker.batch_update(updates)
        # 체크된 행만 대상 (3영업일 필터 없음)
        targets = get_checked_targets(chk_rows, clear_rows)

    if not targets:
        print("    처리 대상이 없습니다.")
        return

    print(f"    {len(targets)}개 처리 대상")

    param_map = build_param_row_map(src_rows)

    print("\n[3] 브라우저 준비 중...")
    driver = create_driver()
    print("    준비 완료!")

    print("\n[4] 순위 검색 시작")
    print("-" * 50)

    try:
        driver = process_rows(ws_source, ws_checker, spreadsheet,
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
                spreadsheet, ws_source, ws_checker = connect_sheets()
                src_rows = sync_tab(ws_source, ws_checker)
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

            # 체크 = 트리거, 실제 대상은 3영업일 이내 전체
            targets = get_cron_targets(chk_rows)
            if not targets:
                print(f"\n\n  >> 체크 감지했으나 처리할 대상 없음 (모두 3슬롯 완료)")
                time.sleep(interval)
                continue

            print(f"\n\n  >> 체크 감지! 3영업일 이내 {len(targets)}개 처리 시작")

            param_map = build_param_row_map(src_rows)

            if driver is None:
                print("  브라우저 준비 중...")
                driver = create_driver()
                print("  준비 완료!")

            driver = process_rows(ws_source, ws_checker, spreadsheet,
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
