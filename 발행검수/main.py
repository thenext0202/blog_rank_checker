"""발행 원고 검수 프로그램 v1.1
- 자사 발행리스트에서 선택 날짜 발행 건 조회
- 원본 DOCX 다운로드 후 지시사항 추출
- 블로그 크롤링 후 대조 검수
- 수정 요청 메시지 자동 생성 (tkinter GUI)
"""

import sys, io, os, re, time, datetime, tempfile, zipfile, threading, webbrowser, html, shutil
from urllib.parse import unquote, urlparse, parse_qsl, urlencode
import requests
from collections import OrderedDict

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build as _build_service
from googleapiclient.http import MediaIoBaseDownload
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from docx import Document
import pyperclip

# ── 설정 ──────────────────────────────────────────────
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# EXE: credentials.json을 EXE 옆에서 먼저 찾고, 없으면 기존 경로 사용
_cred_local = os.path.join(BASE_DIR, "credentials.json")
_cred_orig = os.path.join(
    os.path.dirname(BASE_DIR), "manuscript_generator", "credentials.json"
)
CRED_FILE = _cred_local if os.path.exists(_cred_local) else _cred_orig
SPREADSHEET_ID = "1jflcdbmBjQsY4hp8rNULXGGVqb64fGno4kudlTJoqM4"
DRIVE_FOLDER_ID = "1V3mBxn0bUdMRBCTURJob1n94RN7DNRHR"

SCOPE = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

INSTRUCTION_KEYWORDS = [
    "글자크기", "글자 크기", "인용구", "큰 글자", "큰글자",
    "줄 간격", "줄간격", "링크 배너", "배너 삽입",
    "블로그 내 링크", "링크 도구", "부탁드", "부탁 드",
    "중간 정렬", "글자 색깔", "글자색", "스티커",
    "적용 부탁", "확인 부탁", "안내 사항", "이미지 참고",
    "폴더 내 이미지", "삽입 부탁", "삭제 부탁",
]

BLOG_CHECK_KEYWORDS = [
    "글자크기", "글자 크기", "인용구 ", "줄 간격", "줄간격",
    "배너 삽입", "중간 정렬", "큰글자크기", "큰 글자 크기",
    "★블로거 요청사항★", "요청 사항", "블로거 요청",
]

EMPTY_DOCX = {"instructions": [], "image_numbers": [], "ad_links": [], "content": [], "full_text": "", "format_reqs": [], "link_reqs": []}
EMPTY_BLOG = {"title": "", "body": "", "links": [], "image_links": [], "widget_links": [], "format_info": [], "image_link_map": {}, "image_total": 0, "all_mkt_links": [], "link_results": []}


# ═══════════════════════════════════════════════════════
#  백엔드
# ═══════════════════════════════════════════════════════
def get_creds():
    return Credentials.from_service_account_file(CRED_FILE, scopes=SCOPE)


def _cell(row, idx):
    return row[idx].strip() if len(row) > idx else ""


def date_variants(d):
    return {
        f"{d.month}/{d.day}",
        f"{d.month:02d}/{d.day:02d}",
        f"{d.month}/{d.day:02d}",
        f"{d.month:02d}/{d.day}",
        d.strftime("%Y-%m-%d"),
        d.strftime("%Y.%m.%d"),
    }


def fetch_items(creds, target_date):
    gc = gspread.authorize(creds)
    ss = gc.open_by_key(SPREADSHEET_ID)
    ws_pub = ss.worksheet("자사 발행리스트")
    ws_man = ss.worksheet("원고리스트")
    pub_rows = ws_pub.get_all_values()
    man_rows = ws_man.get_all_values()
    targets = date_variants(target_date)

    man_lookup = {}
    for row in man_rows[1:]:
        param = _cell(row, 9)
        if param:
            man_lookup[param] = {
                "product_link": _cell(row, 27),
                "ad_link": _cell(row, 28),
                "filename": _cell(row, 32),
            }

    items = []
    for i, row in enumerate(pub_rows[1:], start=2):
        if _cell(row, 0) not in targets:
            continue
        param = _cell(row, 7)
        man = man_lookup.get(param, {})
        items.append({
            "row": i,
            "param": param,
            "title": _cell(row, 11),
            "link": _cell(row, 12),
            "publisher": _cell(row, 13),
            "product_link": man.get("product_link", ""),
            "ad_link": man.get("ad_link", ""),
            "filename": man.get("filename", ""),
        })
    return items


def _strip_pub_date(base):
    """파일명에서 발행일(YYMMDD) 부분 제거하여 후보 목록 반환.
    예: '이은주_260316중성지방_260318_후기형_bc'
      → '이은주_260316중성지방_후기형_bc' (두 번째 _YYMMDD 제거)
    """
    # _YYMMDD_ 패턴을 모두 찾아서, 각각 하나씩 제거한 후보 생성
    candidates = []
    for m in re.finditer(r"_(\d{6})_", base):
        stripped = base[:m.start()] + "_" + base[m.end():]
        candidates.append(stripped)
    return candidates


