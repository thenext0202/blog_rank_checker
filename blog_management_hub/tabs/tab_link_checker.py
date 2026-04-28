"""탭 3: MKT 링크 대조 — 블로그 내 MKT 링크 추출 + 상품 링크 일치 검증
원본: 블로그 mkt 링크 대조/blog_link_extractor.py → GUI 탭으로 변환
"""

import html
import os
import re
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk
from urllib.parse import unquote, urlparse, parse_qs

import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from shared.browser_manager import create_headless_driver
from shared.gui_helpers import create_log_area
from shared.sheets_client import normalize_sheet_id

# ═══════════════════════════════════════════════════════
#  MKT 링크 추출/검증 로직
# ═══════════════════════════════════════════════════════
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
    """블로그 페이지에서 mkt.shopping.naver.com 링크 추출"""
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

    # 1차: 카드 외곽 컨테이너 단위 — Naver SE는 카드가 3중 중첩이라
    # 외곽(div.se-component.se-oglink)만 잡아야 카드 1개당 1번 처리됨
    container_fallback_selectors = [
        "div.se-component.se-oglink",   # 외곽 (대부분 케이스)
        "div.se-section-oglink",        # 외곽 못 잡을 때 폴백
        "div.se-module-oglink",         # 그것도 안되면 최종 폴백
    ]
    for sel in container_fallback_selectors:
        try:
            containers = driver.find_elements(By.CSS_SELECTOR, sel)
        except Exception:
            containers = []
        if not containers:
            continue

        for container in containers:
            # 컨테이너 안에서 첫 상품 URL 1개만 추출
            url = None
            try:
                anchors = container.find_elements(By.CSS_SELECTOR, "a")
            except Exception:
                anchors = []
            for a in anchors:
                data = a.get_attribute("data-linkdata") or ""
                if data:
                    for u in re.findall(r"https?://[^\s\"'<>\\,}]+", data):
                        cleaned = _clean_product_url(u)
                        if cleaned:
                            url = cleaned
                            break
                if not url:
                    href = a.get_attribute("href") or ""
                    url = _clean_product_url(href)
                if url:
                    break

            if url:
                mkt_links.append(url)
        # 1개 셀렉터로 잡았으면 다음 셀렉터로 안 넘어감 (중첩 중복 방지)
        break

    # 2차 폴백: 카드 셀렉터로 못 잡았을 때만 — 광범위 셀렉터 + URL 중복 제거
    if not mkt_links:
        broad_selectors = [
            "div.se-main-container a",
            "div#postViewArea a",
            "a.se-link",
        ]
        seen_urls = set()
        for sel in broad_selectors:
            try:
                for el in driver.find_elements(By.CSS_SELECTOR, sel):
                    href = el.get_attribute("href") or ""
                    cleaned = _clean_product_url(href)
                    if cleaned and cleaned not in seen_urls:
                        seen_urls.add(cleaned)
                        mkt_links.append(cleaned)
            except Exception:
                continue

    # 3차 폴백: DOM에서 전혀 못 잡으면 페이지 소스 정규식
    if not mkt_links:
        try:
            source = driver.page_source
            patterns = [
                r'https?://mkt\.shopping\.naver\.com/link/[^\s"\'<>\\,}]+',
                r'https?://brand\.naver\.com/[^/\s"\'<>\\]+/products/\d+[^\s"\'<>\\,}]*',
                r'https?://smartstore\.naver\.com/[^/\s"\'<>\\]+/products/\d+[^\s"\'<>\\,}]*',
            ]
            seen_urls = set()
            for pat in patterns:
                for url in re.findall(pat, source):
                    cleaned = _clean_product_url(url)
                    if cleaned and cleaned not in seen_urls:
                        seen_urls.add(cleaned)
                        mkt_links.append(cleaned)
        except Exception:
            pass

    return mkt_links


# 상품 링크로 인정되는 도메인
PRODUCT_DOMAINS = (
    "mkt.shopping.naver.com",
    "brand.naver.com",
    "smartstore.naver.com",
)


def _clean_product_url(href):
    """URL 정제 — HTML 엔티티/URL 인코딩 풀고, 잡문자 제거, NaPm 추적값 제거.
    상품 도메인이 아니면 빈 문자열 반환."""
    if not href:
        return ""
    # HTML 엔티티 반복 디코딩 (이중 인코딩 대비: &amp;#38; → &#38; → &)
    prev = None
    while href != prev:
        prev = href
        href = html.unescape(href)
    href = unquote(href).strip()
    # URL 끝 잡문자 제거 (따옴표·괄호·콤마 등 페이지 소스에서 따라옴)
    href = re.split(r'[\s"\'<>\\,}]', href, maxsplit=1)[0]
    if not any(d in href for d in PRODUCT_DOMAINS):
        return ""
    # NaPm(자동 추적값) 제거 — 매번 달라지는 값
    return re.sub(r"[&?]NaPm=[^&]*", "", href)


