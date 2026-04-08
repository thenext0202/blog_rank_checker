#!/usr/bin/env python3
"""네이버 블로그 자동 발행 스크립트 (Selenium + 클립보드 붙여넣기)

블록 타입:
  text    - 일반 텍스트 (size, color, align, bold 옵션)
  heading - 소제목 (자동 볼드, size 옵션)
  quote   - 인용구
  image   - 이미지 업로드
"""

import functools
import json
import os
import sys
import time

import pyperclip
from selenium import webdriver
from selenium.common.exceptions import (
    ElementNotInteractableException,
    NoSuchElementException,
    TimeoutException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(BASE_DIR, "..", "chrome_profile")

# ────────────────────────────────────────────────
#  유틸리티
# ────────────────────────────────────────────────

def retry(max_attempts=3, delay=2):
    """실패 시 재시도 데코레이터"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt < max_attempts - 1:
                        print(f"  재시도 {attempt + 1}/{max_attempts}: {e}")
                        time.sleep(delay)
                    else:
                        raise
        return wrapper
    return decorator


def find_element_by_selectors(driver, selectors, wait=5):
    """여러 CSS 셀렉터를 순서대로 시도하여 요소를 찾는다.

    먼저 즉시 탐색(0.3초)으로 빠르게 시도하고,
    전부 실패하면 첫 번째 셀렉터로 wait초까지 대기.
    """
    # 1차: 즉시 탐색 (각 셀렉터 0.3초)
    for selector in selectors:
        try:
            by = By.XPATH if selector.startswith("//") else By.CSS_SELECTOR
            el = WebDriverWait(driver, 0.3).until(
                EC.element_to_be_clickable((by, selector))
            )
            return el
        except TimeoutException:
            continue

    # 2차: 첫 번째 셀렉터로 전체 대기
    selector = selectors[0]
    try:
        by = By.XPATH if selector.startswith("//") else By.CSS_SELECTOR
        el = WebDriverWait(driver, wait).until(
            EC.element_to_be_clickable((by, selector))
        )
        return el
    except TimeoutException:
        return None


# ────────────────────────────────────────────────
#  NaverBlogPoster
# ────────────────────────────────────────────────

class NaverBlogPoster:
    def __init__(self, blog_id: str):
        self.blog_id = blog_id
        self.driver = None

    # ── 드라이버 생성 ──────────────────────────

    def create_driver(self, headless=False):
        """Chrome 드라이버 생성 (프로필 저장 + 자동화 탐지 우회)"""
        # 잠금 파일 정리 (이전 세션 비정상 종료 대비)
        self._cleanup_profile_locks()

        opts = self._build_chrome_options(headless, use_profile=True)

        try:
            driver = self._start_chrome(opts)
            return driver
        except Exception as e:
            err_msg = str(e)
            if "session not created" in err_msg or "cannot parse" in err_msg:
                print(f"  [!] Chrome 프로필 충돌 감지: {err_msg[:80]}")
                print("  → Chrome 창이 열려있다면 모두 닫고 다시 시도하세요.")
                print("  → 프로필 없이 재시도합니다 (로그인 필요)...")
                opts_no_profile = self._build_chrome_options(headless, use_profile=False)
                return self._start_chrome(opts_no_profile)
            raise

    @staticmethod
    def _cleanup_profile_locks():
        """chrome_profile 내 잠금 파일 제거"""
        lock_files = ["SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile"]
        for name in lock_files:
            for subdir in ["", "Default"]:
                lock_path = os.path.join(PROFILE_DIR, subdir, name) if subdir else os.path.join(PROFILE_DIR, name)
                if os.path.exists(lock_path):
                    try:
                        os.remove(lock_path)
                    except OSError:
                        pass

    def _build_chrome_options(self, headless=False, use_profile=True):
        """Chrome 옵션 빌드"""
        opts = Options()

        if use_profile:
            # Chrome 프로필 디렉토리 → 로그인 세션 유지
            opts.add_argument(f"--user-data-dir={PROFILE_DIR}")
            opts.add_argument("--profile-directory=Default")

        if headless:
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
        return opts

    def _start_chrome(self, opts):
        """Chrome 드라이버 시작"""
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

    # ── 로그인 ─────────────────────────────────

    def login_interactive(self):
        """수동 로그인: 브라우저를 열어 사용자가 직접 로그인한다."""
        print("=" * 50)
        print("  네이버 로그인 (수동)")
        print("=" * 50)

        self.driver = self.create_driver(headless=False)
        self.driver.get("https://nid.naver.com/nidlogin.login")

        print()
        print("  브라우저에서 네이버에 로그인해주세요.")
        input("  로그인 완료 후 Enter 키를 누르세요... ")

        # 로그인 확인
        self.driver.get("https://blog.naver.com/" + self.blog_id)
        time.sleep(3)

        logged_in = self._is_logged_in()
        self.driver.quit()
        self.driver = None

        if logged_in:
            print("  로그인 성공! 프로필이 저장되었습니다.")
        else:
            print("  [!] 로그인 감지 실패. 다시 시도해주세요.")
        return logged_in

    def check_login(self):
        """저장된 Chrome 프로필의 로그인 유효 여부를 확인한다."""
        if not os.path.exists(PROFILE_DIR):
            return False
        driver = self.create_driver(headless=True)
        try:
            driver.get("https://blog.naver.com/" + self.blog_id)
            time.sleep(3)
            return self._is_logged_in(driver)
        finally:
            driver.quit()

    def _is_logged_in(self, driver=None):
        """로그인 상태인지 확인 (네이버 인증 쿠키 존재 여부)"""
        d = driver or self.driver
        cookies = d.get_cookies()
        cookie_names = {c["name"] for c in cookies}
        return "NID_AUT" in cookie_names or "NID_SES" in cookie_names

    # ── 에디터 네비게이션 ──────────────────────

    def navigate_to_editor(self):
        """블로그 에디터 페이지로 이동한다."""
        url = f"https://blog.naver.com/{self.blog_id}/postwrite"
        self.driver.get(url)

        # 에디터 로드 대기 (제목 영역이 나타날 때까지)
        try:
            WebDriverWait(self.driver, 7).until(
                EC.presence_of_element_located((By.CSS_SELECTOR,
                    ".se-component-content, [data-placeholder-text], .se-placeholder"))
            )
        except TimeoutException:
            time.sleep(1)

        # 새 탭으로 열린 경우 전환
        if len(self.driver.window_handles) > 1:
            self.driver.switch_to.window(self.driver.window_handles[-1])

        self._dismiss_popups()
        print("  에디터 준비 완료")

    def _dismiss_popups(self):
        """에디터에 나타나는 팝업/툴팁을 닫는다."""
        popup_selectors = [
            "button.se-popup-button-cancel",
            "button.se-help-panel-close-button",
            "button[data-type='cancel']",
            ".layer_popup .btn_close",
            ".toast_close",
        ]
        for selector in popup_selectors:
            try:
                btn = self.driver.find_element(By.CSS_SELECTOR, selector)
                btn.click()
                time.sleep(0.2)
            except (NoSuchElementException, ElementNotInteractableException):
                pass

    # ── 제목 입력 ──────────────────────────────

    @retry(max_attempts=2)
    def input_title(self, title: str):
        """클립보드 붙여넣기로 제목을 입력한다."""
        title_selectors = [
            "span.se-placeholder.__se_placeholder.se-fs32",
            ".se-title-text .se-placeholder",
            "[data-placeholder-text]",
            ".se-component-content .se-text-paragraph",
        ]

        title_el = find_element_by_selectors(self.driver, title_selectors)
        if not title_el:
            raise RuntimeError("제목 입력 영역을 찾을 수 없습니다")

        title_el.click()
        time.sleep(0.3)

        # 기존 내용 전체 선택 후 삭제
        ActionChains(self.driver) \
            .key_down(Keys.CONTROL).send_keys("a").key_up(Keys.CONTROL) \
            .perform()

        pyperclip.copy(title)
        ActionChains(self.driver) \
            .key_down(Keys.CONTROL).send_keys("v").key_up(Keys.CONTROL) \
            .perform()
        time.sleep(0.5)

        # 제목 입력 후 Enter로 본문 영역으로 이동
        ActionChains(self.driver).send_keys(Keys.ENTER).perform()
        time.sleep(0.3)

        print(f"  제목 입력 완료: {title[:40]}...")

    # ── 서식 적용 ──────────────────────────────

    def _select_current_line(self):
        """현재 줄 전체를 선택한다."""
        ActionChains(self.driver) \
            .send_keys(Keys.HOME) \
            .key_down(Keys.SHIFT).send_keys(Keys.END).key_up(Keys.SHIFT) \
            .perform()
        time.sleep(0.2)

    def _apply_bold(self):
        """볼드 토글."""
        ActionChains(self.driver) \
            .key_down(Keys.CONTROL).send_keys("b").key_up(Keys.CONTROL) \
            .perform()
        time.sleep(0.2)

    def _apply_alignment(self, align: str):
        """정렬 적용 (left, center, right)."""
        align_map = {
            "left":   ["button[data-command='alignLeft']",
                       "button.se-toolbar-button-left",
                       "//button[contains(@class, 'align') and contains(@class, 'left')]"],
            "center": ["button[data-command='alignCenter']",
                       "button.se-toolbar-button-center",
                       "//button[contains(@class, 'align') and contains(@class, 'center')]"],
            "right":  ["button[data-command='alignRight']",
                       "button.se-toolbar-button-right",
                       "//button[contains(@class, 'align') and contains(@class, 'right')]"],
        }
        if align not in align_map:
            return

        # 방법 1: 툴바 버튼 클릭
        btn = find_element_by_selectors(self.driver, align_map[align], wait=2)
        if btn:
            btn.click()
            time.sleep(0.3)
            return

        # 방법 2: JavaScript execCommand
        cmd_map = {"left": "justifyLeft", "center": "justifyCenter", "right": "justifyRight"}
        self.driver.execute_script(f"document.execCommand('{cmd_map[align]}', false, null);")
        time.sleep(0.3)

    def _apply_font_size(self, size: int):
        """글자 크기 적용. SmartEditor ONE 지원 크기: 11,13,15,16,18,19,24,28,30,36"""
        # 방법 1: 툴바 폰트 크기 드롭다운
        size_btn_selectors = [
            "button.se-toolbar-button-font-size",
            ".se-font-size button",
            "button[data-command='fontSize']",
            ".se-toolbar .se-text-size-button",
        ]
        size_btn = find_element_by_selectors(self.driver, size_btn_selectors, wait=2)
        if size_btn:
            size_btn.click()
            time.sleep(0.5)
            # 드롭다운에서 사이즈 선택
            size_option_selectors = [
                f"li[data-value='{size}']",
                f"button[data-value='{size}']",
                f"//li[contains(text(), '{size}')]",
                f"//button[contains(text(), '{size}')]",
            ]
            option = find_element_by_selectors(self.driver, size_option_selectors, wait=2)
            if option:
                option.click()
                time.sleep(0.3)
                return

        # 방법 2: JavaScript로 직접 스타일 적용
        self.driver.execute_script(f"""
            var sel = window.getSelection();
            if (sel.rangeCount > 0) {{
                var range = sel.getRangeAt(0);
                var span = document.createElement('span');
                span.style.fontSize = '{size}px';
                range.surroundContents(span);
            }}
        """)
        time.sleep(0.3)

    def _apply_font_color(self, color: str):
        """글자 색상 적용 (hex: #FF0000)."""
        # 방법 1: JavaScript execCommand
        self.driver.execute_script(
            f"document.execCommand('foreColor', false, '{color}');"
        )
        time.sleep(0.3)

    def _apply_format(self, block: dict):
        """블록에 지정된 서식을 현재 선택 영역에 적용한다."""
        has_format = any(k in block for k in ("bold", "size", "color", "align"))
        if not has_format:
            return

        # 현재 줄 선택
        self._select_current_line()
        time.sleep(0.2)

        if block.get("bold"):
            self._apply_bold()

        if "size" in block:
            self._apply_font_size(block["size"])

        if "color" in block:
            self._apply_font_color(block["color"])

        if "align" in block:
            self._apply_alignment(block["align"])

        # 선택 해제 → 줄 끝으로 이동
        ActionChains(self.driver).send_keys(Keys.END).perform()
        time.sleep(0.2)

    # ── 인용구 ─────────────────────────────────

    def _insert_quote(self, text: str):
        """인용구 블록을 삽입한다."""
        # 방법 1: 툴바의 인용구 버튼 클릭
        quote_selectors = [
            "button[data-command='quotation']",
            "button.se-toolbar-button-quotation",
            "button[data-type='quotation']",
            ".se-toolbar button[data-command='quote']",
            "//button[contains(@class, 'quotation')]",
        ]
        quote_btn = find_element_by_selectors(self.driver, quote_selectors, wait=2)
        if quote_btn:
            quote_btn.click()
            time.sleep(0.5)
            self._paste_text(text)
            time.sleep(0.3)
            # 인용구 밖으로 나가기: Enter 두 번
            self._press_enter()
            self._press_enter()
            return

        # 방법 2: 인용구 버튼을 못 찾으면 따옴표로 대체
        self._paste_text(f"「{text}」")
        self._press_enter()

    # ── 본문 입력 ──────────────────────────────

    def input_body(self, body_blocks: list):
        """본문 콘텐츠를 블록 단위로 입력한다."""
        for i, block in enumerate(body_blocks):
            block_type = block.get("type", "text")

            if block_type == "text":
                self._paste_text(block["content"])
                self._apply_format(block)
                self._press_enter()

            elif block_type == "heading":
                self._paste_text(block["content"])
                # 줄 전체 선택 후 볼드
                self._select_current_line()
                self._apply_bold()
                if "size" in block:
                    self._apply_font_size(block["size"])
                if "color" in block:
                    self._apply_font_color(block["color"])
                if "align" in block:
                    self._apply_alignment(block["align"])
                ActionChains(self.driver).send_keys(Keys.END).perform()
                self._press_enter()
                # 다음 줄 볼드 해제
                self._apply_bold()

            elif block_type == "quote":
                self._insert_quote(block["content"])

            elif block_type == "image":
                self._upload_image(block.get("path", ""))

            time.sleep(0.5)
            print(f"  블록 {i + 1}/{len(body_blocks)} 입력 완료 ({block_type})")

    def _paste_text(self, text: str):
        """클립보드를 통해 텍스트를 붙여넣는다."""
        pyperclip.copy(text)
        ActionChains(self.driver) \
            .key_down(Keys.CONTROL).send_keys("v").key_up(Keys.CONTROL) \
            .perform()
        time.sleep(0.3)

    def _press_enter(self):
        """Enter 키로 줄바꿈."""
        ActionChains(self.driver).send_keys(Keys.ENTER).perform()
        time.sleep(0.2)

    # ── 이미지 업로드 ──────────────────────────

    def _upload_image(self, image_path: str):
        """이미지를 에디터에 업로드한다."""
        abs_path = os.path.abspath(image_path)
        if not os.path.exists(abs_path):
            print(f"  [!] 이미지 파일 없음: {abs_path}")
            return

        # 1) 이미지 툴바 버튼 클릭
        img_btn_selectors = [
            "button.se-image-toolbar-button",
            "button.se-document-toolbar-basic-button",
            ".se-toolbar button[data-type='image']",
        ]
        for selector in img_btn_selectors:
            try:
                btn = self.driver.find_element(By.CSS_SELECTOR, selector)
                btn.click()
                time.sleep(1)
                break
            except (NoSuchElementException, ElementNotInteractableException):
                continue

        # 2) 숨겨진 file input 찾기
        file_input = self._find_file_input()
        if file_input:
            file_input.send_keys(abs_path)
            time.sleep(3)
            print(f"  이미지 업로드 완료: {os.path.basename(abs_path)}")
        else:
            print(f"  [!] 이미지 업로드 실패: file input을 찾을 수 없습니다")

    def _find_file_input(self):
        """숨겨진 file input 요소를 찾는다."""
        selectors = ["input#hidden-file", "input[type='file']", "input[accept*='image']"]
        for selector in selectors:
            try:
                return self.driver.find_element(By.CSS_SELECTOR, selector)
            except NoSuchElementException:
                continue

        # JavaScript로 숨겨진 input을 표시
        self.driver.execute_script("""
            document.querySelectorAll('input[type="file"]').forEach(el => {
                el.style.display = 'block';
                el.style.visibility = 'visible';
                el.style.height = '1px';
                el.style.width = '1px';
                el.style.opacity = '1';
            });
        """)
        time.sleep(0.5)

        for selector in selectors:
            try:
                return self.driver.find_element(By.CSS_SELECTOR, selector)
            except NoSuchElementException:
                continue
        return None

    # ── 발행 ───────────────────────────────────

    def open_publish_dialog(self):
        """1차 발행 버튼 클릭 → 발행 설정 다이얼로그 열기."""
        try:
            self.driver.switch_to.default_content()
        except Exception:
            pass

        pub_selectors = [
            "button[class*='publish_btn']",
            "//button[contains(text(), '발행')]",
        ]
        pub_btn = find_element_by_selectors(self.driver, pub_selectors, wait=5)
        if not pub_btn:
            raise RuntimeError("발행 버튼을 찾을 수 없습니다")

        pub_btn.click()
        time.sleep(1)
        print("  발행 설정 다이얼로그 열림")

    def confirm_publish(self):
        """최종 발행 버튼 클릭 → 실제 발행."""
        confirm_selectors = [
            "button[data-testid='seOnePublishBtn']",
            "button[class*='confirm_btn']",
            "//button[contains(@class, 'confirm_btn')]",
        ]
        confirm_btn = find_element_by_selectors(self.driver, confirm_selectors, wait=3)
        if not confirm_btn:
            raise RuntimeError("최종 발행 버튼을 찾을 수 없습니다")

        confirm_btn.click()
        time.sleep(3)
        print("  발행 완료!")
        return True

    def publish(self):
        """발행 (설정 다이얼로그 열기 + 최종 발행). 하위 호환용."""
        self.open_publish_dialog()
        return self.confirm_publish()

    # ── 메인 실행 ──────────────────────────────

    def post(self, content_file: str):
        """JSON 콘텐츠 파일을 읽어 블로그에 발행한다."""
        with open(content_file, "r", encoding="utf-8") as f:
            content = json.load(f)

        title = content["title"]
        body_blocks = content["body"]

        print(f"\n  제목: {title}")
        print(f"  블록 수: {len(body_blocks)}")
        print()

        try:
            self.driver = self.create_driver(headless=False)

            # 로그인 상태 확인 → 안 되어 있으면 같은 브라우저에서 로그인
            self.driver.get("https://www.naver.com")
            time.sleep(2)
            if not self._is_logged_in():
                self.driver.get("https://nid.naver.com/nidlogin.login")
                print("  로그인이 필요합니다. 브라우저에서 로그인해주세요.")
                input("  로그인 완료 후 Enter 키를 누르세요... ")

            self.navigate_to_editor()
            self.input_title(title)
            # input_title에서 Enter로 본문 영역으로 자동 이동됨
            self.input_body(body_blocks)

            print()
            answer = input("  발행하시겠습니까? (y/n): ").strip().lower()
            if answer == "y":
                self.publish()
            else:
                print("  발행을 건너뜁니다. (임시저장 상태)")

        except Exception as e:
            print(f"\n  [!] 오류 발생: {e}")
            try:
                self.driver.save_screenshot(
                    os.path.join(BASE_DIR, "blog_post_error.png")
                )
                print("  에러 스크린샷 저장: blog_post_error.png")
            except Exception:
                pass
            raise

        finally:
            if self.driver:
                self.driver.quit()
                self.driver = None


# ────────────────────────────────────────────────
#  CLI
# ────────────────────────────────────────────────

def main():
    BLOG_ID = "cakebananamilk"

    poster = NaverBlogPoster(blog_id=BLOG_ID)

    if len(sys.argv) < 2:
        print("사용법:")
        print("  python blog_post.py login           최초 로그인 (수동)")
        print("  python blog_post.py check           로그인 상태 확인")
        print("  python blog_post.py post <file>     블로그 글 발행")
        print()
        print("예시:")
        print("  python blog_post.py post blog_content/sample_post.json")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "login":
        poster.login_interactive()

    elif cmd == "check":
        if poster.check_login():
            print("  로그인 상태: 유효")
        else:
            print("  로그인 상태: 만료됨 (login 명령으로 다시 로그인하세요)")

    elif cmd == "post":
        if len(sys.argv) < 3:
            print("  사용법: python blog_post.py post <content.json>")
            sys.exit(1)
        poster.post(sys.argv[2])

    else:
        print(f"  알 수 없는 명령: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