def find_and_download(creds, filename):
    service = _build_service("drive", "v3", credentials=creds)
    base = os.path.splitext(filename)[0] if "." in filename else filename
    escaped = base.replace("'", "\\'")

    # 1차: 원본 파일명으로 검색
    query = f"name contains '{escaped}' and trashed = false"
    results = service.files().list(
        q=query, fields="files(id, name, mimeType)",
        supportsAllDrives=True, includeItemsFromAllDrives=True, corpora="allDrives",
    ).execute()
    files = results.get("files", [])

    # 2차: 실패 시 발행일 제거한 파일명으로 재검색
    if not files:
        for alt in _strip_pub_date(base):
            alt_escaped = alt.replace("'", "\\'")
            query = f"name contains '{alt_escaped}' and trashed = false"
            results = service.files().list(
                q=query, fields="files(id, name, mimeType)",
                supportsAllDrives=True, includeItemsFromAllDrives=True, corpora="allDrives",
            ).execute()
            files = results.get("files", [])
            if files:
                break

    if not files:
        return None, None

    target = None
    for f in files:
        if f["name"].lower().endswith(".docx"):
            target = f
            break
    if not target:
        for f in files:
            if f["name"].lower().endswith(".zip"):
                target = f
                break
    if not target:
        target = files[0]

    tmp_dir = tempfile.mkdtemp()
    dl_path = os.path.join(tmp_dir, target["name"])
    req = service.files().get_media(fileId=target["id"], supportsAllDrives=True)
    fh = io.BytesIO()
    dl = MediaIoBaseDownload(fh, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    with open(dl_path, "wb") as f:
        f.write(fh.getvalue())

    if dl_path.lower().endswith(".zip"):
        with zipfile.ZipFile(dl_path, "r") as zf:
            for name in zf.namelist():
                if name.lower().endswith(".docx") and not name.startswith("__MACOSX"):
                    zf.extract(name, tmp_dir)
                    return os.path.join(tmp_dir, name), tmp_dir
        return None, tmp_dir
    return dl_path, tmp_dir


def parse_docx(docx_path):
    doc = Document(docx_path)
    instructions, image_numbers, ad_links, content = [], [], [], []
    full_lines = []
    format_reqs = []
    link_reqs = []
    prev_line = ""
    in_req = False

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            full_lines.append("")
            continue
        full_lines.append(text)

        if "★" in text and "요청" in text:
            in_req = True
            instructions.append(text)
            continue
        if in_req:
            if text.startswith("---") or text == "---":
                in_req = False
                continue
            # 지시사항 특성이 있는 줄만 캡처, 아니면 섹션 종료
            is_instr_like = (
                text.startswith(("ㄴ", "-", "·", "*", "•"))
                or any(kw in text for kw in INSTRUCTION_KEYWORDS)
                or "★" in text
                or "부탁" in text or "요청" in text
                or text.startswith(("제목", "해시태그"))
                or re.match(r"^https?://", text)
            )
            if is_instr_like:
                instructions.append(text)
                continue
            else:
                in_req = False
                # 아래 일반 파싱 로직으로 계속 진행
        # ㄴ 으로 시작하는 지시사항 (키워드 매칭 또는 짧은 지시)
        if text.startswith("ㄴ"):
            body_after = text[1:].strip()
            # 서식 정보 추출 → 바로 위 콘텐츠(format_reqs[-1])에만 적용
            fmt = _parse_format_info(body_after)
            if fmt and not fmt.get("quote_end") and format_reqs:
                for k in ("quote", "font_size", "bold", "color"):
                    if k in fmt:
                        format_reqs[-1][k] = fmt[k]
            # 링크 지시 추출 (bc1 → 이미지에 상품 링크 삽입)
            if "링크" in body_after and prev_line:
                link_reqs.append({"label": prev_line, "instruction": body_after})
            is_instruction = (
                any(kw in text for kw in INSTRUCTION_KEYWORDS)
                or "링크" in body_after
                or "연결" in body_after
                or "노출" in body_after
                or "적용" in body_after
                or "삭제" in body_after
                or "별도" in body_after
                or len(body_after) <= 30  # 짧은 ㄴ 라인은 대부분 지시
            )
            if is_instruction:
                instructions.append(text)
                continue
        if re.match(r"^\d{1,2}$", text):
            image_numbers.append(text)
            continue
        if re.match(r"^\d{1,2}(,\s*\d{1,2})+(\s*\(.*\))?$", text):
            image_numbers.append(text)
            continue
        if "광고 이미지 번호" in text:
            instructions.append(text)
            continue
        if text.startswith("광고 링크") and ":" in text:
            instructions.append(text)
            continue
        if re.match(r"^-?\s*해시태그", text):
            instructions.append(text)
            continue
        # #태그 #태그 형태의 해시태그 나열 (# HDL 같이 공백 있는 경우도 포함)
        if text.count("#") >= 2 and re.match(r"^#", text):
            instructions.append(text)
            continue
        if "<-" in text:
            instructions.append(text)
            continue
        if re.match(r"^제목\s*:", text):
            instructions.append(text)
            continue

        urls = re.findall(r"https?://[^\s<>\"]+", text)
        for url in urls:
            if "mkt.shopping.naver.com" in url or "smartstore" in url:
                ad_links.append(url)
        if urls and re.match(r"^https?://", text):
            continue

        # 서식 지시 텍스트는 콘텐츠가 아님
        if re.match(r"^(인용구|글자\s*크기|글꼴\s*두껍게|글자\s*색|밑줄|취소선|기울임)", text):
            # standalone 서식 라인 → 바로 위 콘텐츠에 적용
            fmt = _parse_format_info(text)
            if fmt and not fmt.get("quote_end") and format_reqs:
                for k in ("quote", "font_size", "bold", "color"):
                    if k in fmt:
                        format_reqs[-1][k] = fmt[k]
            instructions.append(text)
            continue

        if len(text) >= 5:
            content.append(text)
            format_reqs.append({
                "text": text,
                "quote": None,
                "font_size": None,
                "bold": False,
                "color": None,
            })

        prev_line = text

    return {"instructions": instructions, "image_numbers": image_numbers,
            "ad_links": ad_links, "content": content,
            "full_text": "\n".join(full_lines).strip(),
            "format_reqs": format_reqs, "link_reqs": link_reqs}


def setup_driver():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    driver = webdriver.Chrome(
        service=ChromeService(ChromeDriverManager().install()), options=opts
    )
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"},
    )
    return driver


