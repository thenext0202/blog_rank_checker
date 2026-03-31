"""
네이버 블로그/카페 대댓글 자동 작성 봇
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Google Sheets 컬럼 구조:
  A: 블로그/카페 링크
  B: 찾을 댓글
  C: 작성할 대댓글
  D: 대댓글 작업 완료 (자동 체크)
  E: 비공개 요청 (직접 체크해두면 글을 비공개 처리)
  F: 비공개 작업 완료 (자동 체크)
  G: 공개 요청 (직접 체크해두면 글을 공개 처리)
  H: 공개 작업 완료 (자동 체크)

블로그/카페 URL 자동 감지하여 각각 적절한 방식으로 처리
"""

import gspread
from google.oauth2.service_account import Credentials
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import re
import sys
import os

# ─── 설정 ────────────────────────────────────────────
# PyInstaller 번들 또는 일반 실행 모두 지원
def get_base_path():
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

CREDENTIALS_FILE = os.path.join(get_base_path(), "google_credentials.json")
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


# ─── Google Sheets ───────────────────────────────────
def connect_sheet(sheet_url):
    """Google Sheets에 연결하여 worksheet 반환"""
    if not os.path.exists(CREDENTIALS_FILE):
        print(f"[오류] 인증 파일이 없습니다: {CREDENTIALS_FILE}")
        print()
        print("═" * 55)
        print("  Google Sheets 연동 설정 방법")
        print("═" * 55)
        print("1. https://console.cloud.google.com 접속")
        print("2. 프로젝트 생성 (또는 기존 프로젝트 선택)")
        print("3. 'Google Sheets API' 검색 → 사용 설정")
        print("4. 'Google Drive API' 검색 → 사용 설정")
        print("5. IAM 및 관리자 → 서비스 계정 → 서비스 계정 만들기")
        print("6. 만든 서비스 계정 클릭 → 키 → 키 추가 → JSON")
        print(f"7. 다운받은 JSON 파일을 아래 경로에 저장:")
        print(f"   {CREDENTIALS_FILE}")
        print("8. 서비스 계정 이메일을 스프레드시트에 '편집자'로 공유")
        print("   (서비스 계정 이메일: JSON 파일 안의 client_email)")
        print("═" * 55)
        sys.exit(1)

    # 시트 ID 추출
    match = re.search(r'/d/([a-zA-Z0-9-_]+)', sheet_url)
    if not match:
        print("[오류] 올바른 Google Sheets URL이 아닙니다.")
        sys.exit(1)
    sheet_id = match.group(1)

    try:
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(sheet_id)
        worksheet = spreadsheet.sheet1
        print(f"[OK] 스프레드시트 연결 완료: {spreadsheet.title}")
        return worksheet
    except Exception as e:
        print(f"[오류] 스프레드시트 연결 실패: {e}")
        print("  → 서비스 계정 이메일이 시트에 편집자로 공유되어 있는지 확인하세요.")
        sys.exit(1)


def get_rows(worksheet):
    """시트에서 전체 데이터를 읽어와서 처리할 행 목록 반환"""
    all_values = worksheet.get_all_values()
    if not all_values:
        print("[오류] 시트가 비어 있습니다.")
        return [], []

    header = all_values[0]
    rows = all_values[1:]
    print(f"[OK] {len(rows)}개 행 읽음 (헤더: {header})")
    return header, rows


def is_checked(value):
    """체크박스 또는 텍스트 값이 '완료'인지 확인"""
    if value is None:
        return False
    v = str(value).strip().upper()
    return v in ["TRUE", "완료", "O", "V", "Y", "YES", "1", "✓", "✔"]


# ─── 브라우저 ────────────────────────────────────────
# 봇 전용 크롬 프로필 (한번 로그인하면 다음부터 자동 로그인)
def get_exe_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

BOT_PROFILE_DIR = os.path.join(get_exe_dir(), "chrome_profile")


def kill_existing_chrome():
    """봇 프로필을 사용 중인 크롬 프로세스 자동 종료"""
    import subprocess
    try:
        subprocess.run(
            ['taskkill', '/F', '/IM', 'chromedriver.exe'],
            capture_output=True, timeout=5
        )
    except:
        pass
    # chrome_profile 경로를 물고 있는 크롬만 죽이기 어려우므로
    # 잠금 파일이 있으면 전체 크롬 종료 시도
    lock_path = os.path.join(BOT_PROFILE_DIR, "SingletonLock")
    if os.path.exists(lock_path):
        print("    봇 크롬 프로필이 사용 중입니다. 크롬 프로세스 정리 중...")
        try:
            subprocess.run(
                ['taskkill', '/F', '/IM', 'chrome.exe'],
                capture_output=True, timeout=10
            )
            import time as _t
            _t.sleep(2)
        except:
            pass


def cleanup_chrome_profile():
    """크롬 프로필 잠금 파일 제거"""
    lock_files = ["SingletonLock", "SingletonSocket", "SingletonCookie"]
    for lock in lock_files:
        path = os.path.join(BOT_PROFILE_DIR, lock)
        try:
            os.remove(path)
        except:
            pass


def setup_browser():
    """Chrome 브라우저 설정 (시크릿 모드)"""
    # 기존 크롬 프로세스 정리
    kill_existing_chrome()

    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    options.add_argument("--incognito")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(options=options)

    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    return driver


def is_cafe_url(url):
    """URL이 카페 글인지 확인"""
    return "cafe.naver.com" in url


def switch_to_cafe_frame(driver):
    """네이버 카페 iframe 전환"""
    driver.switch_to.default_content()
    try:
        iframe = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.ID, "cafe_main"))
        )
        driver.switch_to.frame(iframe)
        return True
    except:
        pass
    try:
        for iframe in driver.find_elements(By.TAG_NAME, "iframe"):
            src = iframe.get_attribute("src") or ""
            if "ArticleRead" in src or "article" in src.lower():
                driver.switch_to.frame(iframe)
                return True
    except:
        pass
    return False


