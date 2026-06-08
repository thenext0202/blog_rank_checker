"""탭 4: 자동 발행 — 시트 연동 + 저장 템플릿 자동 발행
원본: 블로그 자동발행/blog_auto_publisher.py → GUI 탭으로 변환
blog_post.py, sheets_handler.py는 원본 경로에서 임포트
"""

import json
import os
import re
import threading
import time
import tkinter as tk
from collections import OrderedDict
from tkinter import messagebox, ttk

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from shared.gui_helpers import create_log_area
from shared.paths import BASE_DIR, CREDENTIALS_PATH

# 번들된 자동발행 모듈 (vendor/)
from vendor.blog_post import NaverBlogPoster, find_element_by_selectors
from vendor import sheets_handler


# ═══════════════════════════════════════════════════════
#  템플릿/카테고리/발행 함수 (원본에서 가져옴, input→콜백 변환)
# ═══════════════════════════════════════════════════════
def _count_visible_dim(driver):
    """현재 DOM 에서 보이는 se-popup-dim 레이어 개수 반환."""
    try:
        return driver.execute_script("""
            var dims = document.querySelectorAll(
                '.se-popup-dim, .se-popup-dim-white, .se-popup-dim-dark'
            );
            var n = 0;
            for (var d of dims) {
                var r = d.getBoundingClientRect();
                var cs = window.getComputedStyle(d);
                if (r.width > 0 && r.height > 0
                    && cs.display !== 'none' && cs.visibility !== 'hidden'
                    && cs.opacity !== '0') n++;
            }
            return n;
        """)
    except Exception:
        return 0


def _click_template_confirm(driver, log=print):
    """dim 오버레이에 실제 '확인/적용' 버튼이 있으면 클릭.
    버튼이 없으면(로딩 인디케이터일 가능성) 건드리지 않고 반환.
    """
    if _count_visible_dim(driver) == 0:
        return "no_dim"

    try:
        r = driver.execute_script("""
            var btns = document.querySelectorAll(
                'button.se-popup-button-confirm,'
                + ' button.se-popup-button-apply,'
                + ' button[class*="popup-button-confirm"],'
                + ' button[class*="popup-button-apply"],'
                + ' .se-popup-container button'
            );
            for (var b of btns) {
                var r = b.getBoundingClientRect();
                if (r.width === 0 || r.height === 0) continue;
                var txt = (b.textContent || '').trim();
                var aria = b.getAttribute('aria-label') || '';
                if (/확인|적용|불러오기|예|네/.test(txt + ' ' + aria)) {
                    b.click();
                    return 'clicked:' + (txt || aria || 'btn');
                }
            }
            return 'no_button';
        """)
        if r and str(r).startswith("clicked"):
            log(f"  템플릿 확인 버튼 클릭: {r}")
            time.sleep(0.6)
            return "clicked"
    except Exception as e:
        log(f"  [주의] 확인 버튼 클릭 중 예외: {e}")
    return "loading_or_no_button"


def _wait_for_dim_gone(driver, timeout=60, log=print, template_name=""):
    """dim 오버레이가 DOM에서 보이지 않을 때까지 폴링 대기.
    양이 많은 템플릿은 로딩이 오래 걸리므로 기본 60초까지 기다림.
    10초마다 진행 로그를 찍어 사용자에게 "살아있음"을 알림.
    """
    deadline = time.time() + timeout
    start = time.time()
    last_log = 0.0
    while time.time() < deadline:
        if _count_visible_dim(driver) == 0:
            elapsed = time.time() - start
            if elapsed > 1.0:
                log(f"  템플릿 로딩 완료 ({elapsed:.1f}초)")
            return True
        elapsed = time.time() - start
        if elapsed - last_log >= 10:
            log(f"  템플릿 로딩 중... ({int(elapsed)}초 경과)")
            last_log = elapsed
        time.sleep(0.5)

    # 타임아웃 — 마지막 수단으로 ESC 한 번
    log(f"  [주의] 템플릿 로딩이 {timeout}초 내에 완료되지 않음 — ESC 시도")
    try:
        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        time.sleep(1)
        if _count_visible_dim(driver) == 0:
            log("  ESC 로 dim 레이어 해제됨")
            return True
    except Exception:
        pass
    log("  [!] dim 레이어가 여전히 남아있음 — 제목 클릭 실패 가능")
    return False


