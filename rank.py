#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
rank.py - 네이버 검색 순위 체커
구글 스프레드시트에서 키워드·타겟 URL을 읽어
네이버 통합검색(메인) + 블로그탭 순위를 확인하고 시트에 기록합니다.

시트 구조:
  A: 날짜 | B: 발행처 | C: 키워드 | D: 링크
  E: 메인 순위1 | F: 블로그탭 순위1
  G: 메인 순위2 | H: 블로그탭 순위2
  I: 메인 순위3 | J: 블로그탭 순위3
  K: 실행 (체크박스, 체크하면 트리거)

동작:
  - 순위1(E,F) 비어있으면 → 순위1에 기록
  - 순위1 있고 순위2(G,H) 비어있으면 → 순위2에 기록
  - 순위2 있고 순위3(I,J) 비어있으면 → 순위3에 기록
  - 순위2,3 기록 시 순위 상승/진입이면 연노란색 표시
  - 셋 다 있으면 → 건너뛰기

사용법: python rank.py watch
"""

import time
import re
import os
import json
import base64
import urllib.parse

import gspread
from google.oauth2.service_account import Credentials
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager


# ━━━━━━━━━━━━━━━━━━━━ 설정 ━━━━━━━━━━━━━━━━━━━━
SPREADSHEET_ID = "1ANZLaVSXB8MKD6BXUCpcZw9t6EaZhKZlcJuXKN_yX_U"   # ← 본인 시트 ID
SHEET_NAME     = "시트1"                         # ← 시트 탭 이름
CRED_FILE      = "credentials.json"              # ← 서비스 계정 키 파일
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# ────────────────────────────────────────────────
#  Google Sheets 연결
# ────────────────────────────────────────────────

def connect_sheet():
    """서비스 계정으로 구글 시트 연결 → 워크시트 반환"""
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    # Railway: GOOGLE_CREDENTIALS_BASE64 환경변수 우선, 없으면 로컬 파일 폴백
    creds_b64 = os.environ.get("GOOGLE_CREDENTIALS_BASE64")
    if creds_b64:
        # Railway UI가 공백/줄바꿈을 추가할 수 있으므로 제거
        creds_b64 = ''.join(creds_b64.split())
        # 패딩 보정
        creds_b64 += '=' * (-len(creds_b64) % 4)
        decoded = base64.b64decode(creds_b64).decode('utf-8')
        info = json.loads(decoded)
        # private_key \n 처리 (환경변수에서 literal \\n으로 저장된 경우)
        if 'private_key' in info:
            info['private_key'] = info['private_key'].replace('\\n', '\n')
        creds = Credentials.from_service_account_info(info, scopes=scope)
    else:
        creds = Credentials.from_service_account_file(CRED_FILE, scopes=scope)
    gc = gspread.authorize(creds)
    return gc.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)


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

    # Chrome 경로 자동 탐색 (로컬/Docker/Nixpacks 순서로)
    chrome_candidates = [
        os.environ.get("CHROME_BIN"),
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/nix/var/nix/profiles/default/bin/chromium",
    ]
    chromedriver_candidates = [
        os.environ.get("CHROMEDRIVER_BIN"),
        "/usr/bin/chromedriver",
        "/nix/var/nix/profiles/default/bin/chromedriver",
    ]

    chrome_bin = next((p for p in chrome_candidates if p and os.path.exists(p)), None)
    chromedriver_bin = next((p for p in chromedriver_candidates if p and os.path.exists(p)), None)

    if chrome_bin and chromedriver_bin:
        opts.binary_location = chrome_bin
        driver = webdriver.Chrome(service=Service(chromedriver_bin), options=opts)
    else:
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=opts,
        )
    # navigator.webdriver 플래그 숨기기
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"},
    )
    driver.implicitly_wait(5)
    return driver


# ────────────────────────────────────────────────
#  유틸리티
# ────────────────────────────────────────────────

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


# ────────────────────────────────────────────────
#  검색 결과 추출 (JavaScript)
# ────────────────────────────────────────────────

# 메인 통합검색: 섹션(api_subject_bx) 단위로 카운트, AI 브리핑·광고 제외
MAIN_EXTRACT_JS = """
    var pack = document.getElementById('main_pack') || document.body;
    var sections = pack.querySelectorAll('.api_subject_bx');
    var targets = ['blog.naver.com', 'cafe.naver.com', 'kin.naver.com'];
    var results = [];

    for (var s = 0; s < sections.length; s++) {
        var sec = sections[s];

        // AI 브리핑, 광고 섹션 스킵
        var titleEl = sec.querySelector('.tit_area .tit, .api_title, h2, .title_area .tit');
        var titleText = titleEl ? titleEl.textContent.trim() : '';
        if (titleText.indexOf('AI') !== -1) continue;

        var cls = (sec.className || '').toLowerCase();
        var daa = sec.getAttribute('data-ad-area');
        if (daa !== null || cls.indexOf('ad_area') !== -1 || cls.indexOf('type_ad') !== -1 ||
            cls.indexOf('sponsored') !== -1 || cls.indexOf('powerlink') !== -1) continue;

        // 이 섹션에서 첫 번째 블로그/카페/지식인 글 링크 찾기
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

# 블로그탭에서 blog.naver.com 글 링크만 추출 (카드 단위, 꼬리글 제외, 광고 제외)
BLOG_EXTRACT_JS = """
    var results = [];

    // 방법1: fds-ugc 카드 컨테이너 기반 (꼬리글 제외)
    var container = document.querySelector('.fds-ugc-single-intention-item-list-tab');
    if (container) {
        var children = container.children;
        for (var i = 0; i < children.length; i++) {
            var child = children[i];

            // 광고 체크
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

            // 이 카드에서 첫 번째 blog.naver.com 포스트 링크만 가져오기 (꼬리글 제외)
            var blogLinks = child.querySelectorAll('a[href*="blog.naver.com"]');
            for (var j = 0; j < blogLinks.length; j++) {
                var href = blogLinks[j].href;
                if (!href || href.indexOf('http') !== 0) continue;
                var pathParts = new URL(href).pathname.split('/').filter(function(p){return p;});
                if (pathParts.length < 2) continue;
                results.push(href);
                break;  // 카드당 첫 번째 링크만
            }
        }
        return results;
    }

    // 방법2: 폴백 - 전체 링크 수집 (컨테이너 없을 경우)
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
    print(f"\n           [디버그] 메인 결과 {len(results)}개 (블로그/카페/지식인):")
    for i, item in enumerate(results[:10], 1):
        u = item[0] if isinstance(item, list) else item
        sec = item[1] if isinstance(item, list) and len(item) > 1 else ""
        print(f"             {i}. [{sec}] {u}")
    for rank, item in enumerate(results, start=1):
        u = item[0] if isinstance(item, list) else item
        sec = item[1] if isinstance(item, list) and len(item) > 1 else ""
        if is_match(u, target_url):
            return rank, sec
    return None, ""


def check_blog(driver, keyword, target_url, limit=150):
    """블로그탭 - 올바른 URL(ssc=tab.blog.all) + 블로그 글만 추출, 광고 제외"""
    driver.get(
        "https://search.naver.com/search.naver?ssc=tab.blog.all&sm=tab_jum&query="
        + urllib.parse.quote(keyword)
    )
    time.sleep(3)
    scroll_times(driver, n=5, pause=2.0)
    time.sleep(1)

    results = driver.execute_script(BLOG_EXTRACT_JS) or []
    print(f"\n           [디버그] 블로그탭 결과 {len(results)}개:")
    for i, u in enumerate(results[:10], 1):
        print(f"             {i}. {u}")
    for rank, url in enumerate(results, start=1):
        if rank > limit:
            break
        if is_match(url, target_url):
            return rank
    return None


# ────────────────────────────────────────────────
#  메인 실행
# ────────────────────────────────────────────────

def is_checked(val: str) -> bool:
    """I열 값이 실행 대상인지 판별"""
    v = val.strip().upper()
    return v in ("TRUE", "O", "V", "Y", "1", "ㅇ")


def parse_rank(val: str):
    """'3위' → 3, '순위 밖' → None"""
    m = re.search(r'(\d+)', val)
    return int(m.group(1)) if m else None


def is_improved(rank1_str: str, rank2_str: str) -> bool:
    """순위2가 순위1보다 좋아졌고 10위 이내일 때만 True"""
    r1 = parse_rank(rank1_str)
    r2 = parse_rank(rank2_str)
    if r2 is None or r2 > 10:
        return False
    if r1 is None:
        return True
    return r2 < r1


LIGHT_YELLOW = {"backgroundColor": {"red": 1, "green": 1, "blue": 0.8}}


def main():
    print("=" * 50)
    print("  네이버 검색 순위 체커")
    print("=" * 50)

    # 1) 시트 연결
    print("\n[1] Google Sheets 연결 중...")
    ws = connect_sheet()
    rows = ws.get_all_values()

    # K열 "실행" 헤더 자동 생성
    header = rows[0] if rows else []
    if len(header) < 11 or header[10] != "실행":
        ws.update(
            values=[["메인 순위1", "블로그탭 순위1", "메인 순위2", "블로그탭 순위2", "메인 순위3", "블로그탭 순위3", "실행"]],
            range_name="E1:K1",
        )
        print("    E~K열 헤더 설정 완료")

    keywords = rows[1:]
    total = len(keywords)
    if total == 0:
        print("    시트에 데이터가 없습니다.")
        return

    # K열 체크 확인 (트리거)
    has_trigger = False
    clear_rows = []
    for idx, row in enumerate(keywords):
        chk = row[10].strip() if len(row) > 10 else ""
        if is_checked(chk):
            has_trigger = True
            clear_rows.append(idx + 2)

    if not has_trigger:
        print("    실행 대상이 없습니다. 시트 K열에 체크해주세요.")
        return

    # 체크 해제
    for r in clear_rows:
        ws.update(values=[[False]], range_name=f"K{r}")

    # 대상 필터링: 순위1~3 중 비어있는 행
    targets = []
    for idx, row in enumerate(keywords):
        row_num = idx + 2
        kw  = row[2].strip() if len(row) > 2 else ""
        url = row[3].strip() if len(row) > 3 else ""
        e = row[4].strip() if len(row) > 4 else ""
        f = row[5].strip() if len(row) > 5 else ""
        g = row[6].strip() if len(row) > 6 else ""
        h = row[7].strip() if len(row) > 7 else ""
        i = row[8].strip() if len(row) > 8 else ""
        j = row[9].strip() if len(row) > 9 else ""

        if not kw or not url:
            continue

        if not e and not f:
            targets.append((row_num, kw, url, "slot1"))
        elif not g and not h:
            targets.append((row_num, kw, url, "slot2", e, f))
        elif not i and not j:
            targets.append((row_num, kw, url, "slot3", e, f, g, h))
        # 셋 다 있으면 건너뛰기

    if not targets:
        print("    처리할 행이 없습니다 (모두 기록 완료)")
        return
    print(f"    전체 {total}개 중 {len(targets)}개 처리 대상")

    # 2) 브라우저 시작
    print("\n[2] 브라우저 준비 중...")
    driver = create_driver()
    print("    준비 완료!")

    # 3) 키워드별 순위 검색
    print("\n[3] 순위 검색 시작")
    print("-" * 50)

    try:
        for i, target in enumerate(targets):
            row_num, kw, url, slot = target[0], target[1], target[2], target[3]
            print(f"\n  [{i+1}/{len(targets)}] 키워드: {kw}")
            print(f"           타겟: {url}")
            print(f"           기록 위치: {'순위1 (E,F)' if slot == 'slot1' else '순위2 (G,H)'}")

            try:
                print("           메인 검색 중...", end=" ", flush=True)
                mr, section = check_main(driver, kw, url)
                mc = f"{mr}위({section})" if mr else "순위 밖"
                print(mc)

                print("           블로그탭 검색 중...", end=" ", flush=True)
                br = check_blog(driver, kw, url)
                bc = str(br) + "위" if br else "순위 밖"
                print(bc)

                if slot == "slot1":
                    ws.update(values=[[mc, bc]], range_name=f"E{row_num}:F{row_num}")
                    print("           순위1 기록 완료")
                elif slot == "slot2":
                    prev_main, prev_blog = target[4], target[5]
                    ws.update(values=[[mc, bc]], range_name=f"G{row_num}:H{row_num}")
                    print("           순위2 기록 완료")
                    main_up = is_improved(prev_main, mc)
                    blog_up = is_improved(prev_blog, bc)
                    if main_up:
                        ws.format(f"G{row_num}", LIGHT_YELLOW)
                        print("           메인 순위 상승! 노란색 표시")
                    if blog_up:
                        ws.format(f"H{row_num}", LIGHT_YELLOW)
                        print("           블로그탭 순위 상승! 노란색 표시")
                else:  # slot3
                    prev_main, prev_blog = target[6], target[7]
                    ws.update(values=[[mc, bc]], range_name=f"I{row_num}:J{row_num}")
                    print("           순위3 기록 완료")
                    main_up = is_improved(prev_main, mc)
                    blog_up = is_improved(prev_blog, bc)
                    if main_up:
                        ws.format(f"I{row_num}", LIGHT_YELLOW)
                        print("           메인 순위 상승! 노란색 표시")
                    if blog_up:
                        ws.format(f"J{row_num}", LIGHT_YELLOW)
                        print("           블로그탭 순위 상승! 노란색 표시")

            except Exception as e:
                print(f"\n           [!] 오류 발생, 브라우저 재시작: {e}")
                try:
                    driver.quit()
                except Exception:
                    pass
                driver = create_driver()

            time.sleep(2)

    finally:
        driver.quit()

    print("\n" + "=" * 50)
    print("  모든 키워드 처리 완료!")
    print("=" * 50)


def watch(interval=60):
    """시트를 주기적으로 감시하며 I열 체크 시 자동 실행"""
    from datetime import datetime
    import zoneinfo
    KST = zoneinfo.ZoneInfo("Asia/Seoul")

    print("=" * 50)
    print("  네이버 순위 체커 - 감시 모드")
    print(f"  {interval}초마다 시트를 확인합니다.")
    print("  운영 시간: 10:00 ~ 18:00")
    print("  시트 I열(2행)에 체크하면 자동 실행!")
    print("  종료: Ctrl+C")
    print("=" * 50)

    ws = connect_sheet()
    driver = None

    # K열 헤더 확인
    header = ws.row_values(1)
    if len(header) < 11 or header[10] != "실행":
        ws.update(
            values=[["메인 순위1", "블로그탭 순위1", "메인 순위2", "블로그탭 순위2", "메인 순위3", "블로그탭 순위3", "실행"]],
            range_name="E1:K1",
        )

    try:
        while True:
            hour = datetime.now(KST).hour
            if hour < 10 or hour >= 18:
                now = datetime.now(KST).strftime("%H:%M:%S")
                print(f"\r  [{now}] 운영 시간 외 (10:00~18:00만 감시)", end="", flush=True)
                if driver:
                    driver.quit()
                    driver = None
                ws = None
                time.sleep(60)
                continue

            # 시트 연결 (끊겼으면 재연결)
            try:
                if ws is None:
                    ws = connect_sheet()
                    print("\n  시트 재연결 완료")
                rows = ws.get_all_values()
            except Exception as e:
                now = datetime.now(KST).strftime("%H:%M:%S")
                print(f"\n  [{now}] 시트 연결 오류, 재연결 시도... ({e})")
                try:
                    ws = connect_sheet()
                    rows = ws.get_all_values()
                    print("  재연결 성공!")
                except Exception:
                    print("  재연결 실패, 1분 후 재시도")
                    time.sleep(60)
                    continue
            keywords = rows[1:]

            # K열에 체크가 하나라도 있는지 확인 (트리거)
            has_trigger = False
            clear_rows = []
            for idx, row in enumerate(keywords):
                chk = row[10].strip() if len(row) > 10 else ""
                if is_checked(chk):
                    has_trigger = True
                    clear_rows.append(idx + 2)

            if not has_trigger:
                now = datetime.now(KST).strftime("%H:%M:%S")
                print(f"\r  [{now}] 대기 중... (체크된 행 없음)", end="", flush=True)
                time.sleep(interval)
                continue

            # 체크 해제
            for r in clear_rows:
                ws.update(values=[[False]], range_name=f"K{r}")

            # 대상 필터링: 순위1~3 중 비어있는 행
            targets = []
            for idx, row in enumerate(keywords):
                row_num = idx + 2
                kw  = row[2].strip() if len(row) > 2 else ""
                url = row[3].strip() if len(row) > 3 else ""
                e = row[4].strip() if len(row) > 4 else ""
                f = row[5].strip() if len(row) > 5 else ""
                g = row[6].strip() if len(row) > 6 else ""
                h = row[7].strip() if len(row) > 7 else ""
                i = row[8].strip() if len(row) > 8 else ""
                j = row[9].strip() if len(row) > 9 else ""

                if not kw or not url:
                    continue

                if not e and not f:
                    targets.append((row_num, kw, url, "slot1"))
                elif not g and not h:
                    targets.append((row_num, kw, url, "slot2", e, f))
                elif not i and not j:
                    targets.append((row_num, kw, url, "slot3", e, f, g, h))

            if not targets:
                print(f"\n\n  >> 체크 감지했으나 처리할 행이 없습니다 (모두 기록 완료)")
                time.sleep(interval)
                continue

            print(f"\n\n  >> 체크 감지! {len(targets)}개 처리 시작")

            if driver is None:
                print("  브라우저 준비 중...")
                driver = create_driver()
                print("  준비 완료!")

            for i, target in enumerate(targets):
                row_num, kw, url, slot = target[0], target[1], target[2], target[3]
                print(f"\n  [{i+1}/{len(targets)}] 키워드: {kw}")
                print(f"           타겟: {url}")
                print(f"           기록 위치: {'순위1 (E,F)' if slot == 'slot1' else '순위2 (G,H)'}")

                try:
                    print("           메인 검색 중...", end=" ", flush=True)
                    mr, section = check_main(driver, kw, url)
                    mc = f"{mr}위({section})" if mr else "순위 밖"
                    print(mc)

                    print("           블로그탭 검색 중...", end=" ", flush=True)
                    br = check_blog(driver, kw, url)
                    bc = str(br) + "위" if br else "순위 밖"
                    print(bc)

                    if slot == "slot1":
                        ws.update(values=[[mc, bc]], range_name=f"E{row_num}:F{row_num}")
                        print("           순위1 기록 완료")
                    elif slot == "slot2":
                        prev_main, prev_blog = target[4], target[5]
                        ws.update(values=[[mc, bc]], range_name=f"G{row_num}:H{row_num}")
                        print("           순위2 기록 완료")
                        main_up = is_improved(prev_main, mc)
                        blog_up = is_improved(prev_blog, bc)
                        if main_up:
                            ws.format(f"G{row_num}", LIGHT_YELLOW)
                            print("           메인 순위 상승! 노란색 표시")
                        if blog_up:
                            ws.format(f"H{row_num}", LIGHT_YELLOW)
                            print("           블로그탭 순위 상승! 노란색 표시")
                    else:  # slot3
                        prev_main, prev_blog = target[6], target[7]
                        ws.update(values=[[mc, bc]], range_name=f"I{row_num}:J{row_num}")
                        print("           순위3 기록 완료")
                        main_up = is_improved(prev_main, mc)
                        blog_up = is_improved(prev_blog, bc)
                        if main_up:
                            ws.format(f"I{row_num}", LIGHT_YELLOW)
                            print("           메인 순위 상승! 노란색 표시")
                        if blog_up:
                            ws.format(f"J{row_num}", LIGHT_YELLOW)
                            print("           블로그탭 순위 상승! 노란색 표시")

                except Exception as e:
                    print(f"\n           [!] 오류: {e}")
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    driver = create_driver()

                time.sleep(2)

            print("\n  처리 완료! 다시 대기 중...")

    except KeyboardInterrupt:
        print("\n\n  감시 모드 종료!")
    finally:
        if driver:
            driver.quit()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "watch":
        watch()
    else:
        main()
