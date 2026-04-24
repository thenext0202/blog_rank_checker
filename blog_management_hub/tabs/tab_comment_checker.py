"""탭 5: 댓글 검수 — 블로그 댓글 중복/누락/미등록 검수 (병렬 스크래핑)
원본: 댓글검수/main.py (v2.1) → GUI 탭으로 변환
"""

import os
import re
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from tkinter import messagebox, ttk

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

from shared.gui_helpers import create_log_area

# ─── 상수 ─────────────────────────────────────────────
MATCH_MIN_LEN = 10
NUM_BLOCKS = 5
BLOCK_WIDTH = 5
BLOCK_OFFSETS = [i * BLOCK_WIDTH for i in range(NUM_BLOCKS)]
NUM_WORKERS = 4


def col_letter(idx):
    return chr(ord('A') + idx)


# ═══════════════════════════════════════════════════════
#  Selenium / 스크래핑 / 매칭 (원본 유지)
# ═══════════════════════════════════════════════════════
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


def switch_to_blog_frame(driver):
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
    driver.get(url)
    time.sleep(3)
    switch_to_blog_frame(driver)
    time.sleep(2)

    try:
        cmt_btn = driver.find_element(By.CSS_SELECTOR, "a._cmtList")
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", cmt_btn)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", cmt_btn)
        time.sleep(3)
    except Exception:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight * 0.7)")
        time.sleep(2)

    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".u_cbox_comment_box"))
        )
    except Exception:
        pass

    try:
        cbox = driver.find_element(By.CSS_SELECTOR, ".u_cbox")
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", cbox)
        time.sleep(1)
    except Exception:
        pass

    expand_all_comments(driver)

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


# ─── 매칭 ─────────────────────────────────────────────
def normalize(text):
    return re.sub(r'\s+', '', text)


def has_common_substring(a, b, min_len):
    if len(a) > len(b):
        a, b = b, a
    for i in range(len(a) - min_len + 1):
        if a[i:i + min_len] in b:
            return True
    return False


def is_match(exp_norm, blog_norm):
    if len(exp_norm) < MATCH_MIN_LEN:
        return exp_norm == blog_norm
    return has_common_substring(exp_norm, blog_norm, MATCH_MIN_LEN)


def count_matches(expected_norm, blog_comments_normalized):
    return sum(1 for c in blog_comments_normalized if is_match(expected_norm, c))


# ─── 블록 파싱/검수/출력 ──────────────────────────────
def parse_block(all_values, col_offset):
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


def check_block_with_cache(links, comments, url_comments_cache):
    results = []
    for url in links:
        blog_comments = url_comments_cache.get(url, [])
        blog_norm = [normalize(c) for c in blog_comments]

        comment_results = []
        for expected in comments:
            exp_norm = normalize(expected)
            mc = count_matches(exp_norm, blog_norm)
            dup = f"중복({mc}회)" if mc >= 2 else ""
            miss = "○" if mc == 0 else ""
            comment_results.append((expected, dup, miss))

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
    cl = col_letter(col_offset)
    cu = col_letter(col_offset + 4)

    batch = []
    row = 2

    for result in block_results:
        url = result['url']
        crs = result['comment_results']
        unregs = result['unregistered']

        if crs:
            exp, dup, miss = crs[0]
            batch.append({
                "range": f"{cl}{row}:{cu}{row}",
                "values": [[url, exp, dup, miss, ""]],
            })
            row += 1
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

        for u in unregs:
            batch.append({
                "range": f"{cl}{row}:{cu}{row}",
                "values": [["", "", "", "", u]],
            })
            row += 1

    return batch, row - 2


