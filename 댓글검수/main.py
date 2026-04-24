"""
댓글 검수 프로그램 v2.1
- 5개 블록(A-E, F-J, K-O, P-T, U-Y)에서 링크+댓글 읽기
- 각 블록: 1열=링크 목록, 2열=댓글 목록 → 모든 링크를 모든 댓글로 체크
- 결과를 묶음 형태로 재배치 (링크 → 댓글결과 → 미등록댓글 내용)
- 병렬 스크래핑 (브라우저 4개 동시)
"""

import re
import time
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

import gspread
from google.oauth2.service_account import Credentials
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# ─── 설정 ───────────────────────────────────────────────
SPREADSHEET_ID = "14IQ3of3Pe9TI-VNHAKNisxYLNub9DSSH7ZZx2Rnzbj8"
SHEET_TAB = "댓글 비교"

CRED_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "manuscript_generator", "credentials.json",
)

MATCH_MIN_LEN = 10  # 부분 일치 최소 글자 수
NUM_BLOCKS = 5
BLOCK_WIDTH = 5     # 각 블록 5열 (링크, 댓글, 중복, 누락, 미등록)
BLOCK_OFFSETS = [i * BLOCK_WIDTH for i in range(NUM_BLOCKS)]  # [0, 5, 10, 15, 20]
NUM_WORKERS = 4     # 병렬 브라우저 수


def col_letter(idx):
    """0-based column index → 시트 열 문자 (A~Z)"""
    return chr(ord('A') + idx)


# ─── Google Sheets 연결 ─────────────────────────────────
def connect_sheet():
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(CRED_FILE, scopes=scope)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SPREADSHEET_ID)
    ws = sh.worksheet(SHEET_TAB) if isinstance(SHEET_TAB, str) else sh.get_worksheet(SHEET_TAB)
    return ws


# ─── 블록 파싱 ─────────────────────────────────────────
def parse_block(all_values, col_offset):
    """
    블록에서 링크 목록과 댓글 목록 추출 (1행 헤더 스킵).
    반환: (links: [str, ...], comments: [str, ...])
    """
    links = []
    comments = []
    for i, row in enumerate(all_values):
        if i == 0:
            continue
        link = row[col_offset].strip() if len(row) > col_offset else ""
        comment = row[col_offset + 1].strip() if len(row) > col_offset + 1 else ""
        if link:
            links.append(link)
        if comment:
            comments.append(comment)
    return links, comments


# ─── Selenium 드라이버 ──────────────────────────────────
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


# ─── 네이버 블로그 댓글 스크래핑 ────────────────────────
def switch_to_blog_frame(driver):
    """네이버 블로그 mainFrame iframe 전환"""
    driver.switch_to.default_content()
    try:
        iframe = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.ID, "mainFrame"))
        )
        driver.switch_to.frame(iframe)
        return True
    except Exception:
        pass
    try:
        for iframe in driver.find_elements(By.TAG_NAME, "iframe"):
            src = iframe.get_attribute("src") or ""
            if "PostView" in src or "post" in src.lower():
                driver.switch_to.frame(iframe)
                return True
    except Exception:
        pass
    return False


def expand_all_comments(driver):
    """댓글 더보기 버튼 반복 클릭"""
    for _ in range(30):
        clicked = False
        for sel in [".u_cbox_btn_more", ".u_cbox_page_more",
                    "a.u_cbox_btn_view_comment", "button.u_cbox_btn_more"]:
            try:
                for btn in driver.find_elements(By.CSS_SELECTOR, sel):
                    if btn.is_displayed():
                        driver.execute_script("arguments[0].click();", btn)
                        time.sleep(1)
                        clicked = True
                        break
            except Exception:
                pass
            if clicked:
                break
        if not clicked:
            break


def scrape_comments(driver, url):
    """블로그 URL 접속 → 모든 댓글 텍스트 리스트 반환."""
    driver.get(url)
    time.sleep(3)

    switch_to_blog_frame(driver)
    time.sleep(2)

    # 댓글 목록 펼치기
    try:
        cmt_btn = driver.find_element(By.CSS_SELECTOR, "a._cmtList")
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", cmt_btn)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", cmt_btn)
        time.sleep(3)
    except Exception:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight * 0.7)")
        time.sleep(2)

    # 댓글 로드 대기
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".u_cbox_comment_box"))
        )
    except Exception:
        pass

    # 댓글 영역으로 스크롤
    try:
        cbox = driver.find_element(By.CSS_SELECTOR, ".u_cbox")
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", cbox)
        time.sleep(1)
    except Exception:
        pass

    expand_all_comments(driver)

    # 댓글 텍스트 수집
    comment_elements = []
    for sel in [".u_cbox_comment_box", ".u_cbox_comment",
                "li.u_cbox_comment", ".comment_item"]:
        comment_elements = driver.find_elements(By.CSS_SELECTOR, sel)
        if comment_elements:
            break

    texts = []
    for elem in comment_elements:
        for ts in [".u_cbox_contents", ".u_cbox_text_wrap",
                   ".u_cbox_text", "span.u_cbox_contents", ".comment_text"]:
            try:
                el = elem.find_element(By.CSS_SELECTOR, ts)
                t = el.text.strip()
                if t:
                    texts.append(t)
                    break
            except Exception:
                continue

    driver.switch_to.default_content()
    return texts