def switch_to_blog_frame(driver):
    """네이버 블로그 iframe 전환"""
    driver.switch_to.default_content()
    try:
        iframe = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.ID, "mainFrame"))
        )
        driver.switch_to.frame(iframe)
        return True
    except:
        pass
    try:
        for iframe in driver.find_elements(By.TAG_NAME, "iframe"):
            src = iframe.get_attribute("src") or ""
            if "PostView" in src or "post" in src.lower():
                driver.switch_to.frame(iframe)
                return True
    except:
        pass
    return False


def expand_all_comments(driver):
    """댓글 더보기 클릭"""
    for _ in range(20):
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
            except:
                pass
            if clicked:
                break
        if not clicked:
            break


def make_post_private(driver, post_url):
    """블로그 글을 비공개로 전환 (수정 → 발행 → 비공개 → 발행)"""
    try:
        # 1. 수정 버튼 클릭 (mainFrame 안)
        switch_to_blog_frame(driver)
        time.sleep(1)

        edit_btn = None
        for el in driver.find_elements(By.TAG_NAME, "a"):
            try:
                txt = el.text.strip()
                cls = el.get_attribute("class") or ""
                if txt == "수정" and "_activeId" in cls:
                    edit_btn = el
                    break
            except:
                pass

        if not edit_btn:
            print("    수정 버튼을 찾을 수 없습니다. (다른 계정의 글일 수 있음)")
            driver.switch_to.default_content()
            return "need_relogin"

        driver.execute_script("arguments[0].click();", edit_btn)
        print("    수정 버튼 클릭")
        time.sleep(5)

        # 2. 에디터 로드 후 mainFrame 재전환
        driver.switch_to.default_content()
        try:
            iframe = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "mainFrame"))
            )
            driver.switch_to.frame(iframe)
        except:
            print("    에디터 로드 실패")
            driver.switch_to.default_content()
            return False

        # 3. 발행 버튼 클릭 (발행 설정 패널 열기)
        publish_btn = None
        try:
            publish_btn = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button.publish_btn__m9KHH"))
            )
        except:
            for btn in driver.find_elements(By.TAG_NAME, "button"):
                try:
                    if btn.is_displayed() and btn.text.strip() == "발행":
                        publish_btn = btn
                        break
                except:
                    pass

        if not publish_btn:
            print("    발행 버튼을 찾을 수 없습니다.")
            input("    비공개 처리 후 Enter... ")
            driver.switch_to.default_content()
            return True

        driver.execute_script("arguments[0].click();", publish_btn)
        print("    발행 버튼 클릭 (설정 패널 열기)")
        time.sleep(2)

        # 4. 비공개 라디오 버튼 클릭
        private_clicked = False
        for label in driver.find_elements(By.CSS_SELECTOR, "label.radio_label__mB6ia"):
            try:
                if label.is_displayed() and "비공개" in label.text:
                    driver.execute_script("arguments[0].click();", label)
                    private_clicked = True
                    print("    비공개 선택")
                    time.sleep(1)
                    break
            except:
                pass

        if not private_clicked:
            # fallback: span으로 찾기
            for span in driver.find_elements(By.CSS_SELECTOR, "span.input_radio__yZcoa"):
                try:
                    if span.is_displayed() and "비공개" in span.text:
                        driver.execute_script("arguments[0].click();", span)
                        private_clicked = True
                        print("    비공개 선택 (span)")
                        time.sleep(1)
                        break
                except:
                    pass

        if not private_clicked:
            print("    비공개 옵션을 찾을 수 없습니다.")
            input("    비공개 처리 후 Enter... ")
            driver.switch_to.default_content()
            return True

        # 5. 발행 확인 버튼 클릭
        confirm_btn = None
        try:
            confirm_btn = driver.find_element(By.CSS_SELECTOR, "button.confirm_btn__WEaBq")
        except:
            for btn in driver.find_elements(By.TAG_NAME, "button"):
                try:
                    cls = btn.get_attribute("class") or ""
                    if btn.is_displayed() and btn.text.strip() == "발행" and "confirm" in cls:
                        confirm_btn = btn
                        break
                except:
                    pass

        if confirm_btn:
            driver.execute_script("arguments[0].click();", confirm_btn)
            print("    발행(비공개) 확인 클릭")
            time.sleep(3)
        else:
            print("    발행 확인 버튼을 찾을 수 없습니다.")
            input("    수동 발행 후 Enter... ")

        print("    글 비공개 처리 완료!")
        driver.switch_to.default_content()
        return True

    except Exception as e:
        print(f"    글 비공개 처리 오류: {e}")
        driver.switch_to.default_content()
        return False