def apply_template(driver, template_name, log=print, ask_manual=None):
    """네이버 에디터에서 저장 템플릿 적용"""
    log(f"  템플릿 적용: {template_name}")

    try:
        driver.switch_to.default_content()
    except Exception:
        pass

    # 템플릿 버튼
    selectors = [
        "button[data-name='template']",
        "button.se-template-toolbar-button",
        "//button[contains(., '템플릿')]",
    ]
    template_btn = find_element_by_selectors(driver, selectors, wait=5)
    if not template_btn:
        log("  [!] 템플릿 버튼을 찾지 못했습니다")
        if ask_manual:
            ask_manual(f"'{template_name}' 템플릿을 수동으로 적용해주세요.")
        return False

    template_btn.click()
    time.sleep(0.5)

    # 패널 열림 확인
    driver.execute_script("""
        var btn = document.querySelector('button[data-name="template"]');
        if (btn && btn.classList.contains('se-is-selected')) return true;
        var panel = document.querySelector('[class*="template-panel"], [class*="template_panel"]');
        return panel !== null;
    """)
    time.sleep(0.5)

    # 나의 템플릿 탭
    tab_selectors = [
        "button.se-tab-button[value='my']",
        "//button[contains(text(), '내 템플릿')]",
    ]
    tab = find_element_by_selectors(driver, tab_selectors, wait=2)
    if tab:
        tab.click()
        log("  '내 템플릿' 탭 클릭")
        time.sleep(0.5)

    # 템플릿 선택
    for attempt in range(20):
        try:
            result = driver.execute_script("""
                var name = arguments[0];
                var titles = document.querySelectorAll('strong.se-doc-template-title');
                for (var t of titles) {
                    if (t.textContent.trim() === name) {
                        var link = t.closest('a.se-doc-template');
                        if (link) { link.scrollIntoView({block:'center'}); link.click(); return 'found'; }
                        var li = t.closest('li.se-doc-template-item');
                        if (li) { li.scrollIntoView({block:'center'}); li.click(); return 'found'; }
                        t.click(); return 'found';
                    }
                }
                for (var t of titles) {
                    if (t.textContent.trim().includes(name) || name.includes(t.textContent.trim())) {
                        var link = t.closest('a.se-doc-template');
                        if (link) { link.scrollIntoView({block:'center'}); link.click(); return 'found'; }
                        t.click(); return 'found';
                    }
                }
                var container = document.querySelector(
                    '.se-panel-scroll-area, .se-panel-content, '
                    + '[class*="template"] [class*="scroll"], [class*="panel-body"]'
                );
                if (container) {
                    var before = container.scrollTop;
                    container.scrollTop += 500;
                    if (container.scrollTop === before) return 'end';
                    return 'scrolled';
                }
                return 'no_container';
            """, template_name)

            if result == "found":
                log(f"  템플릿 선택: {template_name}")
                time.sleep(1.5)
                # ① 실제 확인 버튼이 있으면 클릭 (팝업 확인 모달 케이스)
                _click_template_confirm(driver, log=log)
                # ② 로딩 오버레이가 사라질 때까지 최대 60초 대기
                _wait_for_dim_gone(driver, timeout=60, log=log,
                                   template_name=template_name)
                log("  템플릿 적용 완료!")
                return True
            elif result in ("end", "no_container"):
                break
            time.sleep(0.3)
        except Exception:
            break

    log(f"  [!] 템플릿 '{template_name}'을 찾지 못했습니다")
    if ask_manual:
        ask_manual(f"'{template_name}' 템플릿을 수동으로 적용해주세요.")
    return False


def select_category(driver, category_name, log=print):
    if not category_name:
        return True
    log(f"  카테고리 선택: {category_name}")

    cat_selectors = [
        "button[aria-label='카테고리 목록 버튼']",
        "button[class*='selectbox_button']",
    ]
    cat_btn = find_element_by_selectors(driver, cat_selectors, wait=3)
    if not cat_btn:
        log("  [!] 카테고리 드롭다운을 찾지 못했습니다")
        return False

    cat_btn.click()
    time.sleep(0.5)

    try:
        clicked = driver.execute_script("""
            var name = arguments[0];
            var spans = document.querySelectorAll('span[data-testid^="categoryItemText_"]');
            for (var s of spans) {
                if (s.textContent.trim() === name) {
                    var label = s.closest('label[role="button"]');
                    if (label) { label.click(); return true; }
                    s.click(); return true;
                }
            }
            return false;
        """, category_name)
        if clicked:
            log(f"  카테고리 선택 완료: {category_name}")
            time.sleep(0.5)
            return True
    except Exception:
        pass

    log(f"  [!] 카테고리 '{category_name}'을 찾지 못했습니다")
    return False


