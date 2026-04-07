#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
keyword_board.py - 키워드 전광판 순위 체커

구글 시트 '키워드 전광판' 탭의 키워드를 네이버 블로그탭에서 검색하여
'자사 발행리스트' 링크와 매칭되는 결과의 순위·발행처·링크를 기록합니다.

시트 구조 (키워드 전광판):
  A: 제품 | B: 키워드 | C: 전환_금액
  D1: 날짜 | D2+: 순위 | E: 발행처(블로그명) | F: 자사발행처 | G: 링크
  H: 발행일 | I: 경과일 | J: 결제금액
  K1: 이전 날짜 (롤링: D~J -> K~Q)

시트 구조 (자사 발행리스트):
  A: 발행일 | B: 제품명 | M: 링크 | N: 발행처 | Z: 결제금액

사용법: python keyword_board.py [--limit N]
"""

import sys
import io
import time
import re
import os
import json
import base64
import urllib.parse
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import gspread
from google.oauth2.service_account import Credentials
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

# Windows cp949 인코딩 문제 해결
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


# ━━━━━━━━━━━━━━━━━━━━ 설정 ━━━━━━━━━━━━━━━━━━━━
SPREADSHEET_ID = "1jflcdbmBjQsY4hp8rNULXGGVqb64fGno4kudlTJoqM4"
CONV_SHEET_ID  = "1xJAogt0alaQ8A5OctxltPaF3kg_0PFSF5Z0ePxMw3tY"
CONV_TAB_NAME  = "전환 키워드"
SHEET_KEYWORD  = "키워드 전광판"
SHEET_PUBLIST  = "자사 발행리스트"
SHEET_PUBLIST2 = "내부 발행리스트"
CRED_FILE      = "../manuscript_generator/credentials.json"
BLOG_TOP_N     = 5   # 블로그탭 상위 N위까지 체크
WORKERS        = 2   # 병렬 브라우저 수
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# ────────────────────────────────────────────────
#  Google Sheets 연결
# ────────────────────────────────────────────────

def connect_sheets():
    """서비스 계정으로 구글 시트 연결"""
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
    return gc, gc.open_by_key(SPREADSHEET_ID)


# ────────────────────────────────────────────────
#  Selenium 브라우저
# ────────────────────────────────────────────────

def create_driver():
    """headless Chrome 생성"""
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
    driver.implicitly_wait(3)
    return driver


# 스레드별 드라이버 관리
_thread_drivers = {}
_driver_lock = threading.Lock()


def get_driver():
    """현재 스레드의 드라이버 반환 (없으면 생성)"""
    tid = threading.current_thread().ident
    with _driver_lock:
        if tid not in _thread_drivers:
            _thread_drivers[tid] = create_driver()
    return _thread_drivers[tid]


def quit_all_drivers():
    """모든 스레드 드라이버 종료"""
    for tid, driver in _thread_drivers.items():
        try:
            driver.quit()
        except Exception:
            pass
    _thread_drivers.clear()


# ────────────────────────────────────────────────
#  유틸리티
# ────────────────────────────────────────────────

def normalize_keyword(kw: str) -> str:
    """키워드 비교용 정규화: 괄호 번호 제거 + 공백 제거"""
    kw = re.sub(r"\(\d+\)", "", kw)  # (1), (2) 등 제거
    kw = kw.replace(" ", "").strip()
    return kw


def fill_conversion_amounts(gc, ws_keyword, kw_rows):
    """전환 키워드 탭에서 금액을 읽어 키워드 전광판 C열에 매칭 기입"""
    conv_ss = gc.open_by_key(CONV_SHEET_ID)
    conv_ws = conv_ss.worksheet(CONV_TAB_NAME)
    conv_data = conv_ws.get_all_values()

    if len(conv_data) < 3:
        print("    전환 키워드 데이터가 없습니다.")
        return

    # 전환 키워드 탭에서 키워드-금액 매핑 추출
    # 키워드: A(0), H(7), O(14), ... / 금액: D(3), K(10), R(17), ...
    conv_map = {}  # normalized_keyword -> 합산 금액
    for row in conv_data[2:]:  # 3행부터 데이터
        col = 0
        while col < len(row):
            kw_val = row[col].strip() if col < len(row) else ""
            amt_col = col + 3
            amt_val = row[amt_col].strip() if amt_col < len(row) else ""
            if kw_val:
                norm_kw = normalize_keyword(kw_val)
                if norm_kw and amt_val:
                    # 숫자만 추출하여 합산
                    amt_num = int(re.sub(r"[^\d]", "", amt_val) or "0")
                    conv_map[norm_kw] = conv_map.get(norm_kw, 0) + amt_num
            col += 7

    print(f"    전환 키워드 {len(conv_map)}개 로드 완료")

    # 키워드 전광판 B열과 매칭하여 C열 업데이트
    updates = []
    matched = 0
    for idx, row in enumerate(kw_rows[2:], start=3):  # 3행부터
        board_kw = cell(row, 1).strip()  # B열
        if not board_kw:
            continue
        norm_board = normalize_keyword(board_kw)
        amt = conv_map.get(norm_board, 0)
        if amt:
            updates.append({"range": f"C{idx}", "values": [[f"{amt:,}원"]]})
            matched += 1

    if updates:
        ws_keyword.batch_update(updates)
    print(f"    C열 매칭 기입: {matched}개")


def normalize(url: str) -> str:
    """프로토콜/www/m./끝 슬래시 제거 후 소문자"""
    url = re.sub(r"^https?://", "", url)
    url = re.sub(r"^(www\.|m\.)", "", url)
    return url.rstrip("/").lower()


def is_match(result_url: str, target_url: str) -> bool:
    """타겟 URL이 결과 URL에 포함되는지 판별"""
    return normalize(target_url) in normalize(result_url)


def cell(row, col_idx):
    """행 데이터에서 안전하게 값 가져오기"""
    return row[col_idx].strip() if len(row) > col_idx else ""


# ────────────────────────────────────────────────
#  블로그탭 검색 (Selenium)
# ────────────────────────────────────────────────

BLOG_EXTRACT_JS = """
    var results = [];
    var container = document.querySelector('section.sp_nblog, section._sp_nblog');
    if (!container) return results;

    // 광고 섹션 제외 - 블로그 섹션 내부만
    var allLinks = container.querySelectorAll('a[href*="blog.naver.com"]');
    var seenUrls = {};
    var seenBloggers = {};

    for (var i = 0; i < allLinks.length; i++) {
        var href = allLinks[i].href;
        if (!href || href.indexOf('http') !== 0) continue;

        var parts = href.replace('https://blog.naver.com/', '').split('/');
        if (parts.length < 2 || !parts[1]) continue;
        if (seenUrls[href]) continue;
        seenUrls[href] = true;

        var bloggerId = parts[0];
        if (seenBloggers[bloggerId]) continue;

        // 광고 체크 - 상위 요소에 ad 관련 클래스가 있는지
        var isAd = false;
        var el = allLinks[i];
        for (var j = 0; j < 15; j++) {
            if (!el || !el.parentElement) break;
            el = el.parentElement;
            var cls = (el.className || '').toLowerCase();
            var daa = el.getAttribute('data-ad-area');
            if (daa !== null || cls.indexOf('ad_section') !== -1 || cls.indexOf('ad_area') !== -1 ||
                cls.indexOf('type_ad') !== -1 || cls.indexOf('sponsored') !== -1) {
                isAd = true;
                break;
            }
        }
        if (isAd) continue;

        // 블로그 이름 추출
        var card = allLinks[i];
        var blogName = '';
        for (var k = 0; k < 20; k++) {
            if (!card.parentElement) break;
            card = card.parentElement;
            var nameEl = card.querySelector('.sds-comps-profile-info-title-text');
            if (!nameEl) nameEl = card.querySelector('.name');
            if (!nameEl) nameEl = card.querySelector('.user_info .nick');
            if (nameEl) {
                blogName = nameEl.textContent.trim();
                break;
            }
        }

        seenBloggers[bloggerId] = true;
        results.push({url: href, name: blogName});

        if (results.length >= """ + str(BLOG_TOP_N) + """) break;
    }
    return results;