# ─── 매칭 로직 ──────────────────────────────────────────
def normalize(text):
    """공백 제거 정규화"""
    return re.sub(r'\s+', '', text)


def has_common_substring(a, b, min_len):
    """a와 b 사이에 min_len 이상의 공통 부분 문자열이 있는지 확인"""
    if len(a) > len(b):
        a, b = b, a
    for i in range(len(a) - min_len + 1):
        if a[i:i + min_len] in b:
            return True
    return False


def is_match(exp_norm, blog_norm):
    """기대 댓글(정규화)과 블로그 댓글(정규화) 매칭 여부"""
    if len(exp_norm) < MATCH_MIN_LEN:
        return exp_norm == blog_norm
    return has_common_substring(exp_norm, blog_norm, MATCH_MIN_LEN)


def count_matches(expected_norm, blog_comments_normalized):
    """기대 댓글이 블로그 댓글에 몇 번 매칭되는지 카운트."""
    return sum(1 for c in blog_comments_normalized if is_match(expected_norm, c))


# ─── 병렬 스크래핑 ─────────────────────────────────────
def scrape_single_url(url, worker_id):
    """단일 URL 스크래핑 (워커별 독립 브라우저)"""
    driver = None
    try:
        driver = create_driver()
        comments = scrape_comments(driver, url)
        return url, comments
    except Exception as e:
        print(f"   [워커{worker_id}] 에러 ({url[:40]}): {e}")
        return url, []
    finally:
        if driver:
            driver.quit()


def scrape_all_urls_parallel(unique_urls):
    """
    고유 URL 목록을 병렬 스크래핑.
    반환: { url: [댓글텍스트, ...] }
    """
    url_cache = {}
    total = len(unique_urls)
    completed = 0
    print_lock = Lock()

    def worker(url_idx_pair):
        nonlocal completed
        url, idx = url_idx_pair
        driver = None
        try:
            driver = create_driver()
            comments = scrape_comments(driver, url)
            with print_lock:
                completed += 1
                print(f"   [{completed}/{total}] 댓글 {len(comments)}개 수집 - {url[:50]}...")
            return url, comments
        except Exception as e:
            with print_lock:
                completed += 1
                print(f"   [{completed}/{total}] 에러 - {url[:50]}... ({e})")
            return url, []
        finally:
            if driver:
                driver.quit()

    url_pairs = [(url, i) for i, url in enumerate(unique_urls)]

    with ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
        futures = {executor.submit(worker, pair): pair[0] for pair in url_pairs}
        for future in as_completed(futures):
            url, comments = future.result()
            url_cache[url] = comments

    return url_cache


# ─── 블록 검수 (스크래핑 결과 사용) ────────────────────
def check_block_with_cache(links, comments, url_comments_cache):
    """
    블록 내 모든 링크를 모든 댓글로 체크.
    url_comments_cache: { url: [댓글텍스트, ...] } (이미 스크래핑 완료)
    """
    results = []

    for url in links:
        blog_comments = url_comments_cache.get(url, [])
        blog_norm = [normalize(c) for c in blog_comments]

        # 각 기대 댓글 체크
        comment_results = []
        for expected in comments:
            exp_norm = normalize(expected)
            mc = count_matches(exp_norm, blog_norm)
            dup = f"중복({mc}회)" if mc >= 2 else ""
            miss = "○" if mc == 0 else ""
            comment_results.append((expected, dup, miss))

        # 미등록 댓글 찾기
        expected_norms = [normalize(e) for e in comments]
        unreg = []
        for bc, bc_n in zip(blog_comments, blog_norm):
            matched = any(is_match(en, bc_n) for en in expected_norms)
            if not matched:
                unreg.append(bc)

        results.append({
            'url': url,
            'comment_results': comment_results,
            'unregistered': unreg,
        })

    return results