def resolve_mkt_link(mkt_url):
    """MKT 링크 리다이렉트 최종 URL 반환"""
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
    """경로만 정규화 (쿼리 제거, scheme/www/m 제거)"""
    url = unquote(url).strip()
    url = re.sub(r"\?.*", "", url)
    url = re.sub(r"^https?://", "", url)
    url = re.sub(r"^(www\.|m\.)", "", url)
    return url.rstrip("/").lower()


def _ensure_resolved(url):
    """mkt 단축링크면 풀어서 최종 brand/smartstore URL 반환. 이미 직링크면 그대로."""
    if not url:
        return ""
    if "mkt.shopping.naver.com/link/" in url:
        resolved = resolve_mkt_link(url)
        return resolved or url
    return url


def _extract_product_key(url):
    """비교용 키 추출 — (정규화된 path, nt_keyword 값)"""
    norm_path = normalize_product_url(url)
    # nt_keyword 추출 (원본 url에서 — 정규화 전)
    try:
        qs = parse_qs(urlparse(url).query)
        nt_keyword = unquote(qs.get("nt_keyword", [""])[0]).strip().lower()
    except Exception:
        nt_keyword = ""
    return norm_path, nt_keyword


def check_match(mkt_url, real_url):
    if not mkt_url or not real_url:
        return ""

    # 양쪽 다 mkt 단축링크면 풀어서 직링크로 변환
    resolved_mkt = _ensure_resolved(mkt_url)
    resolved_real = _ensure_resolved(real_url)

    if not resolved_mkt or not resolved_real:
        return "확인불가"

    path_mkt, kw_mkt = _extract_product_key(resolved_mkt)
    path_real, kw_real = _extract_product_key(resolved_real)

    # path 비교 — 전체 경로 같거나, products/숫자 ID가 같으면 동일 상품
    same_product = False
    if path_mkt == path_real:
        same_product = True
    else:
        m1 = re.search(r"products/(\d+)", path_mkt)
        m2 = re.search(r"products/(\d+)", path_real)
        if m1 and m2 and m1.group(1) == m2.group(1):
            same_product = True

    if not same_product:
        return "불일치"

    # 상품은 같음 → nt_keyword까지 비교
    if kw_mkt != kw_real:
        return "불일치"

    return "일치"


