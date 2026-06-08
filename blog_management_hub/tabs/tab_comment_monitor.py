"""탭 2: 댓글 알림 — 네이버 블로그/카페 모니터링 + Slack 알림
원본: 댓글알림/main.py (v2.3) → ttk.Frame 으로 변환
- 블로그: 새 댓글 + 비공개 조치 감지
- 카페: 비공개 조치(블라인드)만 감지 (댓글 X)
"""

import json
import os
import re
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, scrolledtext, ttk

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

from shared.paths import BASE_DIR

# ─── 경로 ─────────────────────────────────────────────
STATE_FILE = os.path.join(BASE_DIR, "comment_state.json")
CONFIG_FILE = os.path.join(BASE_DIR, "comment_config.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
}


def parse_post_url(url):
    """블로그 URL → (blog_id, log_no). 실패 시 None."""
    url = url.strip()
    m = re.search(r'blog\.naver\.com/([^/?#]+)/(\d+)', url)
    if m:
        return m.group(1), m.group(2)
    return None


def parse_cafe_url(url):
    """카페 URL → (cafe_slug, article_id). 실패 시 None.
    지원: https://cafe.naver.com/{slug}/{articleId}
    """
    url = url.strip()
    m = re.search(r'cafe\.naver\.com/([^/?#]+)/(\d+)', url)
    if m:
        return m.group(1), m.group(2)
    return None


def classify_url(url):
    """URL 종류 판별. 'blog' | 'cafe' | None"""
    if parse_cafe_url(url):
        return "cafe"
    if parse_post_url(url):
        return "blog"
    return None


# ═══════════════════════════════════════════════════════
#  Selenium 드라이버
# ═══════════════════════════════════════════════════════
def create_driver():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-software-rasterizer")
    opts.add_argument("--disable-background-networking")
    opts.add_argument("--disable-renderer-backgrounding")
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
        {
            "source": (
                "Object.defineProperty(navigator,'webdriver',"
                "{get:()=>undefined})"
            )
        },
    )
    driver.set_page_load_timeout(15)
    driver.implicitly_wait(3)
    return driver