def make_cafe_post_private(driver, post_url):
    """카페 글을 멤버공개로 전환 (수정 → 새 탭 → 공개설정 → 멤버공개 → 등록)"""
    from selenium.webdriver.common.action_chains import ActionChains

    try:
        # 1. cafe_main iframe에서 수정 버튼 클릭 → 새 탭 열림
        switch_to_cafe_frame(driver)
        time.sleep(1)

        windows_before = driver.window_handles

        edit_btn = None
        for a in driver.find_elements(By.CSS_SELECTOR, "a.BaseButton"):
            try:
                if a.is_displayed() and a.text.strip() == "수정":
                    edit_btn = a
                    break
            except:
                pass

        if not edit_btn:
            for tag in ["a", "button", "span"]:
                for el in driver.find_elements(By.TAG_NAME, tag):
                    try:
                        if el.is_displayed() and el.text.strip() == "수정":
                            edit_btn = el
                            break
                    except:
                        pass
                if edit_btn:
                    break

        if not edit_btn:
            print("    수정 버튼을 찾을 수 없습니다. (다른 계정의 글일 수 있음)")
            driver.switch_to.default_content()
            return "need_relogin"

        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", edit_btn)
        time.sleep(0.5)
        ActionChains(driver).click(edit_btn).perform()
        print("    수정 버튼 클릭")

        # 2. 새 탭 전환
        for _ in range(10):
            time.sleep(1)
            if len(driver.window_handles) > len(windows_before):
                break

        windows_after = driver.window_handles
        if len(windows_after) <= len(windows_before):
            print("    새 탭이 열리지 않았습니다.")
            input("    수동으로 비공개 처리 후 Enter... ")
            driver.switch_to.default_content()
            return True

        new_window = [w for w in windows_after if w not in windows_before][0]
        original_window = windows_before[0]
        driver.switch_to.window(new_window)
        print(f"    에디터 탭 전환: {driver.current_url[:80]}")
        time.sleep(5)

        # 3. 공개 설정 버튼 클릭 (class: btn_open_set)
        open_set_btn = None
        try:
            open_set_btn = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button.btn_open_set"))
            )
        except:
            for btn in driver.find_elements(By.TAG_NAME, "button"):
                try:
                    if btn.is_displayed() and "공개" in btn.text and "설정" in btn.text:
                        open_set_btn = btn
                        break
                except:
                    pass

        if open_set_btn:
            driver.execute_script("arguments[0].click();", open_set_btn)
            print("    공개 설정 패널 열기")
            time.sleep(1)
        else:
            print("    공개 설정 버튼을 찾을 수 없습니다.")

        # 4. 멤버공개 라디오 선택 (div.FormInputRadio 안의 label)
        member_set = False
        for label in driver.find_elements(By.TAG_NAME, "label"):
            try:
                if label.is_displayed() and label.text.strip() == "멤버공개":
                    driver.execute_script("arguments[0].click();", label)
                    member_set = True
                    print("    멤버공개 선택")
                    time.sleep(1)
                    break
            except:
                pass

        if not member_set:
            # FormInputRadio div 클릭 시도
            for div in driver.find_elements(By.CSS_SELECTOR, "div.FormInputRadio"):
                try:
                    if div.is_displayed() and "멤버" in div.text:
                        driver.execute_script("arguments[0].click();", div)
                        member_set = True
                        print("    멤버공개 선택 (div)")
                        time.sleep(1)
                        break
                except:
                    pass

        if not member_set:
            print("    멤버공개를 자동 선택할 수 없습니다.")
            input("    수동으로 멤버공개 선택 후 Enter... ")

        # 5. 검색 · 네이버 서비스공개 체크 해제 (div.FormInputCheck)
        for label in driver.find_elements(By.TAG_NAME, "label"):
            try:
                txt = label.text.strip()
                if not label.is_displayed():
                    continue
                if "검색" in txt and "서비스" in txt:
                    # label 안의 checkbox 상태 확인
                    try:
                        cb = label.find_element(By.CSS_SELECTOR, "input[type='checkbox']")
                        if cb.is_selected():
                            driver.execute_script("arguments[0].click();", label)
                            print("    검색·서비스공개 체크 해제")
                            time.sleep(0.5)
                        else:
                            print("    검색·서비스공개 이미 해제됨")
                    except:
                        # checkbox를 못 찾으면 FormInputCheck div에서 시도
                        try:
                            parent = label.find_element(By.XPATH, "..")
                            cb = parent.find_element(By.CSS_SELECTOR, "input[type='checkbox']")
                            if cb.is_selected():
                                driver.execute_script("arguments[0].click();", label)
                                print("    검색·서비스공개 체크 해제")
                                time.sleep(0.5)
                            else:
                                print("    검색·서비스공개 이미 해제됨")
                        except:
                            # 그래도 못 찾으면 그냥 label 클릭 (토글)
                            driver.execute_script("arguments[0].click();", label)
                            print("    검색·서비스공개 클릭 (토글)")
                            time.sleep(0.5)
                    break
            except:
                pass

        # 6. 등록 버튼 클릭
        time.sleep(1)
        submit_btn = None
        # a.BaseButton 안의 span.BaseButton__txt "등록"
        for a in driver.find_elements(By.CSS_SELECTOR, "a.BaseButton"):
            try:
                if a.is_displayed() and a.text.strip() == "등록":
                    submit_btn = a
                    break
            except:
                pass
        # fallback: button
        if not submit_btn:
            for btn in driver.find_elements(By.TAG_NAME, "button"):
                try:
                    if btn.is_displayed() and btn.text.strip() == "등록":
                        submit_btn = btn
                        break
                except:
                    pass

        if submit_btn:
            driver.execute_script("arguments[0].click();", submit_btn)
            print("    등록 버튼 클릭")
            time.sleep(3)
        else:
            print("    등록 버튼을 찾을 수 없습니다.")
            input("    수동 등록 후 Enter... ")

        # 7. 새 탭 닫고 원래 탭으로 복귀
        try:
            driver.close()
            driver.switch_to.window(original_window)
        except:
            pass

        print("    카페 글 멤버공개 처리 완료!")
        driver.switch_to.default_content()
        return True

    except Exception as e:
        print(f"    카페 글 비공개 처리 오류: {e}")
        # 원래 탭으로 복귀 시도
        try:
            if len(driver.window_handles) > 1:
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
        except:
            pass
        driver.switch_to.default_content()
        return False