# ═══════════════════════════════════════════════════════
#  GUI 탭
# ═══════════════════════════════════════════════════════
class LinkCheckerTab(ttk.Frame):
    """MKT 링크 대조 탭"""

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
        self.sheet_id_var = tk.StringVar(value="")
        ttk.Entry(row1, textvariable=self.sheet_id_var, width=50).pack(side="left", padx=5)

        row2 = ttk.Frame(f1)
        row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="탭 이름:", width=10).pack(side="left")
        self.tab_name_var = tk.StringVar(value="링크대조")
        ttk.Entry(row2, textvariable=self.tab_name_var, width=30).pack(side="left", padx=5)

        ttk.Button(row2, text="시트 불러오기", command=self._load_sheet).pack(side="left", padx=10)

        # 데이터 테이블
        f2 = ttk.LabelFrame(self, text="데이터", padding=5)
        f2.pack(fill="both", expand=True, pady=5)

        cols = [
            ("row", "행", 40),
            ("blog", "블로그 링크", 250),
            ("real", "실제 상품 링크", 200),
            ("mkt1", "MKT 링크 1", 200),
            ("match1", "일치1", 60),
            ("mkt2", "MKT 링크 2", 200),
            ("match2", "일치2", 60),
        ]
        tree_frame = ttk.Frame(f2)
        tree_frame.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(
            tree_frame,
            columns=[c[0] for c in cols],
            show="headings",
            height=10,
        )
        for col_id, heading, width in cols:
            self.tree.heading(col_id, text=heading)
            self.tree.column(col_id, width=width, minwidth=40)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        # 색상 태그
        self.tree.tag_configure("ok", background="#d4edda")
        self.tree.tag_configure("error", background="#f8d7da")
        self.tree.tag_configure("warn", background="#fff3cd")
        self.tree.tag_configure("processing", background="#cce5ff")

        # 컨트롤
        f3 = ttk.Frame(self, padding=5)
        f3.pack(fill="x")

        self.btn_run = ttk.Button(f3, text="검사 시작", command=self._start_check)
        self.btn_run.pack(side="left")

        self.btn_stop = ttk.Button(f3, text="중지", command=self._stop, state="disabled")
        self.btn_stop.pack(side="left", padx=5)

        self.progress = ttk.Progressbar(f3, mode="determinate", length=300)
        self.progress.pack(side="left", padx=10)

        self.progress_label = ttk.Label(f3, text="")
        self.progress_label.pack(side="left")

        # 로그
        log_frame, self.log_box, self.log = create_log_area(self, height=8)
        log_frame.pack(fill="x", pady=(5, 0))

        # 내부 데이터
        self._rows_data = []  # [(row_num, blog_url, real_url), ...]

    def _load_sheet(self):
        """시트에서 데이터 불러오기"""
        sheet_id = normalize_sheet_id(self.sheet_id_var.get())
        tab_name = self.tab_name_var.get().strip()
        if not sheet_id or not tab_name:
            messagebox.showwarning("경고", "시트 ID와 탭 이름을 입력하세요.")
            return

        self.log("시트 연결 중...")

        def work():
            try:
                ws = self.sheets.get_worksheet(sheet_id, tab_name)
                all_data = ws.get_all_values()
                self.root.after(0, lambda: self._on_sheet_loaded(all_data))
            except Exception as e:
                self.log(f"[에러] 시트 연결 실패: {e}")

        threading.Thread(target=work, daemon=True).start()

    def _on_sheet_loaded(self, all_data):
        """시트 데이터 로드 완료"""
        self.tree.delete(*self.tree.get_children())
        self._rows_data = []

        if len(all_data) < 2:
            self.log("데이터가 없습니다.")
            return

        for i, row in enumerate(all_data[1:], start=2):
            g_val = row[0] if len(row) > 0 else ""  # A열 (블로그 링크)
            f_val = row[1] if len(row) > 1 else ""  # B열 (실제 상품 링크)
            if g_val.strip():
                self._rows_data.append((i, g_val.strip(), f_val.strip()))
                self.tree.insert("", "end", iid=str(i), values=(
                    i, g_val.strip()[:60], f_val.strip()[:50], "", "", "", ""
                ))

        self.log(f"시트 로드 완료 — {len(self._rows_data)}개 블로그 링크")

    def _start_check(self):
        """MKT 링크 추출 + 일치 검증 시작"""
        if not self._rows_data:
            messagebox.showwarning("경고", "먼저 시트를 불러오세요.")
            return
        if self.running:
            return

        self.running = True
        self.btn_run.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.progress["value"] = 0
        self.progress["maximum"] = len(self._rows_data)

        threading.Thread(target=self._run_check, daemon=True).start()

    def _stop(self):
        self.running = False
        self.log("중지 요청됨...")

    def _run_check(self):
        """백그라운드: MKT 링크 추출 + 검증"""
        sheet_id = normalize_sheet_id(self.sheet_id_var.get())
        tab_name = self.tab_name_var.get().strip()

        self.log("브라우저 시작 중...")
        driver = None
        ws = None

        try:
            driver = create_headless_driver()
            ws = self.sheets.get_worksheet(sheet_id, tab_name)
        except Exception as e:
            self.log(f"[에러] 초기화 실패: {e}")
            self.root.after(0, self._on_check_done)
            return

        total = len(self._rows_data)
        try:
            for idx, (row_num, blog_url, real_url) in enumerate(self._rows_data):
                if not self.running:
                    break

                self.log(f"[{idx+1}/{total}] {blog_url[:70]}...")
                self.root.after(0, lambda i=idx: self._update_progress(i, total))

                # 현재 행 파란색
                self.root.after(0, lambda r=row_num: self._set_row_tag(r, "processing"))

                # MKT 링크 추출
                mkt_links = extract_mkt_links(driver, blog_url)
                mkt1 = mkt_links[0] if len(mkt_links) > 0 else ""
                mkt2 = mkt_links[1] if len(mkt_links) > 1 else ""
                self.log(f"  → MKT 링크 {len(mkt_links)}개 발견")

                # 일치 검증
                match1 = check_match(mkt1, real_url) if mkt1 else ""
                match2 = check_match(mkt2, real_url) if mkt2 else ""

                # 시트에 기입
                try:
                    ws.update(f"C{row_num}:F{row_num}", [[mkt1, match1, mkt2, match2]])
                except Exception as e:
                    self.log(f"  [에러] 시트 기입 실패: {e}")

                # 테이블 업데이트
                tag = self._get_match_tag(match1, match2)
                self.root.after(0, lambda r=row_num, m1=mkt1, mt1=match1, m2=mkt2, mt2=match2, t=tag: (
                    self.tree.set(str(r), "mkt1", m1[:40] if m1 else ""),
                    self.tree.set(str(r), "match1", mt1),
                    self.tree.set(str(r), "mkt2", m2[:40] if m2 else ""),
                    self.tree.set(str(r), "match2", mt2),
                    self._set_row_tag(r, t),
                ))

                time.sleep(0.5)

        except Exception as e:
            self.log(f"[에러] {e}")
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

        self.root.after(0, self._on_check_done)

    def _get_match_tag(self, match1, match2):
        """일치 결과에 따른 태그 결정"""
        results = [r for r in [match1, match2] if r]
        if not results:
            return "warn"
        if "불일치" in results:
            return "error"
        if "확인불가" in results:
            return "warn"
        return "ok"

    def _set_row_tag(self, row_num, tag):
        try:
            self.tree.item(str(row_num), tags=(tag,))
        except Exception:
            pass

    def _update_progress(self, current, total):
        self.progress["value"] = current + 1
        self.progress_label.configure(text=f"{current+1}/{total}")

    def _on_check_done(self):
        self.running = False
        self.btn_run.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.log("검사 완료!")
