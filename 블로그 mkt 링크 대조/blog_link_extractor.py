"""
블로그 MKT 링크 추출기
- 구글 시트 G열의 네이버 블로그 링크에서 MKT 링크 추출
- H, J열에 MKT 링크 기입
- I, K열에 F열 찐링크와 일치 여부 기입
"""

import os, re, time, json, base64
from urllib.parse import unquote

import gspread
from google.oauth2.service_account import Credentials
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import requests

# ── 설정 ──────────────────────────────────────────────
SPREADSHEET_ID = "1jflcdbmBjQsY4hp8rNULXGGVqb64fGno4kudlTJoqM4"
SHEET_NAME = "시트34"
CRED_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "manuscript_generator",
    "credentials.json",
)
SCOPE = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


# ── 구글 시트 ─────────────────────────────────────────
def get_gsheet():
    creds_b64 = os.environ.get("GOOGLE_CREDENTIALS_BASE64")
    if creds_b64:
        info = json.loads(base64.b64decode(creds_b64))
        creds = Credentials.from_service_account_info(info, scopes=SCOPE)
    else:
        creds = Credentials.from_service_account_file(CRED_FILE, scopes=SCOPE)
    gc = gspread.authorize(creds)
    return gc.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)


# ── Selenium 드라이버 ─────────────────────────────────
def create_driver():
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
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
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
    return driver


# ── 블로그 MKT 링크 추출 ─────────────────────────────
def switch_to_blog_frame(driver):
    driver.switch_to.default_content()
    try:
        iframe = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.ID, "mainFrame"))
        )
        driver.switch_to.frame(iframe)
    except Exception:
        pass


def extract_mkt_links(driver, blog_url):
    """블로그 페이지에서 mkt.shopping.naver.com 링크를 원본 그대로 추출"""
    # blog.naver.com/ID/번호 → PostView 형식으로 변환
    m = re.match(r"https?://blog\.naver\.com/([^/?]+)/(\d+)", blog_url)
    if m:
        bid, lno = m.groups()
        view_url = (
            f"https://blog.naver.com/PostView.naver"
            f"?blogId={bid}&logNo={lno}&redirect=Dlog&widgetTypeCall=true"
        )
    else:
        view_url = blog_url

    driver.get(view_url)
    time.sleep(3)
    switch_to_blog_frame(driver)
    time.sleep(1)

    mkt_links = []
    seen = set()

    # 1) DOM에서 a 태그 href 추출
    selectors = [
        "div.se-main-container a",
        "div#postViewArea a",
        "a.se-oglink-info",
        "a.se-module-oglink",
        "div.se-module-oglink a",
        "a[data-linkdata]",
        "div.se-section-oglink a",
        "a.se-link",
    ]
    for sel in selectors:
        try:
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                href = el.get_attribute("href") or ""
                _collect_mkt(href, mkt_links, seen)
        except Exception:
            continue

    # 2) data-linkdata 속성에서 URL 추출
    try:
        for el in driver.find_elements(By.CSS_SELECTOR, "[data-linkdata]"):
            data = el.get_attribute("data-linkdata") or ""
            for url in re.findall(r"https?://[^\s\"'<>\\,}]+", data):
                _collect_mkt(url, mkt_links, seen)
    except Exception:
        pass

    # 3) 페이지 소스에서 직접 추출 (JS로 DOM이 변경된 경우 대비)
    try:
        source = driver.page_source
        for url in re.findall(
            r'https?://mkt\.shopping\.naver\.com/link/[^\s"\'<>\\]+', source
        ):
            _collect_mkt(url, mkt_links, seen)
    except Exception:
        pass

    return mkt_links


def _collect_mkt(href, mkt_links, seen):
    """mkt.shopping.naver.com 링크 수집 (동일 링크도 중복 허용)"""
    href = unquote(href).strip()
    if "mkt.shopping.naver.com" not in href:
        return
    # NaPm 추적 파라미터 제거
    clean = re.sub(r"[&?]NaPm=[^&]*", "", href)
    mkt_links.append(clean)