def make_post_public(driver, post_url):
    """블로그 글을 공개로 전환 (수정 → 발행 → 전체 공개 → 발행)"""
    try:
        switch_to_blog_frame(driver)
        time.sleep(1)

        edit_btn = None
        for el in driver.find_elements(By.TAG_NAME, "a"):
            try:
                txt = el.text.strip()
                cls = el.get_attribute("class") or ""
                if txt == "수정" and "_activeId" in cls:
                    edit_btn = el
                    break
            except:
                pass

        if not edit_btn:
            print("    수정 버튼을 찾을 수 없습니다. (다른 계정의 글일 수 있음)")
            driver.switch_to.default_content()
            return "need_relogin"

        driver.execute_script("arguments[0].click();", edit_btn)
        print("    수정 버튼 클릭")
        time.sleep(5)

        driver.switch_to.default_content()
        try:
            iframe = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "mainFrame"))
            )
            driver.switch_to.frame(iframe)
        except:
            print("    에디터 로드 실패")
            driver.switch_to.default_content()
            return False

        # 발행 버튼 클릭
        publish_btn = None
        try:
            publish_btn = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button.publish_btn__m9KHH"))
            )
        except:
            for btn in driver.find_elements(By.TAG_NAME, "button"):
                try:
                    if btn.is_displayed() and btn.text.strip() == "발행":
                        publish_btn = btn
                        break
                except:
                    pass

        if not publish_btn:
            print("    발행 버튼을 찾을 수 없습니다.")
            input("    공개 처리 후 Enter... ")
            driver.switch_to.default_content()
            return True

        driver.execute_script("arguments[0].click();", publish_btn)
        print("    발행 버튼 클릭 (설정 패널 열기)")
        time.sleep(2)

        # 전체 공개 라디오 버튼 클릭
        public_clicked = False
        for label in driver.find_elements(By.CSS_SELECTOR, "label.radio_label__mB6ia"):
            try:
                txt = label.text.strip()
                if label.is_displayed() and ("전체 공개" in txt or "전체공개" in txt):
                    driver.execute_script("arguments[0].click();", label)
                    public_clicked = True
                    print("    전체 공개 선택")
                    time.sleep(1)
                    break
            except:
                pass

        if not public_clicked:
            for span in driver.find_elements(By.CSS_SELECTOR, "span.input_radio__yZcoa"):
                try:
                    txt = span.text.strip()
                    if span.is_displayed() and ("전체 공개" in txt or "전체공개" in txt):
                        driver.execute_script("arguments[0].click();", span)
                        public_clicked = True
                        print("    전체 공개 선택 (span)")
                        time.sleep(1)
                        break
                except:
                    pass

        if not public_clicked:
            print("    전체 공개 옵션을 찾을 수 없습니다.")
            input("    공개 처리 후 Enter... ")
            driver.switch_to.default_content()
            return True

        # 발행 설정 체크박스 체크 (공감허용, 외부 공유 허용 등)
        # "기본값으로 유지", "공지사항" 은 제외
        SKIP_KEYWORDS = ["기본값", "공지"]
        try:
            for label in driver.find_elements(By.CSS_SELECTOR, "label.checkbox_label__n5RMI, label[class*='checkbox']"):
                try:
                    if not label.is_displayed():
                        continue
                    label_text = label.text.strip()
                    if any(kw in label_text for kw in SKIP_KEYWORDS):
                        print(f"    건너뜀: {label_text[:20]}")
                        continue
                    cb = None
                    try:
                        cb = label.find_element(By.CSS_SELECTOR, "input[type='checkbox']")
                    except:
                        label_for = label.get_attribute("for")
                        if label_for:
                            try:
                                cb = driver.find_element(By.ID, label_for)
                            except:
                                pass
                    if cb and not cb.is_selected():
                        driver.execute_script("arguments[0].click();", label)
                        print(f"    체크: {label_text[:20]}")
                        time.sleep(0.3)
                    elif cb and cb.is_selected():
                        print(f"    이미 체크됨: {label_text[:20]}")
                except:
                    pass
        except:
            pass

        # 발행 확인 버튼 클릭
        confirm_btn = None
        try:
            confirm_btn = driver.find_element(By.CSS_SELECTOR, "button.confirm_btn__WEaBq")
        except:
            for btn in driver.find_elements(By.TAG_NAME, "button"):
                try:
                    cls = btn.get_attribute("class") or ""
                    if btn.is_displayed() and btn.text.strip() == "발행" and "confirm" in cls:
                        confirm_btn = btn
                        break
                except:
                    pass

        if confirm_btn:
            driver.execute_script("arguments[0].click();", confirm_btn)
            print("    발행(공개) 확인 클릭")
            time.sleep(3)
        else:
            print("    발행 확인 버튼을 찾을 수 없습니다.")
            input("    수동 발행 후 Enter... ")

        print("    글 공개 처리 완료!")
        driver.switch_to.default_content()
        return True

    except Exception as e:
        print(f"    글 공개 처리 오류: {e}")
        driver.switch_to.default_content()
        return False