def scrape_blog(driver, url):
    m = re.match(r"https?://(?:m\.)?blog\.naver\.com/([^/]+)/(\d+)", url)
    if m:
        bid, lno = m.groups()
        view_url = (
            f"https://blog.naver.com/PostView.naver"
            f"?blogId={bid}&logNo={lno}&redirect=Dlog&widgetTypeCall=true"
        )
    else:
        view_url = url

    driver.get(view_url)
    time.sleep(3)
    try:
        driver.switch_to.frame(driver.find_element(By.ID, "mainFrame"))
        time.sleep(1)
    except Exception:
        pass

    title = ""
    for sel in ["div.se-title-text span", "div.se-title-text", ".pcol1", "h3.se_textarea"]:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            title = el.text.strip()
            if title:
                break
        except Exception:
            continue

    body = ""
    for sel in ["div.se-main-container", "div#postViewArea", "div.post-view"]:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            body = el.text
            if body:
                break
        except Exception:
            continue
    if not body:
        try:
            body = driver.find_element(By.TAG_NAME, "body").text
        except Exception:
            pass

    links = []
    image_links = []
    widget_links = []
    seen = set()

    def _clean_href(href):
        href = html.unescape(href)
        m_out = re.search(r"[?&]url=(https?[^&]+)", href)
        if m_out:
            href = unquote(m_out.group(1))
        href = unquote(href)
        href = re.sub(r"[&?]NaPm=.*", "", href)
        return href

    def _skip(href):
        return (re.match(r"https?://blog\.naver\.com/", href)
                or re.match(r"https?://shopping\.naver\.com/ns/", href)
                or href.endswith("#")
                or not href.startswith("http"))

    def _add_link(href, link_type="text"):
        if href not in seen:
            seen.add(href)
            links.append(href)
        if link_type == "image" and href not in image_links:
            image_links.append(href)
        elif link_type == "widget":
            if href not in widget_links:
                widget_links.append(href)
            # oglink 썸네일 <img>로 인해 image로 오분류된 경우 제거
            if href in image_links:
                image_links.remove(href)

    # 1) 일반 <a> 태그 수집
    for sel in ["div.se-main-container a", "div#postViewArea a"]:
        try:
            for a in driver.find_elements(By.CSS_SELECTOR, sel):
                href = _clean_href(a.get_attribute("href") or "")
                if not href or _skip(href):
                    continue
                has_img = False
                try:
                    has_img = bool(a.find_elements(By.TAG_NAME, "img"))
                except Exception:
                    pass
                _add_link(href, link_type="image" if has_img else "text")
            if links:
                break
        except Exception:
            continue

    # 2) 링크 도구 / oglink 위젯에서 추가 수집
    for sel in [
        "a.se-oglink-info",                    # 링크 도구 (SE3)
        "a.se-module-oglink",                  # oglink 모듈
        "div.se-module-oglink a",              # oglink 내부 a
        "a[data-linkdata]",                    # data-linkdata 속성
        "div.se-section-oglink a",             # oglink 섹션
        "a.se-link",                           # 일반 링크 모듈
    ]:
        try:
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                href = _clean_href(el.get_attribute("href") or "")
                if not href or _skip(href):
                    continue
                _add_link(href, link_type="widget")
        except Exception:
            continue

    # 3) data-linkdata 속성에서 URL 추출
    try:
        for el in driver.find_elements(By.CSS_SELECTOR, "[data-linkdata]"):
            data = el.get_attribute("data-linkdata") or ""
            for url in re.findall(r"https?://[^\s\"'<>\\,}]+", data):
                href = _clean_href(url)
                if not _skip(href):
                    _add_link(href, link_type="widget")
    except Exception:
        pass

    # 4) 서식 정보 수집 (인용구/글자크기/볼드/색상)
    format_info = []
    try:
        format_info = driver.execute_script(r"""
            var paras = document.querySelectorAll('p.se-text-paragraph');
            var result = [];
            for (var i = 0; i < paras.length; i++) {
                var p = paras[i];
                var text = p.textContent.trim();
                if (!text) continue;
                var inQuote = p.closest('.se-quotation') !== null;
                var fontSize = null;
                var fm = p.className && p.className.match(/se-fs-fs(\d+)/);
                if (fm) { fontSize = parseInt(fm[1]); }
                if (!fontSize) {
                    var allEls = p.querySelectorAll('[class*="se-fs-fs"]');
                    for (var j = 0; j < allEls.length; j++) {
                        var m = allEls[j].className.match(/se-fs-fs(\d+)/);
                        if (m) { fontSize = parseInt(m[1]); break; }
                    }
                }
                var hasBold = p.querySelector('b, strong') !== null;
                var colors = [];
                var cSpans = p.querySelectorAll('span[style*="color"]');
                for (var j = 0; j < cSpans.length; j++) {
                    var style = cSpans[j].getAttribute('style') || '';
                    var cm = style.match(/color:\s*rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
                    if (cm) {
                        var r = parseInt(cm[1]), g = parseInt(cm[2]), b = parseInt(cm[3]);
                        if (!(r < 50 && g < 50 && b < 50) && !(r > 170 && g > 170 && b > 170)) {
                            colors.push([r, g, b]);
                        }
                    }
                }
                result.push({text: text, in_quote: inQuote, font_size: fontSize,
                             bold: hasBold, colors: colors});
            }
            return result;
        """) or []
    except Exception:
        format_info = []

    # 5) 이미지 컴포넌트별 링크 위치 매핑
    image_link_map = {}
    image_total = 0
    try:
        img_data = driver.execute_script("""
            var images = document.querySelectorAll(
                'div.se-component.se-image, div.se-component.se-imageStrip');
            var total = images.length;
            var result = [];
            for (var i = 0; i < images.length; i++) {
                var a = images[i].querySelector('a[href]');
                if (a && a.href) {
                    result.push({url: a.href, index: i + 1});
                }
            }
            return {links: result, total: total};
        """) or {}
        image_total = img_data.get("total", 0)
        for item in (img_data.get("links") or []):
            url = _clean_href(item["url"])
            if not _skip(url):
                image_link_map[url] = item["index"]
    except Exception:
        pass

    # 6) 모든 MKT 링크 수집 (중복 포함, 삽입 위치 분류)
    all_mkt_links = []
    try:
        raw_entries = driver.execute_script("""
            var c = document.querySelector('div.se-main-container') ||
                    document.querySelector('div#postViewArea');
            if (!c) return [];
            var aa = c.querySelectorAll('a[href]');
            var imgs = document.querySelectorAll(
                'div.se-component.se-image, div.se-component.se-imageStrip');
            var total = imgs.length;
            var out = [];
            var processedBanners = [];
            for (var i = 0; i < aa.length; i++) {
                var a = aa[i], h = a.href || '';
                if (!h) continue;
                var p, idx = null;
                if (a.closest('.se-module-oglink, .se-section-oglink') ||
                    a.classList.contains('se-oglink-info') ||
                    a.closest('[data-linkdata]')) {
                    var bannerRoot = a.closest('.se-module-oglink') ||
                                     a.closest('.se-section-oglink') ||
                                     a.closest('[data-linkdata]');
                    if (bannerRoot && processedBanners.indexOf(bannerRoot) !== -1) continue;
                    if (bannerRoot) processedBanners.push(bannerRoot);
                    p = 'banner';
                    var dlEl = a.closest('[data-linkdata]');
                    if (dlEl) {
                        var dlData = dlEl.getAttribute('data-linkdata') || '';
                        var mktUrls = dlData.match(/https?:\/\/mkt\.[^\\s"'<>,}]+/g);
                        if (mktUrls && mktUrls.length > 0) { h = mktUrls[0]; }
                    }
                } else {
                    var ic = a.closest('.se-component.se-image, .se-component.se-imageStrip');
                    if (ic) {
                        p = 'image';
                        for (var j = 0; j < imgs.length; j++) {
                            if (imgs[j] === ic) { idx = j + 1; break; }
                        }
                    } else { p = 'text'; }
                }
                out.push({url: h, placement: p, imageIndex: idx, totalImages: total});
            }
            return out;
        """) or []
        for entry in raw_entries:
            url = _clean_href(entry["url"])
            if _skip(url) or "mkt." not in url:
                continue
            all_mkt_links.append({
                "url": url,
                "placement": entry["placement"],
                "image_index": entry.get("imageIndex"),
                "image_total": entry.get("totalImages", 0),
            })
    except Exception:
        pass

    driver.switch_to.default_content()
    return {"title": title, "body": body, "links": links,
            "image_links": image_links, "widget_links": widget_links,
            "format_info": format_info,
            "image_link_map": image_link_map, "image_total": image_total,
            "all_mkt_links": all_mkt_links, "link_results": []}


# ── 링크 매칭 ────────────────────────────────────────
def _extract_link_id(url):
    if not url:
        return []
    keys = []
    m = re.search(r"mkt\.shopping\.naver\.com/link/([a-zA-Z0-9]+)", url)
    if m:
        keys.append(m.group(1))
    m = re.search(r"smartstore\.naver\.com/([^/\s?]+)", url)
    if m:
        keys.append(m.group(1))
    m = re.match(r"(https?://[^\s?#]+)", url)
    if m:
        keys.append(m.group(1))
    return keys


_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
}


def _resolve_url(url):
    """URL을 실제 접속하여 최종 리다이렉트 도착지 반환"""
    try:
        resp = requests.head(url, headers=_HEADERS, allow_redirects=True, timeout=10)
        return resp.url
    except Exception:
        try:
            resp = requests.get(url, headers=_HEADERS, allow_redirects=True, timeout=10,
                                stream=True)
            final = resp.url
            resp.close()
            return final
        except Exception:
            return url


def _check_link_accessible(url):
    """URL 접속 확인 → (accessible, final_url)"""
    try:
        resp = requests.head(url, headers=_HEADERS, allow_redirects=True, timeout=10)
        if resp.status_code < 400:
            return True, resp.url
        resp = requests.get(url, headers=_HEADERS, allow_redirects=True, timeout=10, stream=True)
        ok = resp.status_code < 400
        final = resp.url
        resp.close()
        return ok, final
    except Exception:
        return False, url


def _normalize_url(url):
    """비교용 URL 정규화 — 스킴, 파라미터 순서 무시"""
    p = urlparse(url)
    # path 끝 슬래시 제거, 소문자
    path = p.path.rstrip("/").lower()
    return f"{p.netloc.lower()}{path}"


def _is_shop_candidate(url, ids):
    return (
        any(kid in url for kid in ids)
        or "mkt.shopping" in url
        or "smartstore" in url
        or "shopping.naver" in url
        or "brand.naver" in url
    )


def _link_found_in_blog(target_url, blog_links, image_links, widget_links):
    """반환: 'image' | 'widget' | 'text' | 'missing'"""
    if not target_url:
        return "image"  # 링크 없으면 체크 불필요

    target_final = _resolve_url(target_url)
    target_norm = _normalize_url(target_final)
    ids = _extract_link_id(target_url)

    def _match(link_list):
        for lk in link_list:
            if not _is_shop_candidate(lk, ids):
                continue
            if _normalize_url(_resolve_url(lk)) == target_norm:
                return True
        return False

    in_image = _match(image_links)
    in_widget = _match(widget_links)
    in_any = _match(blog_links)

    if in_widget:
        return "widget"
    if in_image:
        return "image"
    if in_any:
        return "text"
    return "missing"


# ── 콘텐츠 매칭용 텍스트 정규화 ─────────────────────
def _normalize_text(s):
    """따옴표, 화살표, 특수문자 통일 후 공백 정규화"""
    s = s.replace("\u201c", '"').replace("\u201d", '"')   # " " → "
    s = s.replace("\u2018", "'").replace("\u2019", "'")   # ' ' → '
    s = s.replace("\u300c", '"').replace("\u300d", '"')   # 「 」 → "
    s = s.replace("->", "").replace("→", "")             # 화살표 제거
    s = s.replace("\u00a0", " ")                          # non-breaking space
    s = re.sub(r"\s+", " ", s).strip()
    return s.lower()