def set_open_type(driver, is_public, log=print):
    target_id = "open_public" if is_public else "open_private"
    label_text = "전체공개" if is_public else "비공개"
    try:
        label = driver.execute_script("""
            var targetId = arguments[0];
            return document.querySelector('label[for="' + targetId + '"]');
        """, target_id)
        if label:
            label.click()
            log(f"  공개 설정: {label_text}")
            time.sleep(0.3)
            return True
    except Exception:
        pass
    log("  [!] 공개 설정 변경 실패")
    return False


def publish_and_get_url(poster, category="", is_public=False, log=print):
    poster.open_publish_dialog()
    if category:
        select_category(poster.driver, category, log=log)
    set_open_type(poster.driver, is_public, log=log)

    success = poster.confirm_publish()
    if not success:
        return None

    driver = poster.driver
    blog_id = poster.blog_id

    time.sleep(2)
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    current_url = driver.current_url
    match = re.search(r"blog\.naver\.com/[^/]+/(\d{10,})", current_url)
    if match:
        log(f"  발행 URL: {current_url}")
        return current_url

    try:
        log_no = driver.execute_script("""
            var blogId = arguments[0];
            var xhr = new XMLHttpRequest();
            xhr.open('GET',
                'https://blog.naver.com/PostTitleListAsync.naver'
                + '?blogId=' + blogId + '&currentPage=1&countPerPage=1', false);
            xhr.send();
            if (xhr.status === 200) {
                var m = xhr.responseText.match(/"logNo"\\s*:\\s*"(\\d+)"/);
                if (m) return m[1];
            }
            return null;
        """, blog_id)
        if log_no:
            url = f"https://blog.naver.com/{blog_id}/{log_no}"
            log(f"  발행 URL: {url}")
            return url
    except Exception as e:
        log(f"  URL 추출 실패: {e}")

    return None