def make_cafe_post_public(driver, post_url):
    """카페 글을 전체공개로 전환 (수정 → 새 탭 → 공개설정 → 전체공개 → 등록)"""
    from selenium.webdriver.common.action_chains import ActionChains

    try:
        switch_to_cafe_frame(driver)
        time.sleep(1)

        windows_before = driver.window_handles

        edit_btn = None
        for a in driver.find_elements(By.CSS_SELECTOR, "a.BaseButton"):
            try:
                if a.is_displayed() and a.text.strip() == "수정":
                    edit_btn = a
                    break
            except:
                pass

        if not edit_btn:
            for tag in ["a", "button", "span"]:
                for el in driver.find_elements(By.TAG_NAME, tag):
                    try:
                        if el.is_displayed() and el.text.strip() == "수정":
                            edit_btn = el
                            break
                    except:
                        pass
                if edit_btn:
                    break

        if not edit_btn:
            print("    수정 버튼을 찾을 수 없습니다. (다른 계정의 글일 수 있음)")
            driver.switch_to.default_content()
            return "need_relogin"

        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", edit_btn)
        time.sleep(0.5)
        ActionChains(driver).click(edit_btn).perform()
        print("    수정 버튼 클릭")

        for _ in range(10):
            time.sleep(1)
            if len(driver.window_handles) > len(windows_before):
                break

        windows_after = driver.window_handles
        if len(windows_after) <= len(windows_before):
            print("    새 탭이 열리지 않았습니다.")
            input("    수동으로 공개 처리 후 Enter... ")
            driver.switch_to.default_content()
            return True

        new_window = [w for w in windows_after if w not in windows_before][0]
        original_window = windows_before[0]
        driver.switch_to.window(new_window)
        print(f"    에디터 탭 전환: {driver.current_url[:80]}")
        time.sleep(5)

        # 공개 설정 버튼 클릭
        open_set_btn = None
        try:
            open_set_btn = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button.btn_open_set"))
            )
        except:
            for btn in driver.find_elements(By.TAG_NAME, "button"):
                try:
                    if btn.is_displayed() and "공개" in btn.text and "설정" in btn.text:
                        open_set_btn = btn
                        break
                except:
                    pass

        if open_set_btn:
            driver.execute_script("arguments[0].click();", open_set_btn)
            print("    공개 설정 패널 열기")
            time.sleep(1)
        else:
            print("    공개 설정 버튼을 찾을 수 없습니다.")

        # 전체공개 라디오 선택
        public_set = False
        for label in driver.find_elements(By.TAG_NAME, "label"):
            try:
                if label.is_displayed() and label.text.strip() == "전체공개":
                    driver.execute_script("arguments[0].click();", label)
                    public_set = True
                    print("    전체공개 선택")
                    time.sleep(1)
                    break
            except:
                pass

        if not public_set:
            for div in driver.find_elements(By.CSS_SELECTOR, "div.FormInputRadio"):
                try:
                    if div.is_displayed() and "전체" in div.text:
                        driver.execute_script("arguments[0].click();", div)
                        public_set = True
                        print("    전체공개 선택 (div)")
                        time.sleep(1)
                        break
                except:
                    pass

        if not public_set:
            print("    전체공개를 자동 선택할 수 없습니다.")
            input("    수동으로 전체공개 선택 후 Enter... ")

        # 검색 · 네이버 서비스공개 체크 설정
        for label in driver.find_elements(By.TAG_NAME, "label"):
            try:
                txt = label.text.strip()
                if not label.is_displayed():
                    continue
                if "검색" in txt and "서비스" in txt:
                    try:
                        cb = label.find_element(By.CSS_SELECTOR, "input[type='checkbox']")
                        if not cb.is_selected():
                            driver.execute_script("arguments[0].click();", label)
                            print("    검색·서비스공개 체크")
                            time.sleep(0.5)
                        else:
                            print("    검색·서비스공개 이미 체크됨")
                    except:
                        try:
                            parent = label.find_element(By.XPATH, "..")
                            cb = parent.find_element(By.CSS_SELECTOR, "input[type='checkbox']")
                            if not cb.is_selected():
                                driver.execute_script("arguments[0].click();", label)
                                print("    검색·서비스공개 체크")
                                time.sleep(0.5)
                            else:
                                print("    검색·서비스공개 이미 체크됨")
                        except:
                            driver.execute_script("arguments[0].click();", label)
                            print("    검색·서비스공개 클릭 (토글)")
                            time.sleep(0.5)
                    break
            except:
                pass

        # 등록 버튼 클릭
        time.sleep(1)
        submit_btn = None
        for a in driver.find_elements(By.CSS_SELECTOR, "a.BaseButton"):
            try:
                if a.is_displayed() and a.text.strip() == "등록":
                    submit_btn = a
                    break
            except:
                pass
        if not submit_btn:
            for btn in driver.find_elements(By.TAG_NAME, "button"):
                try:
                    if btn.is_displayed() and btn.text.strip() == "등록":
                        submit_btn = btn
                        break
                except:
                    pass

        if submit_btn:
            driver.execute_script("arguments[0].click();", submit_btn)
            print("    등록 버튼 클릭")
            time.sleep(3)
        else:
            print("    등록 버튼을 찾을 수 없습니다.")
            input("    수동 등록 후 Enter... ")

        try:
            driver.close()
            driver.switch_to.window(original_window)
        except:
            pass

        print("    카페 글 전체공개 처리 완료!")
        driver.switch_to.default_content()
        return True

    except Exception as e:
        print(f"    카페 글 공개 처리 오류: {e}")
        try:
            if len(driver.window_handles) > 1:
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
        except:
            pass
        driver.switch_to.default_content()
        return False