# ── 서식 파싱 ────────────────────────────────────────
def _parse_format_info(text):
    """ㄴ 지시사항 또는 서식 라인에서 서식 정보 추출"""
    info = {}
    if re.search(r"인용구\s*종료", text):
        info["quote_end"] = True
        return info
    m = re.search(r"인용구\s*(\d+)\s*번?", text)
    if m:
        info["quote"] = int(m.group(1))
    m = re.search(r"글자\s*크기\s*(\d+)", text)
    if m:
        info["font_size"] = int(m.group(1))
    if re.search(r"글꼴\s*두껍게", text):
        info["bold"] = True
    COLOR_KR = {"빨간색": "red", "빨간": "red", "빨강": "red",
                "파란색": "blue", "파란": "blue", "파랑": "blue",
                "초록색": "green", "녹색": "green",
                "주황색": "orange", "주황": "orange",
                "보라색": "purple", "보라": "purple"}
    for kr, en in COLOR_KR.items():
        if kr in text:
            info["color"] = en
            break
    return info


def _color_matches(expected, rgb_list):
    """expected: 'red'/'blue'/... , rgb_list: [[r,g,b], ...]"""
    for r, g, b in rgb_list:
        if expected == "red" and r > 150 and g < 100 and b < 100:
            return True
        if expected == "blue" and r < 100 and g < 100 and b > 150:
            return True
        if expected == "green" and r < 100 and g > 150 and b < 100:
            return True
        if expected == "orange" and r > 200 and g > 100 and b < 50:
            return True
        if expected == "purple" and r > 100 and g < 100 and b > 150:
            return True
    return False


# ── 검수 ─────────────────────────────────────────────
def check_publication(item, docx_info, blog_info):
    issues = []
    blog_body = blog_info["body"]
    blog_title = blog_info["title"]
    blog_links = blog_info["links"]

    # 1) 제목
    if item["title"] and blog_title:
        norm = lambda s: re.sub(r"\s+", " ", s).strip()
        if norm(item["title"]) != norm(blog_title):
            issues.append(
                f"제목 불일치 — 시트: \"{item['title']}\" / 블로그: \"{blog_title}\""
            )

    # 2) 요청 문구
    req_seen = set()
    req_exposed = []  # 노출된 요청 문구 텍스트 목록 (서식 키워드 중복 방지용)
    for instr in docx_info["instructions"]:
        clean = instr.lstrip("ㄴ").strip()
        # 스킵: 짧은 텍스트, URL, 해시태그 나열
        if len(clean) < 5 or clean.startswith("http") or clean.startswith("#"):
            continue
        if clean in req_seen:
            continue
        req_seen.add(clean)
        if clean in blog_body:
            issues.append(f"요청 문구 노출: \"{clean}\"")
            req_exposed.append(clean)

    # 3) 서식 키워드
    seen = set()
    for kw in BLOG_CHECK_KEYWORDS:
        if kw in blog_body and kw not in seen:
            seen.add(kw)
            idx = blog_body.index(kw)
            s, e = max(0, idx - 15), min(len(blog_body), idx + len(kw) + 15)
            ctx = blog_body[s:e].replace("\n", " ")
            # 이미 요청 문구로 잡힌 내용과 겹치면 스킵
            if any(req in ctx for req in req_exposed):
                continue
            issues.append(f"서식 키워드 노출: \"{ctx}\"")

    # 4) 이미지 번호
    blog_lines = [l.strip() for l in blog_body.split("\n") if l.strip()]
    for num in docx_info["image_numbers"]:
        if num in blog_lines:
            issues.append(f"이미지 번호 노출: \"{num}\"")
    for line in blog_lines:
        if re.match(r"^0\d$", line) and line not in docx_info["image_numbers"]:
            issues.append(f"이미지 번호 노출 (추정): \"{line}\"")

    # 5) 링크 검수 (상품 + 광고 — 각 MKT 링크별 접속/일치/위치 확인)
    all_mkt = blog_info.get("all_mkt_links", [])
    prod_link = item.get("product_link", "").strip()
    ad_link_val = item.get("ad_link", "").strip()

    # MKT 링크 정규화 (쿼리 파라미터 포함, percent-decode 후 정렬)
    def _mkt_id(url):
        m = re.search(r"mkt\.shopping\.naver\.com/link/([a-zA-Z0-9]+)", url)
        return m.group(1).lower() if m else None

    def _mkt_full(url):
        """MKT 전체 URL 정규화 (쿼리 포함)"""
        u = unquote(url).strip()
        p = urlparse(u)
        path = p.path.rstrip("/").lower()
        params = sorted(parse_qsl(p.query))
        qs = urlencode(params)
        return f"{p.netloc.lower()}{path}?{qs}" if qs else f"{p.netloc.lower()}{path}"

    prod_mkt_id = _mkt_id(prod_link) if prod_link else None
    ad_mkt_id = _mkt_id(ad_link_val) if ad_link_val else None
    prod_full = _mkt_full(prod_link) if prod_link else ""
    ad_full = _mkt_full(ad_link_val) if ad_link_val else ""

    # non-mkt 기대 링크는 resolve해서 비교
    resolve_cache = {}
    def _cached_check(url):
        if url not in resolve_cache:
            resolve_cache[url] = _check_link_accessible(url)
        return resolve_cache[url]

    prod_norm = ""
    if prod_link and not prod_mkt_id:
        _, prod_final = _cached_check(prod_link)
        prod_norm = _normalize_url(prod_final)
    ad_norm = ""
    if ad_link_val and not ad_mkt_id:
        _, ad_final = _cached_check(ad_link_val)
        ad_norm = _normalize_url(ad_final)

    prod_found = False
    ad_found = False
    link_results = []

    for mkt in all_mkt:
        url = mkt["url"]
        accessible, final_url = _cached_check(url)
        mkt_id = _mkt_id(url)
        mkt_full = _mkt_full(url)
        final_norm = _normalize_url(final_url)

        match_types = []
        # 1차: 전체 URL 비교 (쿼리 파라미터 포함 — 상품/광고 정확히 구분)
        if prod_full and mkt_full == prod_full:
            match_types.append("상품")
            prod_found = True
        if ad_full and mkt_full == ad_full:
            match_types.append("광고")
            ad_found = True
        # 2차: MKT ID만 비교 (블로거가 파라미터를 변경한 경우 fallback)
        if not match_types:
            if mkt_id and prod_mkt_id and mkt_id == prod_mkt_id:
                match_types.append("상품")
                prod_found = True
            if mkt_id and ad_mkt_id and mkt_id == ad_mkt_id:
                match_types.append("광고")
                ad_found = True
        # 3차: 최종 URL 비교 (non-mkt 기대 링크용)
        if not match_types and prod_norm and final_norm == prod_norm:
            match_types.append("상품")
            prod_found = True
        if not match_types and ad_norm and final_norm == ad_norm:
            match_types.append("광고")
            ad_found = True
        match_type = "/".join(match_types) if match_types else None

        link_results.append({
            "url": url,
            "accessible": accessible,
            "final_url": final_url,
            "match_type": match_type,
            "placement": mkt["placement"],
            "image_index": mkt.get("image_index"),
            "image_total": mkt.get("image_total", 0),
        })

    if prod_link and not prod_found:
        issues.append(f"상품 링크 미삽입: {prod_link}")
    if ad_link_val and not ad_found:
        issues.append(f"광고 링크 미삽입: {ad_link_val}")
    for lr in link_results:
        if not lr["accessible"]:
            issues.append(f"링크 접속 불가: {lr['url']}")

    blog_info["link_results"] = link_results

    # 7) 서식 검수 (인용구/글자크기/볼드/색상)
    format_reqs = docx_info.get("format_reqs", [])
    blog_fmt = blog_info.get("format_info", [])
    if format_reqs and blog_fmt:
        blog_idx = 0
        for req in format_reqs:
            has_fmt = req.get("quote") or req.get("font_size") or req.get("bold") or req.get("color")
            req_norm = _normalize_text(req["text"])
            if len(req_norm) < 5:
                continue

            # blog_idx부터 텍스트 매칭 → blog_idx 전진 (서식 무관하게)
            for i in range(blog_idx, len(blog_fmt)):
                bp_norm = _normalize_text(blog_fmt[i]["text"])
                if req_norm[:20] in bp_norm or bp_norm[:20] in req_norm:
                    blog_idx = i + 1
                    break

            if not has_fmt:
                continue

            # 서식 요구가 있는 줄: 서식 점수가 가장 높은 매칭 선택
            candidates = []
            for bp in blog_fmt:
                bp_norm = _normalize_text(bp["text"])
                if not (req_norm[:20] in bp_norm or bp_norm[:20] in req_norm):
                    continue
                score = 0
                if req.get("quote") and bp.get("in_quote"):
                    score += 1
                if req.get("font_size") and bp.get("font_size") == req["font_size"]:
                    score += 1
                if req.get("bold") and bp.get("bold"):
                    score += 1
                if req.get("color") and _color_matches(req["color"], bp.get("colors", [])):
                    score += 1
                candidates.append((score, bp))

            if not candidates:
                continue
            candidates.sort(key=lambda x: x[0], reverse=True)
            matched = candidates[0][1]
            if not matched:
                continue
            short = req["text"][:25] + ("..." if len(req["text"]) > 25 else "")
            if req.get("quote") and not matched.get("in_quote"):
                issues.append(f"인용구 미적용: \"{short}\"")
            if req.get("font_size") and matched.get("font_size") != req["font_size"]:
                actual = matched.get("font_size") or "기본"
                issues.append(f"글자크기 불일치: \"{short}\" (요청: {req['font_size']}, 실제: {actual})")
            if req.get("bold") and not matched.get("bold"):
                issues.append(f"글꼴두껍게 미적용: \"{short}\"")
            if req.get("color"):
                colors = matched.get("colors", [])
                if not _color_matches(req["color"], colors):
                    issues.append(f"색상 미적용: \"{short}\" (요청: {req['color']})")

    return issues