"""


def search_blog(driver, keyword):
    """네이버 블로그탭 검색 -> 상위 결과 [(url, blog_name), ...] 반환"""
    driver.get(
        "https://search.naver.com/search.naver?ssc=tab.blog.all&sm=tab_jum&query="
        + urllib.parse.quote(keyword)
    )
    time.sleep(2)

    results = driver.execute_script(BLOG_EXTRACT_JS) or []
    return [(r["url"], r["name"]) for r in results]


# ────────────────────────────────────────────────
#  자사 발행리스트 로드
# ────────────────────────────────────────────────

def load_pub_links(spreadsheet):
    """자사+내부 발행리스트에서 {제품명: [(링크, 발행처, 발행일, 결제금액), ...]} 딕셔너리 반환"""
    product_links = {}

    # 자사 발행리스트: 결제금액 Z열(25)
    ws1 = spreadsheet.worksheet(SHEET_PUBLIST)
    for row in ws1.get_all_values()[1:]:
        pub_date = cell(row, 0).strip()    # A열: 발행일
        product = cell(row, 1).strip()     # B열: 제품명
        link = cell(row, 12).strip()       # M열: 링크
        publisher = cell(row, 13).strip()  # N열: 발행처
        pay_amount = cell(row, 25).strip() # Z열: 결제금액
        if product and link:
            product_links.setdefault(product, []).append(
                (link, publisher, pub_date, pay_amount)
            )

    # 내부 발행리스트: 결제금액 AA열(26)
    ws2 = spreadsheet.worksheet(SHEET_PUBLIST2)
    for row in ws2.get_all_values()[1:]:
        pub_date = cell(row, 0).strip()    # A열: 발행일
        product = cell(row, 1).strip()     # B열: 제품명
        link = cell(row, 12).strip()       # M열: 링크
        publisher = cell(row, 13).strip()  # N열: 발행처
        pay_amount = cell(row, 26).strip() # AA열: 결제금액
        if product and link:
            product_links.setdefault(product, []).append(
                (link, publisher, pub_date, pay_amount)
            )

    return product_links


# ────────────────────────────────────────────────
#  날짜 롤링
# ────────────────────────────────────────────────

def roll_columns(ws, total_rows):
    """D~J 열 데이터를 K~Q로 이동 후 D~J 초기화"""
    range_def = f"D1:J{total_rows}"
    old_data = ws.get(range_def)

    if not old_data:
        return

    range_new = f"K1:Q{len(old_data)}"
    ws.update(values=old_data, range_name=range_new)
    ws.batch_clear([range_def])

    print(f"    D~J -> K~Q 이동 완료 ({len(old_data)}행)")


# ────────────────────────────────────────────────
#  메인 실행
# ────────────────────────────────────────────────

def main():
    # --limit 옵션 파싱
    limit = None
    if "--limit" in sys.argv:
        try:
            limit = int(sys.argv[sys.argv.index("--limit") + 1])
        except (IndexError, ValueError):
            pass

    today_str = datetime.now().strftime("%Y-%m-%d")

    print("=" * 55)
    print("  키워드 전광판 순위 체커 (Selenium)")
    limit_msg = f" (상위 {limit}개)" if limit else ""
    print(f"  날짜: {today_str}{limit_msg}")
    print("=" * 55)

    # 1. 시트 연결
    print("\n[1] Google Sheets 연결 중...")
    gc, spreadsheet = connect_sheets()
    ws_keyword = spreadsheet.worksheet(SHEET_KEYWORD)

    # 1.5. 전환 금액 매칭 (순위 체크 전)
    print("\n[1.5] 전환 키워드 금액 매칭 중...")
    kw_rows_pre = ws_keyword.get_all_values()
    fill_conversion_amounts(gc, ws_keyword, kw_rows_pre)

    # 2. 발행리스트 로드 (자사 + 내부)
    print("[2] 발행리스트 로드 중 (자사 + 내부)...")
    pub_links = load_pub_links(spreadsheet)
    total_products = len(pub_links)
    total_links = sum(len(v) for v in pub_links.values())
    print(f"    {total_products}개 제품, {total_links}개 링크 로드 완료")

    # 3. 키워드 전광판 로드
    print("[3] 키워드 전광판 로드 중...")
    kw_rows = ws_keyword.get_all_values()
    total_rows = len(kw_rows)

    if total_rows < 2:
        print("    데이터가 없습니다.")
        return

    # 4. 날짜 롤링 체크
    d1_value = cell(kw_rows[0], 3) if len(kw_rows[0]) > 3 else ""
    print(f"    현재 D1 날짜: '{d1_value}'")

    if d1_value and d1_value != today_str:
        print(f"\n[4] 날짜 롤링: {d1_value} -> K~Q로 이동")
        roll_columns(ws_keyword, total_rows)
    elif not d1_value:
        print("\n[4] D1 비어있음 - 신규 기록")
    else:
        print(f"\n[4] 오늘({today_str}) 이미 기록됨 - 덮어쓰기")

    # D1에 오늘 날짜 + D2:J2 헤더 기입
    ws_keyword.update(values=[[today_str]], range_name="D1")
    headers = [["순위", "블로거명", "발행처", "링크", "발행일자", "연속일", "전환금액"]]
    ws_keyword.update(values=headers, range_name="D2:J2")

    # D2:J2 헤더 서식 (검정 배경 + 흰색 글씨)
    sheet_id = ws_keyword.id
    spreadsheet.batch_update({"requests": [
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 1,
                    "endRowIndex": 2,
                    "startColumnIndex": 3,
                    "endColumnIndex": 10,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {"red": 0, "green": 0, "blue": 0},
                        "textFormat": {
                            "foregroundColor": {"red": 1, "green": 1, "blue": 1},
                            "bold": True,
                        },
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        }
    ]})

    # 5. 처리 대상 필터링 (제품 매칭)
    print("\n[5] 제품 매칭 필터링...")
    targets = []
    for idx, row in enumerate(kw_rows[2:], start=3):
        product = cell(row, 0).strip()
        keyword = cell(row, 1).strip()

        if not product or not keyword:
            continue

        matched_links = pub_links.get(product, [])
        if not matched_links:
            continue

        targets.append((idx, keyword, matched_links))

    if limit:
        targets = targets[:limit]

    print(f"    처리 키워드: {len(targets)}개")

    if not targets:
        print("    처리할 키워드가 없습니다.")
        return

    # 6. 브라우저 준비 + 순위 검색
    print(f"\n[6] 블로그탭 순위 검색 시작 ({len(targets)}개, {WORKERS}개 병렬)")
    print("-" * 55)

    def process_one(idx, row_num, keyword, links):
        """단일 키워드 처리 (스레드에서 실행) - 복수 매칭 지원"""
        driver = get_driver()
        try:
            blog_results = search_blog(driver, keyword)
            matches = []
            for rank_idx, (result_url, pub_name) in enumerate(blog_results, 1):
                for target_link, target_publisher, pub_date, pay_amount in links:
                    if is_match(result_url, target_link):
                        # 경과일 계산
                        days_elapsed = ""
                        if pub_date:
                            try:
                                for fmt in ("%Y-%m-%d", "%m/%d", "%Y/%m/%d"):
                                    try:
                                        pd = datetime.strptime(pub_date, fmt)
                                        if pd.year == 1900:
                                            pd = pd.replace(year=datetime.now().year)
                                        # 미래 날짜면 전년도로 보정 (2025년 발행분)
                                        if pd > datetime.now():
                                            pd = pd.replace(year=pd.year - 1)
                                        days_elapsed = str((datetime.now() - pd).days)
                                        break
                                    except ValueError:
                                        continue
                            except Exception:
                                pass
                        matches.append((f"{rank_idx}위", pub_name, target_publisher,
                                        result_url, pub_date, days_elapsed, pay_amount))
                        break  # 같은 순위에서 중복 매칭 방지
            if matches:
                return (row_num, matches, keyword)
            return (row_num, [], keyword)
        except Exception as e:
            # 브라우저 오류 시 재시작
            tid = threading.current_thread().ident
            with _driver_lock:
                try:
                    _thread_drivers[tid].quit()
                except Exception:
                    pass
                _thread_drivers[tid] = create_driver()
            return (row_num, None, keyword)  # None = 오류

    results = []
    done_count = 0

    try:
        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            futures = {}
            for i, (row_num, keyword, links) in enumerate(targets):
                fut = executor.submit(process_one, i, row_num, keyword, links)
                futures[fut] = (i, keyword)

            for fut in as_completed(futures):
                done_count += 1
                row_num, matches, keyword = fut.result()

                if matches is None:
                    # 오류
                    results.append((row_num, "오류", "", "", "", "", "", ""))
                    print(f"  [{done_count}/{len(targets)}] {keyword} -> 오류")
                elif not matches:
                    # 순위 밖
                    results.append((row_num, "순위 밖", "", "", "", "", "", ""))
                    print(f"  [{done_count}/{len(targets)}] {keyword} -> 순위 밖")
                else:
                    # 매칭 결과를 줄바꿈으로 합침
                    rank_str = "\n".join(m[0] for m in matches)
                    pub_name = "\n".join(m[1] for m in matches)
                    company_pub = "\n".join(m[2] for m in matches)
                    link = "\n".join(m[3] for m in matches)
                    pub_date = "\n".join(m[4] for m in matches)
                    days_elapsed = "\n".join(m[5] for m in matches)
                    pay_amount = "\n".join(m[6] for m in matches)
                    results.append((row_num, rank_str, pub_name, company_pub, link,
                                    pub_date, days_elapsed, pay_amount))

                    for m in matches:
                        print(f"  [{done_count}/{len(targets)}] {keyword} -> {m[0]} | {m[1]} / {m[2]} | {m[4]}({m[5]}일) | 결제:{m[6]}")
    finally:
        quit_all_drivers()

    # 7. 시트에 결과 일괄 기록
    print(f"\n\n[7] 시트에 {len(results)}개 결과 기록 중...")

    batch_data = []
    for row_num, rank_str, pub_name, company_pub, link, pub_date, days_elapsed, pay_amount in results:
        batch_data.append({
            "range": f"D{row_num}:J{row_num}",
            "values": [[rank_str, pub_name, company_pub, link, pub_date, days_elapsed, pay_amount]],
        })

    if batch_data:
        ws_keyword.batch_update(batch_data)

    print("    기록 완료!")

    # 8. 옅은 빨간색 서식 (경과일 10일 이상 + 결제금액 0)
    print("\n[8] 서식 적용 중 (경과일≥10 & 결제금액=0)...")
    red_rows = []
    normal_rows = []
    for row_num, rank_str, pub_name, company_pub, link, pub_date, days_elapsed, pay_amount in results:
        try:
            days = int(days_elapsed) if days_elapsed else 0
        except ValueError:
            days = 0
        try:
            pay = int(re.sub(r"[^\d]", "", str(pay_amount))) if pay_amount else 0
        except ValueError:
            pay = 0

        if days >= 10 and pay == 0:
            red_rows.append(row_num)
        else:
            normal_rows.append(row_num)

    if red_rows or normal_rows:
        sheet_id = ws_keyword.id
        fmt_requests = []
        # 옅은 빨간색 배경
        for r in red_rows:
            fmt_requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": r - 1,
                        "endRowIndex": r,
                        "startColumnIndex": 3,  # D열
                        "endColumnIndex": 10,   # J열
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {
                                "red": 0.957, "green": 0.8, "blue": 0.8,
                            }
                        }
                    },
                    "fields": "userEnteredFormat.backgroundColor",
                }
            })
        # 조건 해제된 행은 흰색으로 복원
        for r in normal_rows:
            fmt_requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": r - 1,
                        "endRowIndex": r,
                        "startColumnIndex": 3,
                        "endColumnIndex": 10,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {
                                "red": 1.0, "green": 1.0, "blue": 1.0,
                            }
                        }
                    },
                    "fields": "userEnteredFormat.backgroundColor",
                }
            })
        if fmt_requests:
            spreadsheet.batch_update({"requests": fmt_requests})
            print(f"    빨간색: {len(red_rows)}행, 정상: {len(normal_rows)}행")

    print("\n" + "=" * 55)
    print("  키워드 전광판 순위 체크 완료!")
    print("=" * 55)


if __name__ == "__main__":
    main()