def find_and_reply(driver, target_comment, reply_text, post_url=""):
    """댓글을 찾아 대댓글 작성"""
    if is_cafe_url(post_url):
        switch_to_cafe_frame(driver)
    else:
        switch_to_blog_frame(driver)
    time.sleep(2)

    # ── 1단계: 댓글 목록 펼치기 (_cmtList 클릭) ──
    try:
        cmt_btn = driver.find_element(By.CSS_SELECTOR, "a._cmtList")
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", cmt_btn)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", cmt_btn)
        print("    댓글 목록 펼치기 클릭")
        time.sleep(3)
    except:
        # _cmtList가 없으면 이미 펼쳐진 상태이거나 다른 구조
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight * 0.7)")
        time.sleep(2)

    # ── 2단계: u_cbox 로드 대기 ──
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".u_cbox_comment_box"))
        )
        print("    댓글 로드 완료")
    except:
        print("    댓글 로드 대기 시간 초과")

    # 댓글 영역 스크롤
    try:
        cbox = driver.find_element(By.CSS_SELECTOR, ".u_cbox")
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", cbox)
        time.sleep(1)
    except:
        pass

    expand_all_comments(driver)

    # 댓글 요소 찾기
    comments = []
    for sel in [".u_cbox_comment_box", ".u_cbox_comment",
                "li.u_cbox_comment", ".comment_item"]:
        comments = driver.find_elements(By.CSS_SELECTOR, sel)
        if comments:
            break

    if not comments:
        print("    댓글 요소를 찾을 수 없습니다.")
        driver.switch_to.default_content()
        return False

    print(f"    {len(comments)}개 댓글 발견")
    target_clean = target_comment.strip()

    for comment_elem in comments:
        try:
            # 댓글 텍스트 추출
            comment_text = ""
            for ts in [".u_cbox_contents", ".u_cbox_text_wrap",
                       ".u_cbox_text", "span.u_cbox_contents", ".comment_text"]:
                try:
                    el = comment_elem.find_element(By.CSS_SELECTOR, ts)
                    comment_text = el.text.strip()
                    if comment_text:
                        break
                except:
                    continue
            if not comment_text:
                continue

            # 매칭
            t1 = re.sub(r'\s+', '', target_clean)
            t2 = re.sub(r'\s+', '', comment_text)
            if t1 not in t2 and t2 not in t1:
                continue

            print(f"    매칭됨: \"{comment_text[:40]}\"")

            # ── 답글 버튼 클릭 ──
            reply_btn = None
            for rbs in [".u_cbox_btn_reply", "button.u_cbox_btn_reply",
                        "a.u_cbox_btn_reply", ".btn_reply"]:
                try:
                    reply_btn = comment_elem.find_element(By.CSS_SELECTOR, rbs)
                    if reply_btn.is_displayed():
                        break
                    reply_btn = None
                except:
                    continue
            if not reply_btn:
                for tag in ["button", "a", "span"]:
                    for el in comment_elem.find_elements(By.TAG_NAME, tag):
                        if "답글" in el.text:
                            reply_btn = el
                            break
                    if reply_btn:
                        break
            if not reply_btn:
                print("    답글 버튼을 찾을 수 없습니다.")
                continue

            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", reply_btn)
            time.sleep(0.5)
            driver.execute_script("arguments[0].click();", reply_btn)
            print("    답글 버튼 클릭")
            time.sleep(2)

            # ── 대댓글 입력 (contenteditable div) ──
            text_input = None

            # 1) 답글 영역에서 플레이스홀더(가이드) 클릭하여 입력창 활성화
            try:
                reply_areas = driver.find_elements(By.CSS_SELECTOR, ".u_cbox_reply_area")
                for ra in reply_areas:
                    if ra.is_displayed():
                        # 가이드(플레이스홀더) 클릭 → 입력창 활성화
                        try:
                            guide = ra.find_element(By.CSS_SELECTOR, ".u_cbox_guide")
                            driver.execute_script("arguments[0].click();", guide)
                            time.sleep(1)
                        except:
                            # 가이드 없으면 write 영역 클릭
                            try:
                                write_box = ra.find_element(By.CSS_SELECTOR, ".u_cbox_write")
                                driver.execute_script("arguments[0].click();", write_box)
                                time.sleep(1)
                            except:
                                pass
                        # contenteditable div 찾기
                        try:
                            text_input = ra.find_element(
                                By.CSS_SELECTOR, "div.u_cbox_text[contenteditable='true']")
                            if text_input.is_displayed():
                                break
                            text_input = None
                        except:
                            text_input = None
            except:
                pass

            # 2) 전체 페이지에서 찾기
            if not text_input:
                # 가이드 먼저 클릭
                try:
                    for guide in driver.find_elements(By.CSS_SELECTOR, ".u_cbox_guide"):
                        if guide.is_displayed():
                            driver.execute_script("arguments[0].click();", guide)
                            time.sleep(1)
                            break
                except:
                    pass
                try:
                    for el in driver.find_elements(
                            By.CSS_SELECTOR, "div.u_cbox_text[contenteditable='true']"):
                        if el.is_displayed():
                            text_input = el
                            break
                except:
                    pass

            if not text_input:
                print("    대댓글 입력창을 찾을 수 없습니다.")
                continue

            # JavaScript로 포커스 & 클릭 (가이드 오버레이 우회)
            driver.execute_script("arguments[0].focus();", text_input)
            driver.execute_script("arguments[0].click();", text_input)
            time.sleep(0.5)
            # 기존 내용 지우기
            from selenium.webdriver.common.keys import Keys
            text_input.send_keys(Keys.CONTROL, 'a')
            text_input.send_keys(Keys.DELETE)
            time.sleep(0.3)
            # 줄바꿈(\n) 처리: Shift+Enter
            for char in reply_text:
                if char == '\n':
                    text_input.send_keys(Keys.SHIFT, Keys.ENTER)
                else:
                    text_input.send_keys(char)
                time.sleep(0.02)
            print(f"    대댓글 입력 완료: \"{reply_text[:40]}\"")
            time.sleep(1)

            # ── 등록 버튼 ──
            submit_btn = None
            # 답글 영역 안의 등록 버튼 우선
            try:
                reply_areas = driver.find_elements(By.CSS_SELECTOR, ".u_cbox_reply_area")
                for ra in reply_areas:
                    if ra.is_displayed():
                        try:
                            submit_btn = ra.find_element(By.CSS_SELECTOR, ".u_cbox_btn_upload")
                            if submit_btn.is_displayed():
                                break
                            submit_btn = None
                        except:
                            pass
            except:
                pass
            # 전체에서 찾기
            if not submit_btn:
                for ss in [".u_cbox_btn_upload", "button.u_cbox_btn_upload"]:
                    try:
                        for btn in driver.find_elements(By.CSS_SELECTOR, ss):
                            if btn.is_displayed():
                                submit_btn = btn
                                break
                    except:
                        pass
                    if submit_btn:
                        break
            if not submit_btn:
                for btn in driver.find_elements(By.TAG_NAME, "button"):
                    if btn.is_displayed() and btn.text.strip() in ["등록", "작성", "게시"]:
                        submit_btn = btn
                        break

            if not submit_btn:
                print("    등록 버튼을 찾을 수 없습니다. 수동 등록해주세요.")
                input("    등록 후 Enter... ")
                driver.switch_to.default_content()
                return True

            driver.execute_script("arguments[0].click();", submit_btn)
            print("    등록 완료!")
            time.sleep(2)
            driver.switch_to.default_content()
            return True

        except Exception as e:
            print(f"    처리 중 오류: {e}")
            continue

    print(f"    \"{target_clean[:30]}\" 댓글을 찾지 못했습니다.")
    driver.switch_to.default_content()
    return False