# ═══════════════════════════════════════════════════════
#  GUI 탭
# ═══════════════════════════════════════════════════════
class AutoPublisherTab(ttk.Frame):
    """자동 발행 탭"""

    def __init__(self, parent, sheets_client):
        super().__init__(parent, padding=10)
        self.root = self.winfo_toplevel()
        self.sheets = sheets_client
        self.poster = None
        self.running = False
        self._manual_event = threading.Event()
        self._config = self._load_config()
        self._build()

    def _load_config(self):
        """자동발행 config.json 로드 (EXE/스크립트 루트 옆)"""
        config_path = os.path.join(BASE_DIR, "auto_publisher_config.json")
        # 기본 컬럼 매핑: 시트 B~G열 = 블로그ID/키워드/제목/URL/카테고리/공개
        defaults = {
            "sheet_id": "",
            "tab_name": "블로그 템플릿 발행",
            "blog_id_col": "B",
            "keyword_col": "C",
            "title_col": "D",
            "publish_url_col": "E",
            "start_row": 2,
            "credentials_path": CREDENTIALS_PATH,
            "template_name_col": "C",
            "category_col": "F",
            "public_col": "G",
            "skip_title_input": False,
            "publish_delay_sec": 3,
        }
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            defaults.update(saved)
        return defaults

    def _build(self):
        # 시트 설정
        f1 = ttk.LabelFrame(self, text="시트 설정", padding=10)
        f1.pack(fill="x", pady=(0, 5))

        row1 = ttk.Frame(f1)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="시트 ID:", width=10).pack(side="left")
        self.sheet_id_var = tk.StringVar(value=self._config.get("sheet_id", ""))
        ttk.Entry(row1, textvariable=self.sheet_id_var, width=50).pack(side="left", padx=5)

        row2 = ttk.Frame(f1)
        row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="탭 이름:", width=10).pack(side="left")
        self.tab_name_var = tk.StringVar(value=self._config.get("tab_name", ""))
        ttk.Entry(row2, textvariable=self.tab_name_var, width=30).pack(side="left", padx=5)
        ttk.Button(row2, text="대기 목록 불러오기", command=self._load_pending).pack(side="left", padx=10)

        # 로그인
        f_login = ttk.Frame(f1)
        f_login.pack(fill="x", pady=2)
        ttk.Button(f_login, text="네이버 로그인", command=self._login).pack(side="left")
        self.login_status = ttk.Label(f_login, text="미로그인", foreground="red")
        self.login_status.pack(side="left", padx=10)

        # 데이터 테이블
        f2 = ttk.LabelFrame(self, text="발행 대기 목록", padding=5)
        f2.pack(fill="both", expand=True, pady=5)

        cols = [
            ("row", "행", 40),
            ("blog_id", "블로그ID", 100),
            ("template", "템플릿", 150),
            ("title", "제목", 200),
            ("category", "카테고리", 80),
            ("public", "공개", 60),
            ("status", "상태", 80),
            ("url", "발행URL", 200),
        ]
        tree_frame = ttk.Frame(f2)
        tree_frame.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(
            tree_frame, columns=[c[0] for c in cols], show="headings", height=10,
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

        self.tree.tag_configure("ok", background="#d4edda")
        self.tree.tag_configure("error", background="#f8d7da")
        self.tree.tag_configure("processing", background="#cce5ff")

        # 컨트롤
        f3 = ttk.Frame(self, padding=5)
        f3.pack(fill="x")

        self.btn_run = ttk.Button(f3, text="발행 시작", command=self._start_publish)
        self.btn_run.pack(side="left")
        self.btn_stop = ttk.Button(f3, text="중지", command=self._stop, state="disabled")
        self.btn_stop.pack(side="left", padx=5)

        self.progress_label = ttk.Label(f3, text="")
        self.progress_label.pack(side="left", padx=10)

        # 로그
        log_frame, self.log_box, self.log = create_log_area(self, height=8)
        log_frame.pack(fill="x", pady=(5, 0))

        # 내부 데이터
        self._pending = []
        self._ws = None

    def _load_pending(self):
        sheet_id = self.sheet_id_var.get().strip()
        tab_name = self.tab_name_var.get().strip()
        if not sheet_id or not tab_name:
            messagebox.showwarning("경고", "시트 ID와 탭 이름을 입력하세요.")
            return

        self.log("시트 연결 중...")
        config = dict(self._config)
        config["sheet_id"] = sheet_id
        config["tab_name"] = tab_name

        def work():
            try:
                cred_path = config["credentials_path"]
                if not os.path.isabs(cred_path):
                    cred_path = os.path.normpath(os.path.join(BASE_DIR, cred_path))
                if not os.path.exists(cred_path):
                    self.log(f"[에러] 인증 파일 없음: {cred_path}")
                    return
                ws = sheets_handler.connect(sheet_id, tab_name, cred_path)
                if not ws:
                    self.log("[에러] 시트 연결 실패 — 시트 ID, 탭 이름, 서비스 계정 공유 확인")
                    return
                self.log(f"시트 연결 성공")
                pending = sheets_handler.get_pending_rows(ws, config)
                if not pending:
                    self.log(f"[주의] 대기 건수 0건 — 시트에 데이터가 없거나 모두 발행 완료")
                self.root.after(0, lambda: self._on_pending_loaded(ws, pending))
            except Exception as e:
                self.log(f"[에러] {e}")

        threading.Thread(target=work, daemon=True).start()

    def _on_pending_loaded(self, ws, pending):
        self._ws = ws
        self._pending = pending
        self.tree.delete(*self.tree.get_children())

        for p in pending:
            pub_text = "전체공개" if p.get("is_public") else "비공개"
            self.tree.insert("", "end", iid=str(p["row_num"]), values=(
                p["row_num"], p["blog_id"], p.get("template_name", "")[:30],
                p["title"][:40], p.get("category", ""), pub_text, "대기", ""
            ))

        self.log(f"대기 목록 로드 — {len(pending)}건")

    def _login(self):
        self.log("브라우저 열기 중...")

        def work():
            try:
                first_bid = self._pending[0]["blog_id"] if self._pending else "login"
                self.poster = NaverBlogPoster(blog_id=first_bid)
                self.poster.driver = self.poster.create_driver(headless=False)
                self.poster.driver.get("https://nid.naver.com/nidlogin.login")
                self.root.after(0, lambda: self.login_status.configure(
                    text="로그인 페이지 열림", foreground="orange"
                ))
                self.root.after(0, self._show_login_confirm)
            except Exception as e:
                self.log(f"[에러] 브라우저 열기 실패: {e}")

        threading.Thread(target=work, daemon=True).start()

    def _show_login_confirm(self):
        messagebox.showinfo("네이버 로그인", "네이버에 로그인한 후 확인을 눌러주세요.")
        self.login_status.configure(text="로그인 완료", foreground="green")
        self.log("네이버 로그인 완료")

    def _ask_manual(self, msg):
        self._manual_event.clear()

        def show():
            messagebox.showinfo("수동 처리 필요", msg)
            self._manual_event.set()

        self.root.after(0, show)
        self._manual_event.wait()

    def _start_publish(self):
        if not self._pending:
            messagebox.showwarning("경고", "먼저 대기 목록을 불러오세요.")
            return
        if not self.poster or not self.poster.driver:
            messagebox.showwarning("경고", "먼저 네이버 로그인을 해주세요.")
            return
        if self.running:
            return

        self.running = True
        self.btn_run.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        threading.Thread(target=self._run_publish, daemon=True).start()

    def _stop(self):
        self.running = False
        self.log("중지 요청됨...")

    def _run_publish(self):
        config = dict(self._config)
        config["sheet_id"] = self.sheet_id_var.get().strip()
        config["tab_name"] = self.tab_name_var.get().strip()
        skip_title = config.get("skip_title_input", False)
        publish_delay = config.get("publish_delay_sec", 3)

        total = len(self._pending)
        success_count = 0
        fail_count = 0

        try:
            for idx, row in enumerate(self._pending):
                if not self.running:
                    break

                row_num = row["row_num"]
                title = row["title"]
                template_name = row.get("template_name", title)
                category = row.get("category", "")
                is_public = row.get("is_public", False)
                blog_id = row["blog_id"]

                self.poster.blog_id = blog_id

                self.root.after(0, lambda r=row_num: (
                    self.tree.set(str(r), "status", "진행중"),
                    self.tree.item(str(r), tags=("processing",)),
                ))
                self.root.after(0, lambda i=idx: self.progress_label.configure(
                    text=f"{i+1}/{total}"
                ))

                self.log(f"\n[{idx+1}/{total}] 행{row_num}: [{blog_id}] {title[:40]}")

                try:
                    self.poster.navigate_to_editor()

                    template_applied = apply_template(
                        self.poster.driver, template_name,
                        log=self.log, ask_manual=self._ask_manual
                    )

                    if not skip_title:
                        self.poster.input_title(title)
                    elif not template_applied:
                        self.poster.input_title(title)

                    url = publish_and_get_url(
                        self.poster, category=category,
                        is_public=is_public, log=self.log
                    )

                    if url:
                        sheets_handler.write_url(
                            self._ws, row_num, config["publish_url_col"], url
                        )
                        success_count += 1
                        tag = "ok"
                        status = "완료"
                    else:
                        sheets_handler.write_url(
                            self._ws, row_num, config["publish_url_col"],
                            "발행완료(URL미확인)"
                        )
                        success_count += 1
                        tag = "ok"
                        status = "완료(URL미확인)"
                        url = ""

                except Exception as e:
                    fail_count += 1
                    tag = "error"
                    status = "실패"
                    url = ""
                    self.log(f"  [!] 오류: {e}")

                self.root.after(0, lambda r=row_num, s=status, t=tag, u=url: (
                    self.tree.set(str(r), "status", s),
                    self.tree.set(str(r), "url", u[:50] if u else ""),
                    self.tree.item(str(r), tags=(t,)),
                ))

                if idx < total - 1:
                    time.sleep(publish_delay)

        except Exception as e:
            self.log(f"[에러] {e}")

        self.log(f"\n완료: 성공 {success_count}건, 실패 {fail_count}건")
        self.root.after(0, self._on_publish_done)

    def _on_publish_done(self):
        self.running = False
        self.btn_run.configure(state="normal")
        self.btn_stop.configure(state="disabled")