# ═══════════════════════════════════════════════════════
#  GUI 탭
# ═══════════════════════════════════════════════════════
class CommentCheckerTab(ttk.Frame):
    """댓글 검수 탭"""

    def __init__(self, parent, sheets_client):
        super().__init__(parent, padding=10)
        self.root = self.winfo_toplevel()
        self.sheets = sheets_client
        self.running = False
        self._build()

    def _build(self):
        # 시트 설정
        f1 = ttk.LabelFrame(self, text="시트 설정", padding=10)
        f1.pack(fill="x", pady=(0, 5))

        row1 = ttk.Frame(f1)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="시트 ID:", width=10).pack(side="left")
        self.sheet_id_var = tk.StringVar(value="14IQ3of3Pe9TI-VNHAKNisxYLNub9DSSH7ZZx2Rnzbj8")
        ttk.Entry(row1, textvariable=self.sheet_id_var, width=50).pack(side="left", padx=5)

        row2 = ttk.Frame(f1)
        row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="탭 이름:", width=10).pack(side="left")
        self.tab_name_var = tk.StringVar(value="댓글 비교")
        ttk.Entry(row2, textvariable=self.tab_name_var, width=30).pack(side="left", padx=5)

        ttk.Button(row2, text="시트 불러오기", command=self._load_sheet).pack(side="left", padx=10)

        # 블록 현황
        f2 = ttk.LabelFrame(self, text="블록 현황", padding=5)
        f2.pack(fill="x", pady=5)

        cols = [
            ("block", "블록", 60),
            ("cols", "열 범위", 80),
            ("links", "링크 수", 60),
            ("comments", "댓글 수", 60),
            ("status", "상태", 80),
        ]
        self.block_tree = ttk.Treeview(
            f2, columns=[c[0] for c in cols], show="headings", height=5,
        )
        for col_id, heading, width in cols:
            self.block_tree.heading(col_id, text=heading)
            self.block_tree.column(col_id, width=width, minwidth=40)
        self.block_tree.pack(fill="x")

        # 결과 요약
        f3 = ttk.LabelFrame(self, text="검수 결과", padding=5)
        f3.pack(fill="x", pady=5)

        self.result_frame = ttk.Frame(f3)
        self.result_frame.pack(fill="x")

        self.lbl_ok = ttk.Label(self.result_frame, text="정상: -", font=("맑은 고딕", 10))
        self.lbl_ok.pack(side="left", padx=10)
        self.lbl_dup = ttk.Label(self.result_frame, text="중복: -", font=("맑은 고딕", 10), foreground="red")
        self.lbl_dup.pack(side="left", padx=10)
        self.lbl_miss = ttk.Label(self.result_frame, text="누락: -", font=("맑은 고딕", 10), foreground="orange")
        self.lbl_miss.pack(side="left", padx=10)
        self.lbl_unreg = ttk.Label(self.result_frame, text="미등록: -", font=("맑은 고딕", 10), foreground="purple")
        self.lbl_unreg.pack(side="left", padx=10)

        # 컨트롤
        f4 = ttk.Frame(self, padding=5)
        f4.pack(fill="x")

        self.btn_run = ttk.Button(f4, text="검수 시작", command=self._start_check)
        self.btn_run.pack(side="left")
        self.btn_stop = ttk.Button(f4, text="중지", command=self._stop, state="disabled")
        self.btn_stop.pack(side="left", padx=5)

        self.progress = ttk.Progressbar(f4, mode="determinate", length=300)
        self.progress.pack(side="left", padx=10)
        self.progress_label = ttk.Label(f4, text="")
        self.progress_label.pack(side="left")

        # 로그
        log_frame, self.log_box, self.log = create_log_area(self, height=10)
        log_frame.pack(fill="both", expand=True, pady=(5, 0))

        # 내부 데이터
        self._blocks = []  # [(bi, offset, links, comments), ...]
        self._ws = None

    def _load_sheet(self):
        sheet_id = self.sheet_id_var.get().strip()
        tab_name = self.tab_name_var.get().strip()
        if not sheet_id or not tab_name:
            messagebox.showwarning("경고", "시트 ID와 탭 이름을 입력하세요.")
            return

        self.log("시트 연결 중...")

        def work():
            try:
                ws = self.sheets.get_worksheet(sheet_id, tab_name)
                all_values = ws.get_all_values()
                self.root.after(0, lambda: self._on_sheet_loaded(ws, all_values))
            except Exception as e:
                self.log(f"[에러] 시트 연결 실패: {e}")

        threading.Thread(target=work, daemon=True).start()

    def _on_sheet_loaded(self, ws, all_values):
        self._ws = ws
        self._all_values = all_values
        self.block_tree.delete(*self.block_tree.get_children())
        self._blocks = []

        for bi, offset in enumerate(BLOCK_OFFSETS):
            links, comments = parse_block(all_values, offset)
            col_range = f"{col_letter(offset)}~{col_letter(offset + 4)}"

            if links and comments:
                self._blocks.append((bi, offset, links, comments))
                self.block_tree.insert("", "end", iid=str(bi), values=(
                    f"블록 {bi+1}", col_range, len(links), len(comments), "대기"
                ))
            else:
                self.block_tree.insert("", "end", iid=str(bi), values=(
                    f"블록 {bi+1}", col_range,
                    len(links) if links else 0,
                    len(comments) if comments else 0,
                    "데이터 없음"
                ))

        all_urls = set()
        for _, _, links, _ in self._blocks:
            all_urls.update(links)

        self.log(f"시트 로드 완료 — {len(self._blocks)}개 블록, 고유 URL {len(all_urls)}개")

    def _start_check(self):
        if not self._blocks:
            messagebox.showwarning("경고", "먼저 시트를 불러오세요.")
            return
        if self.running:
            return

        self.running = True
        self.btn_run.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        threading.Thread(target=self._run_check, daemon=True).start()

    def _stop(self):
        self.running = False
        self.log("중지 요청됨...")

    def _run_check(self):
        # 고유 URL 수집
        all_urls = set()
        for _, _, links, _ in self._blocks:
            all_urls.update(links)
        unique_urls = list(all_urls)

        total = len(unique_urls)
        self.root.after(0, lambda: self.progress.configure(maximum=total))

        # 병렬 스크래핑
        self.log(f"\n병렬 스크래핑 시작 (브라우저 {NUM_WORKERS}개, URL {total}개)...")
        start_time = time.time()

        url_cache = {}
        completed = [0]
        print_lock = Lock()

        def worker(url):
            if not self.running:
                return url, []
            driver = None
            try:
                driver = create_driver()
                comments = scrape_comments(driver, url)
                with print_lock:
                    completed[0] += 1
                    self.log(f"  [{completed[0]}/{total}] 댓글 {len(comments)}개 — {url[:50]}...")
                    self.root.after(0, lambda c=completed[0]: (
                        self.progress.configure(value=c),
                        self.progress_label.configure(text=f"{c}/{total}"),
                    ))
                return url, comments
            except Exception as e:
                with print_lock:
                    completed[0] += 1
                    self.log(f"  [{completed[0]}/{total}] 에러 — {url[:50]}...")
                return url, []
            finally:
                if driver:
                    driver.quit()

        with ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
            futures = {executor.submit(worker, url): url for url in unique_urls}
            for future in as_completed(futures):
                if not self.running:
                    break
                url, comments = future.result()
                url_cache[url] = comments

        elapsed = time.time() - start_time
        self.log(f"스크래핑 완료 ({elapsed:.1f}초)")

        if not self.running:
            self.root.after(0, self._on_check_done)
            return

        # 블록별 검수
        self.log("\n블록별 검수 중...")
        all_batch = []
        clear_ranges = []
        max_row = len(self._all_values)
        stats = {"ok": 0, "dup": 0, "miss": 0, "unreg": 0}

        for bi, offset, links, comments in self._blocks:
            results = check_block_with_cache(links, comments, url_cache)
            batch, rows_written = build_block_output(offset, results)
            all_batch.extend(batch)

            cl = col_letter(offset)
            cu = col_letter(offset + 4)
            clear_end = max(max_row, rows_written + 1)
            clear_ranges.append(f"{cl}2:{cu}{clear_end}")

            ok_cnt = dup_cnt = miss_cnt = unreg_cnt = 0
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

            self.log(f"  블록 {bi+1}: 정상 {ok_cnt} | 중복 {dup_cnt} | 누락 {miss_cnt} | 미등록 {unreg_cnt}")
            self.root.after(0, lambda b=bi, s=f"정상{ok_cnt} 중복{dup_cnt} 누락{miss_cnt}": (
                self.block_tree.set(str(b), "status", s),
            ))

        # 시트 기록
        self.log("\n결과를 시트에 기록 중...")
        try:
            max_needed_row = 1
            for entry in all_batch:
                r = entry["range"]
                row_num = int(re.search(r'(\d+)$', r.split(':')[-1]).group(1))
                if row_num > max_needed_row:
                    max_needed_row = row_num

            if max_needed_row > self._ws.row_count:
                self._ws.resize(rows=max_needed_row)

            if clear_ranges:
                self._ws.batch_clear(clear_ranges)
            if all_batch:
                self._ws.batch_update(all_batch)

            self.log("시트 기록 완료!")
        except Exception as e:
            self.log(f"[에러] 시트 기록 실패: {e}")

        # 결과 표시
        self.root.after(0, lambda: (
            self.lbl_ok.configure(text=f"정상: {stats['ok']}"),
            self.lbl_dup.configure(text=f"중복: {stats['dup']}"),
            self.lbl_miss.configure(text=f"누락: {stats['miss']}"),
            self.lbl_unreg.configure(text=f"미등록: {stats['unreg']}"),
        ))

        total_time = time.time() - start_time
        self.log(f"\n검수 완료! ({total_time:.1f}초)")
        self.log(f"정상: {stats['ok']} | 중복: {stats['dup']} | 누락: {stats['miss']} | 미등록: {stats['unreg']}")

        self.root.after(0, self._on_check_done)

    def _on_check_done(self):
        self.running = False
        self.btn_run.configure(state="normal")
        self.btn_stop.configure(state="disabled")