def is_post_author(driver, post_url):
    """현재 로그인 계정이 글 작성자인지 확인 (수정 버튼 존재 여부)"""
    if is_cafe_url(post_url):
        switch_to_cafe_frame(driver)
        time.sleep(1)
        for a in driver.find_elements(By.CSS_SELECTOR, "a.BaseButton"):
            try:
                if a.is_displayed() and a.text.strip() == "수정":
                    driver.switch_to.default_content()
                    return True
            except:
                pass
        for tag in ["a", "button", "span"]:
            for el in driver.find_elements(By.TAG_NAME, tag):
                try:
                    if el.is_displayed() and el.text.strip() == "수정":
                        driver.switch_to.default_content()
                        return True
                except:
                    pass
    else:
        switch_to_blog_frame(driver)
        time.sleep(1)
        for el in driver.find_elements(By.TAG_NAME, "a"):
            try:
                txt = el.text.strip()
                cls = el.get_attribute("class") or ""
                if txt == "수정" and "_activeId" in cls:
                    driver.switch_to.default_content()
                    return True
            except:
                pass
    driver.switch_to.default_content()
    return False


def process_item(driver, ws, item, label=""):
    """단일 항목 처리. 반환: '완료', '대댓글 실패', '재로그인 필요', '비공개 실패', '공개 실패', '실패'"""
    print(f"\n{'─'*55}")
    tags = []
    if item["need_reply"]:
        tags.append("대댓글")
    if item["need_private"]:
        tags.append("비공개")
    if item["need_public"]:
        tags.append("공개")
    print(f"[{label}] 행{item['row_num']} [{'+'.join(tags)}]")
    print(f"  링크: {item['link']}")
    if item["need_reply"]:
        print(f"  댓글: {item['comment'][:50]}")
        print(f"  대댓글: {item['reply'][:50]}")

    try:
        driver.get(item["link"])
        time.sleep(3)

        # ── 비공개 글 alert 감지 ──
        try:
            alert = driver.switch_to.alert
            alert_text = alert.text
            alert.accept()
            if "비공개" in alert_text:
                print(f"    → 비공개 글입니다. 다른 계정으로 재로그인 필요")
                return "재로그인 필요"
        except:
            pass

        # ── 작성자 확인 (수정 버튼 존재 여부) ──
        if not is_post_author(driver, item["link"]):
            print("    → 내 글이 아닙니다. 다른 계정으로 재로그인 필요")
            return "재로그인 필요"

        need_reload = False

        # ── 대댓글 작성 ──
        if item["need_reply"]:
            reply_ok = find_and_reply(driver, item["comment"], item["reply"], item["link"])
            if reply_ok:
                item["need_reply"] = False
                need_reload = True
                try:
                    ws.update_cell(item["row_num"], 4, True)
                    print("    ✓ D열 체크 완료")
                except Exception as e:
                    print(f"    D열 업데이트 실패: {e}")
            else:
                print("    ✗ 대댓글 실패 - 건너뜀")
                return "대댓글 실패"

        # ── 비공개 처리 ──
        if item["need_private"]:
            if need_reload:
                driver.get(item["link"])
                time.sleep(3)
                need_reload = False
            if is_cafe_url(item["link"]):
                priv_ok = make_cafe_post_private(driver, item["link"])
            else:
                priv_ok = make_post_private(driver, item["link"])
            if priv_ok == "need_relogin":
                print("    → 다른 계정으로 재로그인 후 처리 필요")
                return "재로그인 필요"
            elif priv_ok:
                item["need_private"] = False
                need_reload = True
                try:
                    ws.update_cell(item["row_num"], 6, True)
                    print("    ✓ F열 체크 완료")
                except Exception as e:
                    print(f"    F열 업데이트 실패: {e}")
            else:
                print("    ✗ 글 비공개 처리 실패")
                return "비공개 실패"

        # ── 공개 처리 ──
        if item["need_public"]:
            if need_reload:
                driver.get(item["link"])
                time.sleep(3)
            if is_cafe_url(item["link"]):
                pub_ok = make_cafe_post_public(driver, item["link"])
            else:
                pub_ok = make_post_public(driver, item["link"])
            if pub_ok == "need_relogin":
                print("    → 다른 계정으로 재로그인 후 처리 필요")
                return "재로그인 필요"
            elif pub_ok:
                item["need_public"] = False
                try:
                    ws.update_cell(item["row_num"], 8, True)
                    print("    ✓ H열 체크 완료")
                except Exception as e:
                    print(f"    H열 업데이트 실패: {e}")
            else:
                print("    ✗ 글 공개 처리 실패")
                return "공개 실패"

        return "완료"
    except Exception as e:
        print(f"  오류: {e}")
        return "실패"