def generate_message(selected_results):
    """선택된 항목만으로 발행처별 메시지 생성"""
    if not selected_results:
        return ""

    by_pub = OrderedDict()
    for it, iss in selected_results:
        pub = it.get("publisher", "") or "(발행처 없음)"
        by_pub.setdefault(pub, []).append((it, iss))

    sections = []
    for pub, items in by_pub.items():
        cnt = len(items)
        lines = [
            f"[{pub}]",
            f"안녕하세요, 아래 {cnt}건 내용 수정 요청 부탁드립니다.",
            "",
        ]
        for it, iss in items:
            lines.append(it["link"])
            for i in iss:
                lines.append(f"ㄴ {i}")
            lines.append("")
        lines.append("감사합니다 : )")
        sections.append("\n".join(lines).strip())

    return ("\n\n" + "=" * 40 + "\n\n").join(sections)


# ═══════════════════════════════════════════════════════
#  GUI
# ═══════════════════════════════════════════════════════
CHK_ON = "\u2611"   # ☑
CHK_OFF = "\u2610"  # ☐


class App:
    C_OK = "#2e7d32"
    C_WARN = "#e65100"
    C_ERR = "#c62828"
    C_INFO = "#1565c0"
    C_BG = "#fafafa"

    def __init__(self, root):
        self.root = root
        self.root.title("발행 원고 검수 프로그램 v1.1")
        self.root.geometry("1100x850")
        self.root.minsize(950, 700)
        self.root.configure(bg=self.C_BG)

        self.results = []          # [(item, issues), ...]
        self.checked = {}          # tree_id → bool
        self.tree_data = {}        # tree_id → (item, issues)
        self.running = False
        self.stop_event = threading.Event()

        self._build_ui()

    # ────────────────────────────────────────────
    #  UI
    # ────────────────────────────────────────────
    def _build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Title.TLabel", font=("맑은 고딕", 14, "bold"), background=self.C_BG)
        style.configure("Status.TLabel", font=("맑은 고딕", 9), foreground=self.C_INFO)
        style.configure("Big.TButton", font=("맑은 고딕", 10, "bold"), padding=(16, 7))
        style.configure("Stop.TButton", font=("맑은 고딕", 10), padding=(12, 7))
        style.configure("Act.TButton", font=("맑은 고딕", 10), padding=(12, 6))

        # ── 헤더 ──
        hdr = ttk.Frame(self.root)
        hdr.pack(fill=tk.X, padx=15, pady=(12, 4))
        ttk.Label(hdr, text="발행 원고 검수", style="Title.TLabel").pack(side=tk.LEFT)

        # ── 컨트롤 바 ──
        ctrl = ttk.Frame(self.root)
        ctrl.pack(fill=tk.X, padx=15, pady=4)

        ttk.Label(ctrl, text="검수 날짜:", font=("맑은 고딕", 10)).pack(side=tk.LEFT, padx=(0, 4))
        today = datetime.date.today()

        self.var_year = tk.StringVar(value=str(today.year))
        ttk.Spinbox(ctrl, from_=2024, to=2030, width=5,
                     textvariable=self.var_year, font=("맑은 고딕", 10)).pack(side=tk.LEFT)
        ttk.Label(ctrl, text="년", font=("맑은 고딕", 10)).pack(side=tk.LEFT, padx=(1, 4))

        self.var_month = tk.StringVar(value=str(today.month))
        ttk.Spinbox(ctrl, from_=1, to=12, width=3,
                     textvariable=self.var_month, font=("맑은 고딕", 10)).pack(side=tk.LEFT)
        ttk.Label(ctrl, text="월", font=("맑은 고딕", 10)).pack(side=tk.LEFT, padx=(1, 4))

        self.var_day = tk.StringVar(value=str(today.day))
        ttk.Spinbox(ctrl, from_=1, to=31, width=3,
                     textvariable=self.var_day, font=("맑은 고딕", 10)).pack(side=tk.LEFT)
        ttk.Label(ctrl, text="일", font=("맑은 고딕", 10)).pack(side=tk.LEFT, padx=(1, 12))

        self.btn_start = ttk.Button(ctrl, text="검수 시작", style="Big.TButton",
                                    command=self._on_start)
        self.btn_start.pack(side=tk.LEFT, padx=(0, 5))

        self.btn_stop = ttk.Button(ctrl, text="중단", style="Stop.TButton",
                                   command=self._on_stop, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=(0, 15))

        self.btn_gen = ttk.Button(ctrl, text="메시지 생성", style="Act.TButton",
                                  command=self._on_generate, state=tk.DISABLED)
        self.btn_gen.pack(side=tk.LEFT, padx=(0, 5))

        self.btn_copy = ttk.Button(ctrl, text="메시지 복사", style="Act.TButton",
                                   command=self._on_copy, state=tk.DISABLED)
        self.btn_copy.pack(side=tk.LEFT)

        self.btn_blog = ttk.Button(ctrl, text="블로그 열기", style="Act.TButton",
                                   command=self._on_open_blog)
        self.btn_blog.pack(side=tk.LEFT, padx=(5, 0))

        self.lbl_status = ttk.Label(ctrl, text="", style="Status.TLabel")
        self.lbl_status.pack(side=tk.RIGHT, padx=5)

        # ── 진행률 ──
        pf = ttk.Frame(self.root)
        pf.pack(fill=tk.X, padx=15, pady=(0, 4))
        self.progress = ttk.Progressbar(pf, mode="determinate")
        self.progress.pack(fill=tk.X)
        self.lbl_progress = ttk.Label(pf, text="", font=("맑은 고딕", 9), foreground="gray")
        self.lbl_progress.pack(anchor=tk.W, pady=(2, 0))

        # ── 메인 영역: 좌(트리+상세) / 우(메시지) ──
        paned_h = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned_h.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 10))

        # 좌측: 트리 + 상세
        left_paned = ttk.PanedWindow(paned_h, orient=tk.VERTICAL)
        paned_h.add(left_paned, weight=3)

        # -- 트리뷰 --
        tree_frame = ttk.LabelFrame(left_paned, text="검수 결과 (체크하여 메시지에 포함)", padding=4)
        left_paned.add(tree_frame, weight=3)

        cols = ("chk", "status", "param", "publisher", "title")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings",
                                 selectmode="browse", height=14)
        self.tree.heading("chk", text="")
        self.tree.heading("status", text="상태")
        self.tree.heading("param", text="파라미터")
        self.tree.heading("publisher", text="발행처")
        self.tree.heading("title", text="제목")
        self.tree.column("chk", width=30, anchor=tk.CENTER, stretch=False)
        self.tree.column("status", width=80, anchor=tk.CENTER)
        self.tree.column("param", width=150)
        self.tree.column("publisher", width=80)
        self.tree.column("title", width=250)

        self.tree.tag_configure("ok", foreground=self.C_OK)
        self.tree.tag_configure("err", foreground=self.C_ERR)

        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<ButtonRelease-1>", self._on_tree_click)
        self.tree.bind("<Double-1>", self._on_tree_dblclick)
        self.tree.bind("<KeyRelease-Up>", self._on_tree_key)
        self.tree.bind("<KeyRelease-Down>", self._on_tree_key)
        self.tree.bind("<Return>", self._on_tree_enter)

        # -- 상세 보기 --
        detail_frame = ttk.LabelFrame(left_paned, text="상세 정보", padding=4)
        left_paned.add(detail_frame, weight=2)

        self.txt_detail = scrolledtext.ScrolledText(
            detail_frame, wrap=tk.WORD, font=("맑은 고딕", 10)
        )
        self.txt_detail.pack(fill=tk.BOTH, expand=True)

        # -- 블로그 링크 목록 --
        link_frame = ttk.LabelFrame(left_paned, text="블로그 내 링크 목록", padding=4)
        left_paned.add(link_frame, weight=1)

        self.lst_links = tk.Listbox(link_frame, font=("맑은 고딕", 9),
                                    selectmode=tk.BROWSE, activestyle="none",
                                    foreground="#1565c0", cursor="hand2")
        link_vsb = ttk.Scrollbar(link_frame, orient=tk.VERTICAL, command=self.lst_links.yview)
        self.lst_links.configure(yscrollcommand=link_vsb.set)
        self.lst_links.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        link_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.lst_links.bind("<Double-1>", self._on_link_dblclick)
        self._blog_links = []

        # 우측: 메시지
        right_frame = ttk.LabelFrame(paned_h, text="수정 요청 메시지", padding=4)
        paned_h.add(right_frame, weight=2)

        self.txt_msg = scrolledtext.ScrolledText(
            right_frame, wrap=tk.WORD, font=("맑은 고딕", 10), state=tk.DISABLED
        )
        self.txt_msg.pack(fill=tk.BOTH, expand=True)

        # ── 하단 요약 ──
        sf = ttk.Frame(self.root)
        sf.pack(fill=tk.X, padx=15, pady=(0, 8))
        self.lbl_summary = ttk.Label(sf, text="", font=("맑은 고딕", 10, "bold"))
        self.lbl_summary.pack(side=tk.LEFT)

    # ────────────────────────────────────────────
    #  유틸
    # ────────────────────────────────────────────
    def _get_target_date(self):
        try:
            return datetime.date(int(self.var_year.get()),
                                 int(self.var_month.get()),
                                 int(self.var_day.get()))
        except ValueError:
            return None

    def _set_status(self, text, color=None):
        self.lbl_status.config(text=text)
        if color:
            self.lbl_status.config(foreground=color)

    def _set_progress(self, value, text=""):
        self.progress["value"] = value
        self.lbl_progress.config(text=text)

    def _set_text(self, widget, text):
        widget.config(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        if text:
            widget.insert(tk.END, text)
        widget.config(state=tk.DISABLED)

    # ────────────────────────────────────────────
    #  트리 체크박스 & 클릭
    # ────────────────────────────────────────────
    def _on_tree_click(self, event):
        iid = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)

        if not iid or iid not in self.tree_data:
            return

        # 체크박스 토글 (첫 번째 컬럼 클릭)
        if col == "#1":
            self._save_detail_edits()  # 이전 수정 사항 저장
            self.checked[iid] = not self.checked.get(iid, False)
            vals = list(self.tree.item(iid, "values"))
            vals[0] = CHK_ON if self.checked[iid] else CHK_OFF
            self.tree.item(iid, values=vals)
            return

        # 그 외 컬럼 클릭 → 이전 수정 저장 후 상세 보기
        self._save_detail_edits()
        self.current_detail_iid = iid
        self._show_detail(iid)

    def _save_detail_edits(self):
        """상세 정보에서 수정한 내용을 tree_data에 반영"""
        iid = getattr(self, "current_detail_iid", None)
        if not iid or iid not in self.tree_data:
            return

        text = self.txt_detail.get("1.0", tk.END).strip()
        if not text:
            return

        # "검수 결과:" 이후의 번호 라인을 이슈로 파싱
        item, old_issues, docx_info, blog_info = self.tree_data[iid]
        new_issues = []
        in_issues = False
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("검수 결과:"):
                in_issues = True
                continue
            if line.startswith("-" * 5):
                continue
            if in_issues and line:
                # "1. 이슈내용" → "이슈내용"
                cleaned = re.sub(r"^\d+\.\s*", "", line)
                if cleaned:
                    new_issues.append(cleaned)

        self.tree_data[iid] = (item, new_issues, docx_info, blog_info)

        # 트리뷰 상태 업데이트
        if not new_issues:
            tag = "ok"
            status = "통과"
        else:
            tag = "err"
            status = f"문제 {len(new_issues)}건"
        vals = list(self.tree.item(iid, "values"))
        vals[1] = status
        self.tree.item(iid, values=vals, tags=(tag,))

    def _show_detail(self, iid):
        if iid not in self.tree_data:
            return
        item, issues, docx_info, blog_info = self.tree_data[iid]

        lines = []
        lines.append(f"제목:     {item.get('title', '')}")
        lines.append(f"파라미터: {item.get('param', '')}")
        lines.append(f"발행처:   {item.get('publisher', '')}")
        lines.append(f"링크:     {item.get('link', '')}")
        lines.append(f"파일명:   {item.get('filename', '')}")
        lines.append("")

        if not issues:
            lines.append("검수 결과: 문제 없음")
        else:
            lines.append(f"검수 결과: 문제 {len(issues)}건")
            lines.append("-" * 40)
            for i, iss in enumerate(issues, 1):
                lines.append(f"{i}. {iss}")

        self.txt_detail.delete("1.0", tk.END)
        self.txt_detail.insert(tk.END, "\n".join(lines))

        # 블로그 링크 목록 갱신 (링크 검수 결과 — 중복 포함)
        self.lst_links.delete(0, tk.END)
        link_results = blog_info.get("link_results", [])

        self._blog_links = []
        if link_results:
            for lr in link_results:
                # 삽입 위치
                if lr["placement"] == "image":
                    idx = lr.get("image_index")
                    total = lr.get("image_total", 0)
                    if idx:
                        pos = f"[이미지 {idx}/{total}번째]" if total else f"[이미지 {idx}번째]"
                    else:
                        pos = "[이미지]"
                elif lr["placement"] == "banner":
                    pos = "[배너]"
                else:
                    pos = "[텍스트]"
                # 접속 여부
                acc = "[접속OK]" if lr["accessible"] else "[접속불가]"
                # 원고 링크 매칭
                if lr["match_type"]:
                    match = f"[{lr['match_type']}링크]"
                else:
                    match = "[불일치]"
                self.lst_links.insert(tk.END, f"{pos} {acc} {match} {lr['url']}")
                self._blog_links.append(lr["url"])
        else:
            self.lst_links.insert(tk.END, "(MKT 링크 없음)")

        # 원고 기대 링크 표시
        prod = item.get("product_link", "")
        ad = item.get("ad_link", "")
        if prod or ad:
            self.lst_links.insert(tk.END, "")
            self.lst_links.insert(tk.END, "── 원고 링크 (시트) ──")
            if prod:
                self.lst_links.insert(tk.END, f"  상품: {prod}")
            if ad:
                self.lst_links.insert(tk.END, f"  광고: {ad}")

        # DOCX 링크 지시 표시
        link_reqs = docx_info.get("link_reqs", [])
        if link_reqs:
            self.lst_links.insert(tk.END, "")
            self.lst_links.insert(tk.END, "── DOCX 링크 지시 ──")
            for req in link_reqs:
                self.lst_links.insert(tk.END, f"  {req['label']}: ㄴ{req['instruction']}")

    def _on_tree_key(self, event):
        """위/아래 화살표 → 상세 정보 갱신"""
        sel = self.tree.selection()
        if not sel or sel[0] not in self.tree_data:
            return
        iid = sel[0]
        self._save_detail_edits()
        self.current_detail_iid = iid
        self._show_detail(iid)

    def _on_tree_enter(self, event):
        """엔터 → 블로그 열기"""
        sel = self.tree.selection()
        if not sel or sel[0] not in self.tree_data:
            return
        item = self.tree_data[sel[0]][0]
        link = item.get("link", "")
        if link:
            webbrowser.open(link)

    def _on_open_blog(self):
        sel = self.tree.selection()
        if not sel or sel[0] not in self.tree_data:
            return
        item = self.tree_data[sel[0]][0]
        link = item.get("link", "")
        if link:
            webbrowser.open(link)

    def _on_link_dblclick(self, event):
        sel = self.lst_links.curselection()
        if not sel or not self._blog_links:
            return
        idx = sel[0]
        if idx < len(self._blog_links):
            webbrowser.open(self._blog_links[idx])

    # ────────────────────────────────────────────
    #  원고 비교 팝업
    # ────────────────────────────────────────────
    def _on_tree_dblclick(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid or iid not in self.tree_data:
            return
        item, issues, docx_info, blog_info = self.tree_data[iid]
        self._open_compare(item, docx_info, blog_info)

    def _open_compare(self, item, docx_info, blog_info):
        win = tk.Toplevel(self.root)
        title_text = item.get("title", "") or item.get("param", "")
        win.title(f"원고 원문 — {title_text}")
        win.geometry("700x700")
        win.minsize(500, 400)

        # 상단 정보 + 블로그 열기 버튼
        info_frame = ttk.Frame(win)
        info_frame.pack(fill=tk.X, padx=10, pady=(8, 4))
        ttk.Label(info_frame, text=f"파라미터: {item.get('param', '')}",
                  font=("맑은 고딕", 10)).pack(side=tk.LEFT, padx=(0, 20))
        ttk.Label(info_frame, text=f"발행처: {item.get('publisher', '')}",
                  font=("맑은 고딕", 10)).pack(side=tk.LEFT)

        blog_link = item.get("link", "")
        if blog_link:
            ttk.Button(info_frame, text="블로그 열기",
                       command=lambda: webbrowser.open(blog_link),
                       style="Act.TButton").pack(side=tk.RIGHT, padx=5)

        # 원고 원문
        docx_frame = ttk.LabelFrame(win, text="원고 원문 (DOCX)", padding=4)
        docx_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        txt_docx = scrolledtext.ScrolledText(docx_frame, wrap=tk.WORD, font=("맑은 고딕", 10))
        txt_docx.pack(fill=tk.BOTH, expand=True)

        full_text = docx_info.get("full_text", "")
        if full_text:
            txt_docx.insert(tk.END, full_text)
        else:
            reason = "(원고 없음"
            if not item.get("filename"):
                reason += " — 파일명 없음"
            reason += ")"
            txt_docx.insert(tk.END, reason)
        txt_docx.config(state=tk.DISABLED)

    # ────────────────────────────────────────────
    #  버튼 이벤트
    # ────────────────────────────────────────────
    def _on_start(self):
        if self.running:
            return
        target = self._get_target_date()
        if not target:
            messagebox.showwarning("알림", "올바른 날짜를 입력하세요.")
            return

        # 사전 체크: credentials.json
        if not os.path.exists(CRED_FILE):
            messagebox.showerror(
                "오류",
                "credentials.json 파일을 찾을 수 없습니다.\n"
                "EXE 파일과 같은 폴더에 credentials.json을 넣어주세요."
            )
            return

        # 사전 체크: Chrome 브라우저 설치 여부
        import winreg
        chrome_found = False
        for reg_path in [
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
        ]:
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path):
                    chrome_found = True
                    break
            except OSError:
                pass
        if not chrome_found:
            # 일반 경로도 확인
            chrome_paths = [
                os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
            ]
            chrome_found = any(os.path.exists(p) for p in chrome_paths)
        if not chrome_found:
            messagebox.showerror(
                "오류",
                "Chrome 브라우저가 설치되어 있지 않습니다.\n"
                "이 프로그램은 Chrome이 필요합니다.\n"
                "https://www.google.com/chrome 에서 설치 후 다시 시도하세요."
            )
            return

        self.running = True
        self.stop_event.clear()
        self.btn_start.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)
        self.btn_gen.config(state=tk.DISABLED)
        self.btn_copy.config(state=tk.DISABLED)
        self.tree.delete(*self.tree.get_children())
        self.checked.clear()
        self.tree_data.clear()
        self._set_text(self.txt_msg, "")
        self.txt_detail.delete("1.0", tk.END)
        self.lbl_summary.config(text="")
        self.results = []
        self._set_progress(0, "시작 중...")
        self._set_status("검수 진행 중...", self.C_INFO)

        threading.Thread(target=self._run_check, args=(target,), daemon=True).start()

    def _on_stop(self):
        self.stop_event.set()
        self._set_status("중단 요청됨...", self.C_WARN)

    def _on_generate(self):
        """체크된 항목만으로 메시지 생성 (상세 수정 반영)"""
        self._save_detail_edits()  # 현재 수정 중인 내용 저장
        selected = []
        for iid, data in self.tree_data.items():
            if self.checked.get(iid, False):
                selected.append((data[0], data[1]))

        if not selected:
            messagebox.showinfo("알림", "메시지에 포함할 항목을 체크하세요.")
            return

        msg = generate_message(selected)
        self._set_text(self.txt_msg, msg)
        self.btn_copy.config(state=tk.NORMAL)
        self._set_status(f"메시지 생성 완료 ({len(selected)}건)", self.C_OK)

    def _on_copy(self):
        msg = self.txt_msg.get("1.0", tk.END).strip()
        if msg:
            try:
                pyperclip.copy(msg)
                self._set_status("클립보드에 복사되었습니다.", self.C_OK)
            except Exception:
                self._set_status("복사 실패", self.C_ERR)

    # ────────────────────────────────────────────
    #  검수 워커
    # ────────────────────────────────────────────
    def _run_check(self, target_date):
        try:
            self._do_check(target_date)
        except Exception as e:
            import traceback
            err_detail = traceback.format_exc()
            err_msg = str(e) if str(e) else type(e).__name__
            self.root.after(0, lambda: messagebox.showerror("오류", err_msg))
            self.root.after(0, lambda: self._set_status(f"오류: {err_msg}", self.C_ERR))
            self.root.after(0, lambda: self._set_progress(0, f"오류 발생: {err_msg}"))
            # 상세 패널에 트레이스백 표시 (디버깅용)
            self.root.after(0, lambda: self.txt_detail.delete("1.0", tk.END))
            self.root.after(0, lambda: self.txt_detail.insert("1.0", f"[오류 상세]\n{err_detail}"))
        finally:
            self.root.after(0, self._finish_check)

    def _finish_check(self):
        self.running = False
        self.btn_start.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)
        if self.results:
            self.btn_gen.config(state=tk.NORMAL)

    def _do_check(self, target_date):
        date_str = target_date.strftime("%Y-%m-%d")

        # 1) 시트 조회
        self.root.after(0, lambda: self._set_progress(5, f"[1/4] {date_str} 발행 건 조회 중..."))
        creds = get_creds()
        items = fetch_items(creds, target_date)

        if not items:
            self.root.after(0, lambda: self._set_progress(100, "완료"))
            self.root.after(0, lambda: self._set_status(
                f"{date_str} 발행 건이 없습니다.", self.C_WARN))
            self.root.after(0, lambda: self.lbl_summary.config(
                text=f"{date_str} — 발행 건 0건", foreground=self.C_WARN))
            return

        total = len(items)
        self.root.after(0, lambda: self._set_progress(10, f"[1/4] {total}건 발견"))

        if self.stop_event.is_set():
            self.root.after(0, lambda: self._set_status("중단됨", self.C_WARN))
            return

        # 2) 원본 다운로드
        docx_map = {}
        tmp_dirs = []
        for idx, it in enumerate(items):
            if self.stop_event.is_set():
                self.root.after(0, lambda: self._set_status("중단됨", self.C_WARN))
                self._cleanup_tmp(tmp_dirs)
                return
            fn = it["filename"]
            pct = 10 + int(30 * (idx + 1) / total)
            label = f"[2/4] 원본 다운로드 {idx+1}/{total}"
            self.root.after(0, lambda p=pct, l=label: self._set_progress(p, l))

            if not fn:
                docx_map[it["param"]] = EMPTY_DOCX
                continue
            try:
                path, tmp_dir = find_and_download(creds, fn)
                if tmp_dir:
                    tmp_dirs.append(tmp_dir)
                if path:
                    result = parse_docx(path)
                    docx_map[it["param"]] = result
                else:
                    docx_map[it["param"]] = EMPTY_DOCX
            except Exception as e:
                print(f"[DOCX 오류] {fn}: {e}")
                docx_map[it["param"]] = EMPTY_DOCX

        if self.stop_event.is_set():
            self.root.after(0, lambda: self._set_status("중단됨", self.C_WARN))
            return

        # 3) 블로그 크롤링 (병렬)
        WORKERS = min(4, total)
        self.root.after(0, lambda: self._set_progress(40,
            f"[3/4] 브라우저 {WORKERS}개 초기화..."))

        # 링크 목록 준비
        link_items = [(idx, it) for idx, it in enumerate(items) if it["link"]]
        blog_map = {it["link"]: EMPTY_BLOG for it in items if not it["link"]}
        crawl_done = [0]  # mutable counter for threads
        lock = threading.Lock()

        def crawl_worker(driver, work_list):
            try:
                for idx, it in work_list:
                    if self.stop_event.is_set():
                        break
                    try:
                        blog_map[it["link"]] = scrape_blog(driver, it["link"])
                    except Exception:
                        blog_map[it["link"]] = EMPTY_BLOG
                    with lock:
                        crawl_done[0] += 1
                        done = crawl_done[0]
                    pct = 40 + int(40 * done / total)
                    label = f"[3/4] 블로그 크롤링 {done}/{total}"
                    self.root.after(0, lambda p=pct, l=label: self._set_progress(p, l))
            finally:
                driver.quit()

        # 작업 분배
        chunks = [[] for _ in range(WORKERS)]
        for i, item_pair in enumerate(link_items):
            chunks[i % WORKERS].append(item_pair)

        # 드라이버 생성 & 스레드 시작
        threads = []
        for chunk in chunks:
            if not chunk:
                continue
            drv = setup_driver()
            t = threading.Thread(target=crawl_worker, args=(drv, chunk), daemon=True)
            t.start()
            threads.append(t)

        for t in threads:
            t.join()

        if self.stop_event.is_set():
            self.root.after(0, lambda: self._set_status("중단됨 (부분 결과 표시)", self.C_WARN))

        # 4) 검수
        self.root.after(0, lambda: self._set_progress(85, "[4/4] 검수 중..."))
        results = []
        for it in items:
            di = docx_map.get(it["param"], EMPTY_DOCX)
            bi = blog_map.get(it["link"], EMPTY_BLOG)
            issues = check_publication(it, di, bi)
            results.append((it, issues, di, bi))

        self.results = results
        self._cleanup_tmp(tmp_dirs)

        def update_ui():
            self._populate_tree(results)
            self._set_progress(100, "완료")

            ok_cnt = sum(1 for _, iss, *_ in results if not iss)
            err_cnt = sum(1 for _, iss, *_ in results if iss)
            total_issues = sum(len(iss) for _, iss, *_ in results)

            summary = f"{date_str}  |  총 {len(results)}건  |  "
            if err_cnt == 0:
                summary += "전체 통과"
                color = self.C_OK
            else:
                summary += f"통과 {ok_cnt}건 / 문제 {err_cnt}건 (이슈 {total_issues}개)"
                color = self.C_ERR
            self.lbl_summary.config(text=summary, foreground=color)

            if self.stop_event.is_set():
                self._set_status("중단됨 (부분 결과)", self.C_WARN)
            elif err_cnt > 0:
                self._set_status("검수 완료 — 문제 발견", self.C_ERR)
            else:
                self._set_status("검수 완료 — 이상 없음", self.C_OK)

        self.root.after(0, update_ui)

    # ────────────────────────────────────────────
    #  임시 파일 정리
    # ────────────────────────────────────────────
    def _cleanup_tmp(self, tmp_dirs):
        for d in tmp_dirs:
            try:
                shutil.rmtree(d, ignore_errors=True)
            except Exception:
                pass

    # ────────────────────────────────────────────
    #  트리 채우기
    # ────────────────────────────────────────────
    def _populate_tree(self, results):
        self.tree.delete(*self.tree.get_children())
        self.checked.clear()
        self.tree_data.clear()

        for item, issues, docx_info, blog_info in results:
            title = item["title"] or "(제목 없음)"
            param = item.get("param", "")
            publisher = item.get("publisher", "")

            if not item.get("link"):
                tag = "ok"
                status = "링크 없음"
                chk = CHK_OFF
                checked = False
            elif not issues:
                tag = "ok"
                status = "통과"
                chk = CHK_OFF
                checked = False
            else:
                tag = "err"
                status = f"문제 {len(issues)}건"
                chk = CHK_OFF
                checked = False

            iid = self.tree.insert(
                "", tk.END,
                values=(chk, status, param, publisher, title),
                tags=(tag,),
            )
            self.checked[iid] = checked
            self.tree_data[iid] = (item, issues, docx_info, blog_info)


# ═══════════════════════════════════════════════════════
#  실행
# ═══════════════════════════════════════════════════════
if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
