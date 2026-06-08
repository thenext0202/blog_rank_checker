"""Selenium 브라우저 관리 — headless/visible 드라이버 생성"""

import os

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

from shared.paths import CHROME_PROFILE

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def create_headless_driver():
    """headless Chrome 드라이버 생성 (MKT 링크 대조, 댓글 알림용)"""
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument(f"user-agent={USER_AGENT}")

    driver = _build_driver(opts)
    _hide_webdriver(driver)
    return driver


def create_visible_driver():
    """visible Chrome 드라이버 생성 (대댓글 봇, 자동발행용)
    chrome_profile/ 폴더에 로그인 세션 유지
    """
    opts = Options()
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument(f"--user-data-dir={CHROME_PROFILE}")
    opts.add_argument(f"user-agent={USER_AGENT}")

    driver = _build_driver(opts)
    _hide_webdriver(driver)
    driver.set_page_load_timeout(30)
    return driver


def _build_driver(opts):
    """Chrome 드라이버 빌드 (환경변수 CHROME_BIN 지원)"""
    chrome_bin = os.environ.get("CHROME_BIN")
    if chrome_bin:
        opts.binary_location = chrome_bin
        return webdriver.Chrome(options=opts)
    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=opts,
    )


def _hide_webdriver(driver):
    """navigator.webdriver 속성 숨기기"""
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"},
    )