# ── MKT 링크 → 최종 URL 추적 ─────────────────────────
def resolve_mkt_link(mkt_url):
    """MKT 링크를 따라가서 리다이렉트 최종 URL 반환"""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
    }
    try:
        resp = requests.head(mkt_url, allow_redirects=True, timeout=10, headers=headers)
        return resp.url
    except Exception:
        pass
    try:
        resp = requests.get(mkt_url, allow_redirects=True, timeout=10, headers=headers)
        return resp.url
    except Exception:
        return ""


def normalize_product_url(url):
    """상품 URL 정규화 — 비교용"""
    url = unquote(url).strip()
    url = re.sub(r"\?.*", "", url)           # 쿼리 파라미터 제거
    url = re.sub(r"^https?://", "", url)     # 프로토콜 제거
    url = re.sub(r"^(www\.|m\.)", "", url)   # www/m 제거
    return url.rstrip("/").lower()


def check_match(mkt_url, real_url):
    """MKT 링크의 최종 목적지가 찐링크(F열)와 일치하는지 확인"""
    if not mkt_url or not real_url:
        return ""

    resolved = resolve_mkt_link(mkt_url)
    if not resolved:
        return "확인불가"

    norm_resolved = normalize_product_url(resolved)
    norm_real = normalize_product_url(real_url)

    # 전체 URL 비교
    if norm_resolved == norm_real:
        return "일치"

    # 상품 ID(products/숫자)만 비교
    m1 = re.search(r"products/(\d+)", norm_resolved)
    m2 = re.search(r"products/(\d+)", norm_real)
    if m1 and m2 and m1.group(1) == m2.group(1):
        return "일치"

    return "불일치"


# ── 메인 ──────────────────────────────────────────────
def main():
    print("=" * 50)
    print("  블로그 MKT 링크 추출기")
    print("=" * 50)

    # 1. 시트 연결
    print("\n[1/3] 구글 시트 연결...")
    ws = get_gsheet()

    # 2. 데이터 읽기 (1행 = 헤더)
    all_data = ws.get_all_values()
    if len(all_data) < 2:
        print("데이터가 없습니다.")
        return

    blog_rows = []
    for i, row in enumerate(all_data[1:], start=2):  # 2행부터
        g_val = row[6] if len(row) > 6 else ""   # G열 (블로그 링크)
        f_val = row[5] if len(row) > 5 else ""   # F열 (찐링크)
        if g_val.strip():
            blog_rows.append((i, g_val.strip(), f_val.strip()))

    if not blog_rows:
        print("G열에 블로그 링크가 없습니다.")
        return

    print(f"  → {len(blog_rows)}개 블로그 링크 발견")

    # 3. MKT 링크 추출
    print("\n[2/3] 블로그에서 MKT 링크 추출 중...")
    driver = create_driver()
    results = []
    try:
        for idx, (row_num, blog_url, real_url) in enumerate(blog_rows):
            print(f"  [{idx+1}/{len(blog_rows)}] {blog_url[:70]}...")
            mkt_links = extract_mkt_links(driver, blog_url)
            print(f"         → MKT 링크 {len(mkt_links)}개 발견")

            mkt1 = mkt_links[0] if len(mkt_links) > 0 else ""
            mkt2 = mkt_links[1] if len(mkt_links) > 1 else ""
            results.append((row_num, mkt1, mkt2, real_url))
    finally:
        driver.quit()

    # 4. 일치 여부 확인 & 시트 기입
    print("\n[3/3] 일치 여부 확인 & 시트 기입...")
    for row_num, mkt1, mkt2, real_url in results:
        match1 = check_match(mkt1, real_url) if mkt1 else ""
        match2 = check_match(mkt2, real_url) if mkt2 else ""

        print(f"  행{row_num}: H={'O' if mkt1 else 'X'}({match1}) J={'O' if mkt2 else 'X'}({match2})")

        # H(MKT1), I(일치여부1), J(MKT2), K(일치여부2)
        ws.update(f"H{row_num}:K{row_num}", [[mkt1, match1, mkt2, match2]])
        time.sleep(0.5)  # API 속도 제한

    print(f"\n완료! {len(results)}개 블로그 처리됨.")


if __name__ == "__main__":
    main()