# ─── 메인 ────────────────────────────────────────────
def main():
    print("=" * 55)
    print("  네이버 블로그/카페 대댓글 자동 작성 봇")
    print("  A:링크 B:댓글 C:대댓글 D:완료 E:비공개 F:비공개완료 G:공개 H:공개완료")
    print("=" * 55)

    # 1. Google Sheets 연결
    sheet_url = input("\nGoogle Sheets URL: ").strip()
    ws = connect_sheet(sheet_url)
    header, rows = get_rows(ws)

    # 처리 대상 확인
    pending = []
    for i, row in enumerate(rows):
        if len(row) < 1:
            continue
        link = row[0].strip()
        comment = row[1].strip() if len(row) > 1 else ""
        reply = row[2].strip() if len(row) > 2 else ""
        d_val = row[3].strip() if len(row) > 3 else ""
        e_val = row[4].strip() if len(row) > 4 else ""
        f_val = row[5].strip() if len(row) > 5 else ""
        g_val = row[6].strip() if len(row) > 6 else ""
        h_val = row[7].strip() if len(row) > 7 else ""

        if not link:
            continue

        need_reply = comment and reply and not is_checked(d_val)
        need_private = is_checked(e_val) and not is_checked(f_val)
        need_public = is_checked(g_val) and not is_checked(h_val)

        # 디버그: 각 행의 값 표시
        print(f"  행{i+2}: D=\"{d_val}\" E=\"{e_val}\" F=\"{f_val}\" G=\"{g_val}\" H=\"{h_val}\" → 댓글={need_reply} 비공개={need_private} 공개={need_public}")

        if not need_reply and not need_private and not need_public:
            continue

        pending.append({
            "row_num": i + 2,
            "link": link,
            "comment": comment,
            "reply": reply,
            "need_reply": need_reply,
            "need_private": need_private,
            "need_public": need_public,
        })

    if not pending:
        print("\n처리할 항목이 없습니다.")
        return

    print(f"\n처리 대기: {len(pending)}건")
    for p in pending:
        ptype = "카페" if is_cafe_url(p["link"]) else "블로그"
        tags = [ptype]
        if p["need_reply"]:
            tags.append("대댓글")
        if p["need_private"]:
            tags.append("비공개")
        if p["need_public"]:
            tags.append("공개")
        print(f"  행{p['row_num']}: {p['link'][:50]}... [{'+'.join(tags)}]")

    # 2. 브라우저 & 로그인 체크
    print("\n브라우저를 여는 중...")
    driver = setup_browser()

    # 로그인 상태 확인
    driver.get("https://www.naver.com")
    time.sleep(2)
    logged_in = False
    try:
        # 네이버 메인에서 로그인 여부 확인 (로그인 버튼이 없으면 로그인 상태)
        login_btns = driver.find_elements(By.CSS_SELECTOR, ".MyView-module__link_login___HpHMW, a.link_login, .lg_local_btn, a[href*='nidlogin']")
        if not login_btns or not any(b.is_displayed() for b in login_btns):
            logged_in = True
    except:
        pass

    if logged_in:
        print("[OK] 이미 로그인되어 있습니다!")
    else:
        driver.get("https://nid.naver.com/nidlogin.login")
        input("\n>>> 네이버에 로그인한 후 Enter를 눌러주세요... ")

    # 3. 작업 시작
    results = []

    for i, item in enumerate(pending):
        label = f"{i+1}/{len(pending)}"
        status = process_item(driver, ws, item, label)
        results.append((item["row_num"], status))
        time.sleep(2)

    # 4. 결과 보고 + 재로그인/재시도 루프
    while True:
        sep = '=' * 55
        print()
        print(sep)
        print('결과 요약')
        print(sep)
        ok_count = sum(1 for _, s in results if s == '완료')
        relogin_list = [(r, s) for r, s in results if '재로그인' in s]
        fail_list = [(r, s) for r, s in results if s != '완료' and '재로그인' not in s]
        print(f'  성공: {ok_count}건  |  재로그인 필요: {len(relogin_list)}건  |  실패: {len(fail_list)}건')
        for row_num, status in results:
            print(f'  행 {row_num}: {status}')

        if not relogin_list and not fail_list:
            break

        # ── 재로그인 필요 항목 ──
        if relogin_list:
            print(f'\n재로그인이 필요한 항목 ({len(relogin_list)}건):')
            for row_num, _ in relogin_list:
                for p in pending:
                    if p['row_num'] == row_num:
                        print(f'  행{row_num}: {p["link"][:60]}...')
                        break

            ans = input('\n다른 계정으로 로그인하시겠습니까? (y/n): ').strip().lower()
            if ans == 'y':
                driver.get("https://nid.naver.com/nidlogin.login")
                input(">>> 다른 계정으로 로그인한 후 Enter를 눌러주세요... ")

                relogin_rows = [r for r, _ in relogin_list]
                retry_items = [p for p in pending if p['row_num'] in relogin_rows]
                results = [r for r in results if r[0] not in relogin_rows]

                for i, item in enumerate(retry_items):
                    label = f"재로그인 {i+1}/{len(retry_items)}"
                    status = process_item(driver, ws, item, label)
                    results.append((item['row_num'], status))
                    time.sleep(2)
                continue

        # ── 일반 실패 항목 ──
        if fail_list:
            print(f'\n실패 항목 ({len(fail_list)}건):')
            for row_num, status in fail_list:
                for p in pending:
                    if p['row_num'] == row_num:
                        print(f'  행{row_num}: {p["link"][:60]}... [{status}]')
                        break

            ans = input('실패 건을 다시 시도하시겠습니까? (y/n): ').strip().lower()
            if ans == 'y':
                fail_rows = [r for r, _ in fail_list]
                retry_items = [p for p in pending if p['row_num'] in fail_rows]
                results = [r for r in results if r[0] not in fail_rows]

                for i, item in enumerate(retry_items):
                    label = f"재시도 {i+1}/{len(retry_items)}"
                    status = process_item(driver, ws, item, label)
                    results.append((item['row_num'], status))
                    time.sleep(2)
                continue

        break

    input('작업 완료. Enter -> 브라우저 닫기...')
    driver.quit()


if __name__ == '__main__':
    main()