# ═══════════════════════════════════════════════════════
#  모니터링 엔진
# ═══════════════════════════════════════════════════════
class BlogMonitor:
    def __init__(self, log_fn=print):
        self.log = log_fn
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.config = self._load(CONFIG_FILE, {
            "posts": [],
            "slack_webhook": "",
            "interval_minutes": 30,
        })
        self.state = self._load(STATE_FILE, {
            "seen": {},
            "comment_counts": {},
        })
        self.state.setdefault("seen", {})
        self.state.setdefault("comment_counts", {})
        self.state.setdefault("cafe_club_ids", {})  # slug → clubId 캐시
        self.driver = None
        self._baseline_done = False

    @staticmethod
    def _load(path, default):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return default.copy()

    def _save(self, path, data):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def save_config(self):
        self._save(CONFIG_FILE, self.config)

    def save_state(self):
        self._save(STATE_FILE, self.state)

    # ── Selenium 관리 ─────────────────────────────────
    def _ensure_driver(self):
        if self.driver is None:
            self.log("  브라우저 시작 중...")
            self.driver = create_driver()

    def _quit_driver(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

    # ── commentCount + 비공개 체크 ────────────────────
    def _fetch_comment_count_direct(self, blog_id, log_no):
        url = f"https://m.blog.naver.com/{blog_id}/{log_no}"
        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Linux; Android 10; SM-G981B) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/80.0.3987.162 Mobile Safari/537.36"
                ),
            }
            r = self.session.get(url, headers=headers, timeout=10)
            html = r.text

            private_info = None
            pm = re.search(
                r'(.+?)의\s*요청에\s*따라\s*비공개\s*조치', html
            )
            if pm:
                agency = pm.group(1).strip()
                agency = re.sub(r'^.*?(?:위해|따른)\s*', '', agency).strip()
                private_info = {"agency": agency}

            cc = None
            cm = re.search(r'commentCount="(\d+)"', html)
            if cm:
                cc = int(cm.group(1))

            return cc, private_info
        except Exception as e:
            self.log(f"  [에러] 상태 조회 {blog_id}/{log_no}: {e}")
        return None, None

    def _fetch_private_detail(self, blog_id, log_no):
        url = (
            f"https://blog.naver.com/PostView.naver"
            f"?blogId={blog_id}&logNo={log_no}"
        )
        try:
            r = self.session.get(url, timeout=10)
            html = r.text
            pm = re.search(
                r'이 게시물은\s+(.+?)의?\s*요청으로\s*비공개\s*조치\s*되었습니다',
                html
            )
            if pm:
                agency = pm.group(1).strip()
                dm = re.search(
                    r'요청\s*일자.*?(\d{4}\.\d{2}\.\d{2})',
                    html, re.DOTALL
                )
                req_date = dm.group(1) if dm else "알 수 없음"
                return {"agency": agency, "date": req_date}
        except Exception as e:
            self.log(f"  [에러] 비공개 상세 {blog_id}/{log_no}: {e}")
        return None

    # ── 카페 clubId 조회 (캐싱) ───────────────────────
    def _get_cafe_club_id(self, cafe_slug):
        """카페 slug → clubId. state에 캐싱."""
        cache = self.state["cafe_club_ids"]
        if cafe_slug in cache:
            return cache[cafe_slug]
        try:
            r = self.session.get(
                f"https://cafe.naver.com/{cafe_slug}", timeout=10
            )
            m = re.search(r'g_sClubId\s*=\s*["\']?(\d+)', r.text)
            if not m:
                m = re.search(r'clubid["\':=\s]+(\d+)', r.text, re.I)
            if m:
                club_id = m.group(1)
                cache[cafe_slug] = club_id
                self.save_state()
                return club_id
        except Exception as e:
            self.log(f"  [에러] clubId 조회 {cafe_slug}: {e}")
        return None

    # ── 카페 글 비공개 감지 (API) ─────────────────────
    def _fetch_cafe_blind_info(self, club_id, article_id):
        """카페 글 상태 조회.
        반환: ("ok", None) | ("blind", {agency, reason, date}) |
              ("member_only", None) | ("error", None)
        """
        url = (
            f"https://apis.naver.com/cafe-web/cafe-articleapi/"
            f"cafes/{club_id}/articles/{article_id}"
        )
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 10) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Mobile Safari/537.36"
            ),
            "Referer": "https://m.cafe.naver.com/",
            "X-Cafe-Product": "pc",
        }
        try:
            r = self.session.get(url, headers=headers, timeout=10)
            # 401: 로그인 필요한 카페의 일반 글 (비공개 아님)
            if r.status_code == 401:
                return "member_only", None
            if r.status_code != 200:
                return "error", None
            data = r.json()
            article = data.get("article") or \
                data.get("result", {}).get("article")
            if not article:
                return "error", None
            blind = article.get("blindInfo")
            if blind:
                return "blind", {
                    "agency": blind.get("requester", "알 수 없음"),
                    "reason": blind.get("reason", ""),
                    "date": blind.get("requestDateToStr")
                        or blind.get("requestDate", "알 수 없음"),
                }
            return "ok", None
        except Exception as e:
            self.log(
                f"  [에러] 카페 API {club_id}/{article_id}: {e}"
            )
            return "error", None

    # ── 댓글 스크래핑 ────────────────────────────────
    def _switch_to_blog_frame(self):
        self.driver.switch_to.default_content()
        try:
            iframe = WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.ID, "mainFrame"))
            )
            self.driver.switch_to.frame(iframe)
            return True
        except Exception:
            pass
        try:
            for iframe in self.driver.find_elements(By.TAG_NAME, "iframe"):
                src = iframe.get_attribute("src") or ""
                if "PostView" in src or "post" in src.lower():
                    self.driver.switch_to.frame(iframe)
                    return True
        except Exception:
            pass
        return False

    def _expand_all_comments(self):
        for _ in range(10):
            clicked = False
            for sel in [
                ".u_cbox_btn_more",
                ".u_cbox_page_more",
                "a.u_cbox_btn_view_comment",
                "button.u_cbox_btn_more",
            ]:
                try:
                    for btn in self.driver.find_elements(By.CSS_SELECTOR, sel):
                        if btn.is_displayed():
                            self.driver.execute_script(
                                "arguments[0].click();", btn
                            )
                            time.sleep(0.5)
                            clicked = True
                            break
                except Exception:
                    pass
                if clicked:
                    break
            if not clicked:
                break

    def get_comments(self, blog_id, log_no):
        post_url = f"https://blog.naver.com/{blog_id}/{log_no}"
        try:
            try:
                self.driver.get(post_url)
            except Exception:
                pass

            time.sleep(1)

            try:
                alert = self.driver.switch_to.alert
                alert.accept()
                time.sleep(0.3)
                return None
            except Exception:
                pass

            try:
                title = self.driver.title or ""
            except Exception:
                return None
            if "삭제" in title or "없는" in title:
                return None

            if not self._switch_to_blog_frame():
                return None

            time.sleep(0.5)

            try:
                cmt_btn = self.driver.find_element(
                    By.CSS_SELECTOR, "a._cmtList"
                )
                self.driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center'});", cmt_btn,
                )
                time.sleep(0.3)
                self.driver.execute_script("arguments[0].click();", cmt_btn)
                time.sleep(1)
            except Exception:
                self.driver.execute_script(
                    "window.scrollTo(0, document.body.scrollHeight * 0.7)"
                )
                time.sleep(0.5)

            try:
                WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, ".u_cbox_comment_box")
                    )
                )
            except Exception:
                pass

            self._expand_all_comments()

            comment_elements = []
            for sel in [
                ".u_cbox_comment_box",
                "li.u_cbox_comment",
                ".comment_item",
            ]:
                comment_elements = self.driver.find_elements(
                    By.CSS_SELECTOR, sel
                )
                if comment_elements:
                    break

            comments = []
            for elem in comment_elements:
                try:
                    comment = self._extract_comment(elem)
                    if comment:
                        comments.append(comment)
                except Exception:
                    continue

            self.driver.switch_to.default_content()
            return comments

        except Exception as e:
            err_msg = str(e)
            self.log(
                f"  [에러] 스크래핑 {blog_id}/{log_no}: {err_msg[:80]}"
            )
            if "crash" in err_msg.lower() or "session" in err_msg.lower():
                self.log("  드라이버 재시작...")
                self._quit_driver()
                self._ensure_driver()
            else:
                try:
                    self.driver.switch_to.default_content()
                except Exception:
                    self._quit_driver()
                    self._ensure_driver()
            return []

    def _extract_comment(self, elem):
        content = ""
        for sel in [".u_cbox_contents", ".u_cbox_text_wrap", ".u_cbox_text"]:
            els = elem.find_elements(By.CSS_SELECTOR, sel)
            if els:
                content = els[0].text.strip()
                if content:
                    break
        if not content:
            return None

        user_name = "알 수 없음"
        for sel in [".u_cbox_nick", ".u_cbox_name"]:
            els = elem.find_elements(By.CSS_SELECTOR, sel)
            if els:
                user_name = els[0].text.strip()
                if user_name:
                    break

        profile_url = ""
        for sel in [
            ".u_cbox_nick_area a", "a.u_cbox_name", ".u_cbox_info_main a",
        ]:
            els = elem.find_elements(By.CSS_SELECTOR, sel)
            if els:
                href = els[0].get_attribute("href") or ""
                if "blog.naver.com" in href:
                    profile_url = href
                    break

        comment_id = f"{user_name}_{hash(content)}"
        return {
            "id": comment_id,
            "userName": user_name,
            "content": content,
            "profileUrl": profile_url,
        }

    # ── Slack ─────────────────────────────────────────
    def send_slack(self, text):
        wh = self.config.get("slack_webhook", "")
        if not wh:
            return
        try:
            requests.post(wh, json={"text": text}, timeout=10)
        except Exception as e:
            self.log(f"  [에러] Slack 전송: {e}")

    # ── 전체 체크 ─────────────────────────────────────
    def check_all(self):
        post_urls = self.config.get("posts", [])
        if not post_urls:
            return 0

        total_new = 0
        counts = self.state["comment_counts"]
        seen = self.state["seen"]
        alerted_private = self.state.setdefault("alerted_private", {})

        # URL 파싱 — 블로그/카페 분리
        parsed = []         # 블로그: (blog_id, log_no, url)
        cafe_parsed = []    # 카페:   (cafe_slug, article_id, url)
        for url in post_urls:
            kind = classify_url(url)
            if kind == "blog":
                blog_id, log_no = parse_post_url(url)
                parsed.append((blog_id, log_no, url))
            elif kind == "cafe":
                slug, aid = parse_cafe_url(url)
                cafe_parsed.append((slug, aid, url))

        if not parsed and not cafe_parsed:
            self.log("유효한 URL이 없습니다.")
            return 0

        # ── 카페: 비공개만 체크 (댓글 스킵) ────────────
        if cafe_parsed:
            self.log(f"\n카페 비공개 확인 중... ({len(cafe_parsed)}개 글)")
            for slug, aid, url in cafe_parsed:
                key = f"cafe_{slug}_{aid}"
                club_id = self._get_cafe_club_id(slug)
                if not club_id:
                    self.log(f"  [경고] clubId 조회 실패: {slug}")
                    continue
                status, info = self._fetch_cafe_blind_info(club_id, aid)
                if status == "blind" and key not in alerted_private:
                    agency = info["agency"]
                    reason = info["reason"]
                    req_date = info["date"]
                    self.log(
                        f"  🚨 카페 비공개 감지: {slug}/{aid} "
                        f"(요청기관: {agency})"
                    )
                    msg = (
                        f"🚨 *카페 비공개 조치 감지*\n"
                        f"• 게시글: <{url}|{slug}/{aid}>\n"
                        f"• 요청기관: {agency}\n"
                        f"• 요청 일자: {req_date}\n"
                        f"• 사유: {reason}"
                    )
                    self.send_slack(msg)
                    alerted_private[key] = {
                        "agency": agency,
                        "reason": reason,
                        "date": req_date,
                        "detected_at": datetime.now().strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                    }
                time.sleep(0.1)
            self.save_state()

        if not parsed:
            # 블로그 없으면 여기서 종료 (카페만 등록된 경우)
            return 0

        # 1단계: 댓글 수 + 비공개 확인
        self.log(f"\n상태 확인 중... ({len(parsed)}개 글)")
        api_counts = {}
        cc_failed_keys = set()
        for blog_id, log_no, url in parsed:
            key = f"{blog_id}_{log_no}"
            cc, private_info = self._fetch_comment_count_direct(blog_id, log_no)

            if private_info and key not in alerted_private:
                agency = private_info["agency"]
                detail = self._fetch_private_detail(blog_id, log_no)
                if detail:
                    agency = detail["agency"]
                    req_date = detail["date"]
                else:
                    req_date = "알 수 없음"
                self.log(
                    f"  🚨 비공개 조치 감지: {blog_id}/{log_no} "
                    f"(요청기관: {agency}, 요청일자: {req_date})"
                )
                msg = (
                    f"🚨 *비공개 조치 감지*\n"
                    f"• 게시글: <{url}|{blog_id}/{log_no}>\n"
                    f"• 요청기관: {agency}\n"
                    f"• 요청 일자: {req_date}\n"
                    f"• 내용: 이 게시물은 {agency}의 요청으로 비공개 조치 되었습니다."
                )
                self.send_slack(msg)
                alerted_private[key] = {
                    "agency": agency,
                    "date": req_date,
                    "detected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }

            if cc is not None:
                api_counts[key] = cc
            else:
                api_counts[key] = counts.get(key, 0)
                if not private_info and key not in alerted_private:
                    cc_failed_keys.add(key)
            time.sleep(0.1)

        # 2단계: 기준점 + 변동 감지
        first_run = not self._baseline_done and not counts
        if first_run:
            for key, cc in api_counts.items():
                counts[key] = cc
            self._baseline_done = True
            self.save_state()
            self.log(f"  기준점 저장 완료 ({len(api_counts)}개 글)")
            return 0

        self._baseline_done = True

        to_scrape = []
        for blog_id, log_no, url in parsed:
            key = f"{blog_id}_{log_no}"
            old_cc = counts.get(key, 0)
            new_cc = api_counts.get(key, 0)
            if new_cc > old_cc:
                n_new = new_cc - old_cc
                to_scrape.append((blog_id, log_no, url, n_new))
            elif key in cc_failed_keys and key in seen:
                self.log(
                    f"  [경고] 댓글수 조회 실패, Selenium 확인: {blog_id}/{log_no}"
                )
                to_scrape.append((blog_id, log_no, url, 0))

        for key, cc in api_counts.items():
            if key not in cc_failed_keys:
                counts[key] = cc

        if not to_scrape:
            self.log("  댓글 변동 없음")
            self.save_state()
            return 0

        self.log(f"  댓글 증가 {len(to_scrape)}개 글 스크래핑")

        # 3단계: Selenium 스크래핑
        self._ensure_driver()
        try:
            for i, (blog_id, log_no, url, n_new) in enumerate(to_scrape):
                key = f"{blog_id}_{log_no}"

                if i > 0 and i % 10 == 0:
                    self.log("  드라이버 재시작 (안정화)...")
                    self._quit_driver()
                    time.sleep(1)
                    self._ensure_driver()

                self.log(
                    f"  [{i+1}/{len(to_scrape)}] {blog_id}/{log_no} (+{n_new})"
                )

                comments = self.get_comments(blog_id, log_no)

                if i < len(to_scrape) - 1:
                    time.sleep(0.5)

                if comments is None:
                    self.log(f"  [경고] 접근 불가: {url}")
                    self.send_slack(f"🚫 접근 불가: {url}")
                    continue

                prev_seen = set(seen.get(key, []))
                if prev_seen:
                    new = [c for c in comments if c["id"] not in prev_seen]
                else:
                    new = comments[-n_new:] if comments else []

                seen[key] = [c["id"] for c in comments]

                if not new:
                    continue

                for c in new:
                    total_new += 1
                    msg = (
                        f"💬 *새 댓글*\n"
                        f"• 게시글: <{url}|{blog_id}/{log_no}>\n"
                        f"• 작성자: {c['userName']}\n"
                        f"• 작성자 블로그: {c['profileUrl'] or '없음'}\n"
                        f"• 내용: {c['content']}"
                    )
                    self.send_slack(msg)
                    self.log(
                        f"    새 댓글: {c['userName']} - {c['content'][:50]}"
                    )
        finally:
            self._quit_driver()

        self.save_state()
        return total_new


# ═══════════════════════════════════════════════════════
#  GUI 탭
# ═══════════════════════════════════════════════════════
class CommentMonitorTab(ttk.Frame):
    """댓글 알림 탭 (ttk.Frame)"""

    def __init__(self, parent):
        super().__init__(parent, padding=10)
        self.root = self.winfo_toplevel()
        self.monitor = BlogMonitor(log_fn=self._log)
        self.monitoring = False
        self.timer_id = None
        self._build()
        self._refresh_posts()
        self._log("글 URL을 추가하고 [모니터링 시작]을 눌러주세요.")
        self._log("버튼을 누른 시점부터 새로 달린 댓글만 Slack으로 알림합니다.")

    def _build(self):
        # 글 관리
        f1 = ttk.LabelFrame(self, text="모니터링 글 목록", padding=10)
        f1.pack(fill="x", pady=(0, 5))

        list_frame = ttk.Frame(f1)
        list_frame.pack(side="left", fill="both", expand=True)

        self.lb = tk.Listbox(
            list_frame, height=5, font=("맑은 고딕", 9),
            selectmode="extended",
        )
        self.lb.pack(side="left", fill="both", expand=True)

        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self.lb.yview)
        sb.pack(side="right", fill="y")
        self.lb.configure(yscrollcommand=sb.set)

        bf = ttk.Frame(f1)
        bf.pack(side="right", padx=(10, 0))

        self.entry = ttk.Entry(bf, width=35)
        self.entry.pack(pady=2)
        self.entry.insert(0, "글 URL 붙여넣기")
        self.entry.bind("<FocusIn>", self._clear_placeholder)

        ttk.Button(bf, text="추가", command=self._add).pack(fill="x", pady=2)
        ttk.Button(bf, text="대량 추가", command=self._bulk_add).pack(fill="x", pady=2)
        ttk.Button(bf, text="선택 삭제", command=self._remove).pack(fill="x", pady=2)
        ttk.Button(bf, text="전체 삭제", command=self._remove_all).pack(fill="x", pady=2)

        cnt_frame = ttk.Frame(bf)
        cnt_frame.pack(fill="x", pady=2)
        self.cnt_label = ttk.Label(cnt_frame, text="0개 등록")
        self.cnt_label.pack()

        # 컨트롤
        f2 = ttk.Frame(self, padding=5)
        f2.pack(fill="x")

        self.btn = ttk.Button(f2, text="▶ 모니터링 시작", command=self._toggle)
        self.btn.pack(side="left")

        self.btn_now = ttk.Button(f2, text="⚡ 즉시 체크", command=self._run_now)
        self.btn_now.pack(side="left", padx=(5, 0))

        self.st = ttk.Label(f2, text="대기 중")
        self.st.pack(side="left", padx=20)

        self.lt = ttk.Label(f2, text="")
        self.lt.pack(side="right")

        # 로그
        f3 = ttk.LabelFrame(self, text="로그", padding=5)
        f3.pack(fill="both", expand=True, pady=(5, 0))

        self.log_box = scrolledtext.ScrolledText(
            f3, height=15, state="disabled", font=("Consolas", 9)
        )
        self.log_box.pack(fill="both", expand=True)

    # ── 로그 ──────────────────────────────────────────
    def _log(self, msg):
        def _do():
            self.log_box.configure(state="normal")
            ts = datetime.now().strftime("%H:%M:%S")
            self.log_box.insert("end", f"[{ts}] {msg}\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        try:
            self.root.after(0, _do)
        except Exception:
            pass

    # ── 글 관리 ───────────────────────────────────────
    def _clear_placeholder(self, _):
        if self.entry.get() == "글 URL 붙여넣기":
            self.entry.delete(0, "end")

    def _refresh_posts(self):
        self.lb.delete(0, "end")
        posts = self.monitor.config.get("posts", [])
        for url in posts:
            self.lb.insert("end", f"  {url}")
        self.cnt_label.configure(text=f"{len(posts)}개 등록")

    def _add(self):
        raw = self.entry.get().strip()
        if not raw or raw == "글 URL 붙여넣기":
            return
        urls = re.split(r'[\s,]+', raw)
        added = 0
        for url in urls:
            url = url.strip()
            if not url:
                continue
            if not classify_url(url):
                self._log(f"  [경고] 잘못된 URL: {url}")
                continue
            if url in self.monitor.config["posts"]:
                continue
            self.monitor.config["posts"].append(url)
            added += 1
        if added:
            self.monitor.save_config()
            self._refresh_posts()
            self._log(f"글 {added}개 추가됨")
        self.entry.delete(0, "end")

    def _bulk_add(self):
        popup = tk.Toplevel(self.root)
        popup.title("대량 추가")
        popup.geometry("600x400")
        popup.transient(self.root)
        popup.grab_set()

        ttk.Label(
            popup, text="URL을 한 줄에 하나씩 붙여넣으세요:",
            font=("맑은 고딕", 10),
        ).pack(padx=10, pady=(10, 5), anchor="w")

        text = scrolledtext.ScrolledText(popup, height=18, font=("Consolas", 9))
        text.pack(fill="both", expand=True, padx=10, pady=5)

        def do_add():
            raw = text.get("1.0", "end")
            found = re.findall(
                r'https?://(?:blog|cafe)\.naver\.com/[^\s,]+', raw
            )
            added = 0
            for url in found:
                url = url.strip()
                if not classify_url(url):
                    continue
                if url in self.monitor.config["posts"]:
                    continue
                self.monitor.config["posts"].append(url)
                added += 1
            if added:
                self.monitor.save_config()
                self._refresh_posts()
                self._log(f"글 {added}개 추가됨")
            else:
                self._log("추가할 새 URL이 없습니다.")
            popup.destroy()

        btn_frame = ttk.Frame(popup)
        btn_frame.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btn_frame, text="추가", command=do_add).pack(side="right", padx=5)
        ttk.Button(btn_frame, text="취소", command=popup.destroy).pack(side="right")

    def _remove(self):
        sel = list(self.lb.curselection())
        if not sel:
            return
        posts = self.monitor.config["posts"]
        for idx in reversed(sel):
            if idx < len(posts):
                posts.pop(idx)
        self.monitor.save_config()
        self._refresh_posts()
        self._log(f"글 {len(sel)}개 삭제됨")

    def _remove_all(self):
        if not self.monitor.config.get("posts"):
            return
        if not messagebox.askyesno("확인", "모든 글을 삭제하시겠습니까?"):
            return
        cnt = len(self.monitor.config["posts"])
        self.monitor.config["posts"] = []
        self.monitor.save_config()
        self._refresh_posts()
        self._log(f"전체 {cnt}개 글 삭제됨")

    # ── 모니터링 제어 ─────────────────────────────────
    def _toggle(self):
        if self.monitoring:
            self.monitoring = False
            if self.timer_id:
                self.root.after_cancel(self.timer_id)
                self.timer_id = None
            self.btn.configure(text="▶ 모니터링 시작")
            self.st.configure(text="대기 중")
            self._log("모니터링 중지")
        else:
            posts = self.monitor.config.get("posts", [])
            if not posts:
                messagebox.showwarning("경고", "모니터링할 글 URL을 추가해주세요.")
                return
            self.monitoring = True
            self.btn.configure(text="⏹ 모니터링 중지")
            self.st.configure(text="모니터링 중")
            self.monitor.state["comment_counts"] = {}
            self.monitor.state["seen"] = {}
            self.monitor.state["alerted_private"] = {}
            self.monitor._baseline_done = False
            self._log(f"모니터링 시작! ({len(posts)}개 글)")
            self._run()

    def _run_now(self):
        if self.st.cget("text") == "체크 중...":
            self._log("이미 체크 진행 중입니다.")
            return
        posts = self.monitor.config.get("posts", [])
        if not posts:
            messagebox.showwarning("경고", "체크할 글 URL을 추가해주세요.")
            return
        if self.monitoring:
            if self.timer_id:
                self.root.after_cancel(self.timer_id)
                self.timer_id = None
            self._log("즉시 체크 시작!")
            self._run()
        else:
            self._log("1회 즉시 체크 시작!")
            self._run_once()

    def _run_once(self):
        self.st.configure(text="체크 중...")
        self.btn_now.configure(state="disabled")

        def work():
            try:
                n = self.monitor.check_all()
                self.root.after(0, lambda: self._done_once(n))
            except Exception as e:
                self._log(f"[에러] {e}")
                self.root.after(0, lambda: self._done_once(-1))

        threading.Thread(target=work, daemon=True).start()

    def _done_once(self, n):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.lt.configure(text=f"마지막: {now}")
        if n >= 0:
            self._log(f"체크 완료 - 새 댓글 {n}개")
        self.st.configure(text="대기 중")
        self.btn_now.configure(state="normal")

    def _run(self):
        if not self.monitoring:
            return
        self.st.configure(text="체크 중...")

        def work():
            try:
                n = self.monitor.check_all()
                self.root.after(0, lambda: self._done(n))
            except Exception as e:
                self._log(f"[에러] {e}")
                self.root.after(0, lambda: self._done(-1))

        threading.Thread(target=work, daemon=True).start()

    def _done(self, n):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.lt.configure(text=f"마지막: {now}")
        if n >= 0:
            self._log(f"체크 완료 - 새 댓글 {n}개")
        if self.monitoring:
            self.st.configure(text="모니터링 중")
            mins = self.monitor.config.get("interval_minutes", 30)
            self.timer_id = self.root.after(mins * 60_000, self._run)
            self._log(f"다음 체크: {mins}분 후")