def build_block_output(col_offset, block_results):
    """
    블록 결과를 묶음 형태의 batch_update 데이터로 변환.

    출력 형태:
      링크열    댓글열    중복열       누락열    미등록열
      링크1     댓글1     중복(2회)
                댓글2                  ○
                댓글3
                                                 미등록댓글1
                                                 미등록댓글2
      링크2     댓글1                  ○
                댓글2     중복(3회)
                ...
    """
    cl = col_letter(col_offset)       # 링크
    cu = col_letter(col_offset + 4)   # 미등록 (범위 끝)

    batch = []
    row = 2  # 1행 = 헤더

    for result in block_results:
        url = result['url']
        crs = result['comment_results']
        unregs = result['unregistered']

        if crs:
            # 첫 행: 링크 + 첫 댓글
            exp, dup, miss = crs[0]
            batch.append({
                "range": f"{cl}{row}:{cu}{row}",
                "values": [[url, exp, dup, miss, ""]],
            })
            row += 1

            # 나머지 댓글
            for exp, dup, miss in crs[1:]:
                batch.append({
                    "range": f"{cl}{row}:{cu}{row}",
                    "values": [["", exp, dup, miss, ""]],
                })
                row += 1
        else:
            batch.append({
                "range": f"{cl}{row}:{cu}{row}",
                "values": [[url, "", "", "", ""]],
            })
            row += 1

        # 미등록 댓글 (내용 그대로 E열에 기록)
        for u in unregs:
            batch.append({
                "range": f"{cl}{row}:{cu}{row}",
                "values": [["", "", "", "", u]],
            })
            row += 1

    return batch, row - 2  # (batch, 총 기록 행 수)


# ─── 메인 ───────────────────────────────────────────────
def main():
    print("=" * 50)
    print("  댓글 검수 프로그램 v2.1 (병렬)")
    print("=" * 50)

    # 1. 시트 연결
    print("\n[1/5] 구글 시트 연결 중...")
    ws = connect_sheet()
    print(f"  시트: {ws.title}")

    # 2. 데이터 파싱
    print("\n[2/5] 시트 데이터 파싱 중...")
    all_values = ws.get_all_values()
    max_row = len(all_values)

    blocks = []
    all_urls = set()
    for bi, offset in enumerate(BLOCK_OFFSETS):
        links, comments = parse_block(all_values, offset)
        if links and comments:
            blocks.append((bi, offset, links, comments))
            all_urls.update(links)
            print(f"  블록 {bi+1} ({col_letter(offset)}열): "
                  f"{len(links)}개 링크, {len(comments)}개 댓글")

    if not blocks:
        print("  검수할 데이터가 없습니다.")
        return

    unique_urls = list(all_urls)
    print(f"\n  총 고유 URL: {len(unique_urls)}개")

    # 3. 병렬 스크래핑
    print(f"\n[3/5] 병렬 스크래핑 시작 (브라우저 {NUM_WORKERS}개)...")
    start_time = time.time()
    url_cache = scrape_all_urls_parallel(unique_urls)
    elapsed = time.time() - start_time
    print(f"  스크래핑 완료 ({elapsed:.1f}초)")

    # 4. 블록별 검수
    print("\n[4/5] 검수 중...")
    all_batch = []
    clear_ranges = []
    stats = {"ok": 0, "dup": 0, "miss": 0, "unreg": 0}

    for bi, offset, links, comments in blocks:
        print(f"  블록 {bi+1} ({col_letter(offset)}열) 검수...")

        results = check_block_with_cache(links, comments, url_cache)
        batch, rows_written = build_block_output(offset, results)
        all_batch.extend(batch)

        # 기존 데이터 클리어 범위 (헤더 제외)
        cl = col_letter(offset)
        cu = col_letter(offset + 4)
        clear_end = max(max_row, rows_written + 1)
        clear_ranges.append(f"{cl}2:{cu}{clear_end}")

        # 통계 집계
        dup_cnt = miss_cnt = ok_cnt = unreg_cnt = 0
        for r in results:
            for _, dup, miss in r['comment_results']:
                if dup:
                    dup_cnt += 1
                elif miss:
                    miss_cnt += 1
                else:
                    ok_cnt += 1
            unreg_cnt += len(r['unregistered'])
        stats["ok"] += ok_cnt
        stats["dup"] += dup_cnt
        stats["miss"] += miss_cnt
        stats["unreg"] += unreg_cnt
        print(f"    정상: {ok_cnt} | 중복: {dup_cnt} | 누락: {miss_cnt} | 미등록: {unreg_cnt}")

    # 5. 시트에 결과 기록
    print("\n[5/5] 결과를 시트에 기록 중...")

    # 필요한 최대 행 수 계산 → 시트 크기 확장
    max_needed_row = 1
    for entry in all_batch:
        r = entry["range"]
        # "A2:E2" 또는 "F150:J150" 형태에서 행 번호 추출
        row_num = int(re.search(r'(\d+)$', r.split(':')[-1]).group(1))
        if row_num > max_needed_row:
            max_needed_row = row_num

    current_rows = ws.row_count
    if max_needed_row > current_rows:
        print(f"  시트 크기 확장: {current_rows}행 → {max_needed_row}행")
        ws.resize(rows=max_needed_row)

    if clear_ranges:
        ws.batch_clear(clear_ranges)
    if all_batch:
        ws.batch_update(all_batch)

    total_time = time.time() - start_time
    print(f"\n{'=' * 50}")
    print(f"  검수 완료! ({total_time:.1f}초)")
    print(f"  정상: {stats['ok']} | 중복: {stats['dup']} "
          f"| 누락: {stats['miss']} | 미등록: {stats['unreg']}")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
