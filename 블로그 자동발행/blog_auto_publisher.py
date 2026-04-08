#!/usr/bin/env python3
"""네이버 블로그 자동 발행 — Google Sheets 연동 + 저장 템플릿 적용

사용법:
  python blog_auto_publisher.py            시트 읽어 자동 발행
  python blog_auto_publisher.py login      수동 로그인 (창만 열어줌)
  python blog_auto_publisher.py test       시트 연결 테스트
  python blog_auto_publisher.py discover   에디터 열고 템플릿 셀렉터 탐색
"""

import json
import os
import re
import sys
import time

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from blog_post import NaverBlogPoster, find_element_by_selectors, PROFILE_DIR
import sheets_handler

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")


# ────────────────────────────────────────────────
#  설정 로드
# ────────────────────────────────────────────────

def load_config() -> dict:
    """config.json 로드. 필수 값 누락 시 안내."""
    defaults = {
        "sheet_id": "",
        "tab_name": "",
        "blog_id_col": "B",
        "keyword_col": "C",
        "title_col": "D",
        "publish_url_col": "E",
        "start_row": 2,
        "credentials_path": "../credentials.json",
    }

    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        # 기존 값이 기본값보다 우선
        defaults.update(saved)

    # credentials_path를 절대 경로로 변환
    cred = defaults["credentials_path"]
    if not os.path.isabs(cred):
        defaults["credentials_path"] = os.path.normpath(os.path.join(BASE_DIR, cred))

    return defaults


def validate_config(config: dict) -> bool:
    """필수 설정 확인"""
    missing = []
    if not config.get("sheet_id"):
        missing.append("sheet_id")
    if not config.get("tab_name"):
        missing.append("tab_name")

    if missing:
        print(f"[오류] config.json에 필수 값이 비어있습니다: {', '.join(missing)}")
        print(f"  설정 파일: {CONFIG_FILE}")
        return False
    return True


# ────────────────────────────────────────────────
#  템플릿 적용 (2단계에서 셀렉터 확정 예정)
# ────────────────────────────────────────────────

def apply_template(driver, template_name: str) -> bool:
    """네이버 에디터에서 저장 템플릿을 이름으로 찾아 적용.

    플로우: 툴바 템플릿 버튼 → 나의 템플릿 목록 → 이름 매칭 → 적용
    실패 시 수동 적용 대기 모드로 전환.
    """
    print(f"  템플릿 적용: {template_name}")

    # iframe 밖으로 나와야 툴바 접근 가능한 경우도 있음
    try:
        driver.switch_to.default_content()
    except Exception:
        pass

    # ── 1단계: 툴바에서 "템플릿" 버튼 클릭 ──
    template_btn = _find_template_button(driver)
    if not template_btn:
        print("  [!] 템플릿 버튼을 자동으로 찾지 못했습니다")
        return _manual_fallback(driver, template_name)

    template_btn.click()
    time.sleep(0.5)

    # 패널이 열렸는지 확인 (toggle 버튼 → se-is-selected 클래스 추가됨)
    panel_open = driver.execute_script("""
        var btn = document.querySelector('button[data-name="template"]');
        if (btn && btn.classList.contains('se-is-selected')) return true;
        var panel = document.querySelector(
            '[class*="template-panel"], [class*="template_panel"]'
        );
        return panel !== null;
    """)
    if not panel_open:
        time.sleep(0.5)

    # ── 2단계: 나의 템플릿 탭 클릭 ──
    _click_my_template_tab(driver)

    # ── 3단계: 템플릿 이름으로 항목 찾아 클릭 ──
    if not _select_template_by_name(driver, template_name):
        print(f"  [!] 템플릿 '{template_name}'을 목록에서 찾지 못했습니다")
        return _manual_fallback(driver, template_name)

    time.sleep(0.5)

    # 템플릿 클릭으로 바로 적용됨 → DOM 교체 대기
    time.sleep(1)
    print("  템플릿 적용 완료!")
    return True


def _find_template_button(driver):
    """툴바에서 템플릿 버튼을 찾는다."""
    # 확정 셀렉터 (discover 결과 기반)
    selectors = [
        "button[data-name='template']",
        "button.se-template-toolbar-button",
        "//button[contains(., '템플릿')]",
    ]
    return find_element_by_selectors(driver, selectors, wait=5)


def _click_my_template_tab(driver):
    """'내 템플릿' 탭 클릭."""
    # 확정 셀렉터: button.se-tab-button[value='my']
    selectors = [
        "button.se-tab-button[value='my']",
        "//button[contains(text(), '내 템플릿')]",
    ]
    tab = find_element_by_selectors(driver, selectors, wait=2)
    if tab:
        tab.click()
        print("  '내 템플릿' 탭 클릭")
        time.sleep(0.5)  # 내 템플릿 목록 로드 대기


def _select_template_by_name(driver, name: str) -> bool:
    """템플릿 목록에서 이름이 일치하는 항목을 클릭.

    확정 DOM 구조:
      li.se-doc-template-item
        a.se-doc-template[role='button']  ← 클릭 대상
          strong.se-doc-template-title     ← 이름 매칭
    """
    try:
        clicked = driver.execute_script("""
            var name = arguments[0];
            // 1) strong.se-doc-template-title 에서 이름 매칭
            var titles = document.querySelectorAll('strong.se-doc-template-title');
            for (var t of titles) {
                if (t.textContent.trim() === name) {
                    // 부모 a.se-doc-template 클릭
                    var link = t.closest('a.se-doc-template');
                    if (link) { link.click(); return true; }
                    // fallback: 부모 li 클릭
                    var li = t.closest('li.se-doc-template-item');
                    if (li) { li.click(); return true; }
                    t.click(); return true;
                }
            }
            // 2) 부분 매칭 (포함 관계)
            for (var t of titles) {
                if (t.textContent.trim().includes(name) || name.includes(t.textContent.trim())) {
                    var link = t.closest('a.se-doc-template');
                    if (link) { link.click(); return true; }
                    t.click(); return true;
                }
            }
            return false;
        """, name)
        if clicked:
            print(f"  템플릿 항목 선택: {name}")
            return True
    except Exception:
        pass

    return False


def _click_apply_or_confirm(driver):
    """적용/확인 버튼을 찾아 클릭. 템플릿 클릭 시 바로 적용되는 경우도 있음."""
    apply_selectors = [
        "//button[contains(text(), '적용')]",
        "//button[contains(text(), '확인')]",
        "//button[contains(text(), '넣기')]",
        "button[class*='confirm']",
        "button[class*='apply']",
    ]
    btn = find_element_by_selectors(driver, apply_selectors, wait=3)
    if btn:
        btn.click()
        print("  적용 버튼 클릭")
    else:
        print("  (별도 적용 버튼 없음 — 클릭으로 바로 적용된 것으로 판단)")


def _dismiss_confirm_popup(driver):
    """추가 확인 팝업 (덮어쓰기 경고 등) 처리."""
    try:
        popup_btn = driver.execute_script("""
            var buttons = document.querySelectorAll('button');
            for (var b of buttons) {
                var text = (b.textContent || '').trim();
                if (text === '확인' || text === '적용' || text === '예'
                    || text === 'OK' || text === 'Yes') {
                    // 모달/팝업 내부의 버튼인지 확인
                    var parent = b.closest('[class*="popup"], [class*="modal"], '
                                          + '[class*="dialog"], [class*="layer"], '
                                          + '[role="dialog"]');
                    if (parent) {
                        return b;
                    }
                }
            }
            return null;
        """)
        if popup_btn:
            popup_btn.click()
            print("  확인 팝업 처리")
    except Exception:
        pass


def _manual_fallback(driver, template_name: str) -> bool:
    """자동 적용 실패 시 수동 대기."""
    print(f"  → 수동으로 '{template_name}' 템플릿을 적용해주세요.")
    result = input("  적용 완료 후 Enter (건너뛰려면 's' 입력): ").strip().lower()
    if result == "s":
        print("  템플릿 적용 건너뜀")
        return False
    return True


# ────────────────────────────────────────────────
#  카테고리 선택
# ────────────────────────────────────────────────

def select_category(driver, category_name: str) -> bool:
    """발행 설정 다이얼로그에서 카테고리를 선택한다."""
    if not category_name:
        return True

    print(f"  카테고리 선택: {category_name}")

    # 카테고리 드롭다운 버튼 클릭
    cat_selectors = [
        "button[aria-label='카테고리 목록 버튼']",
        "button[class*='selectbox_button']",
    ]
    cat_btn = find_element_by_selectors(driver, cat_selectors, wait=3)
    if not cat_btn:
        print("  [!] 카테고리 드롭다운을 찾지 못했습니다")
        return False

    cat_btn.click()
    time.sleep(0.5)

    # 확정 DOM: SPAN[data-testid^="categoryItemText_"]에 실제 이름,
    # 부모 LABEL[role="button"]을 클릭해야 선택됨
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
            print(f"  카테고리 선택 완료: {category_name}")
            time.sleep(0.5)
            return True
    except Exception:
        pass

    print(f"  [!] 카테고리 '{category_name}'을 목록에서 찾지 못했습니다")
    return False


def set_open_type(driver, is_public: bool) -> bool:
    """발행 설정 다이얼로그에서 공개/비공개를 선택한다."""
    target_id = "open_public" if is_public else "open_private"
    label_text = "전체공개" if is_public else "비공개"

    try:
        label = driver.execute_script("""
            var targetId = arguments[0];
            var label = document.querySelector('label[for="' + targetId + '"]');
            return label;
        """, target_id)
        if label:
            label.click()
            print(f"  공개 설정: {label_text}")
            time.sleep(0.3)
            return True
    except Exception:
        pass

    print(f"  [!] 공개 설정 변경 실패")
    return False


# ────────────────────────────────────────────────
#  발행 + URL 추출
# ────────────────────────────────────────────────

def publish_and_get_url(poster: NaverBlogPoster, category: str = "",
                        is_public: bool = False) -> str | None:
    """발행 설정 → 카테고리 선택 → 공개설정 → 최종 발행 → URL 추출."""
    # 1) 발행 설정 다이얼로그 열기
    poster.open_publish_dialog()

    # 2) 카테고리 선택
    if category:
        select_category(poster.driver, category)

    # 3) 공개/비공개 설정
    set_open_type(poster.driver, is_public)

    # 4) 최종 발행
    success = poster.confirm_publish()
    if not success:
        return None

    # 발행 후 리다이렉트 대기 (페이지 전환될 때까지)
    driver = poster.driver
    blog_id = poster.blog_id

    # 방법 1: 페이지 전환 대기 → URL에서 logNo 추출
    time.sleep(2)
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    current_url = driver.current_url
    match = re.search(r"blog\.naver\.com/[^/]+/(\d{10,})", current_url)
    if match:
        print(f"  발행 URL: {current_url}")
        return current_url

    # 방법 2: fetch API로 최신 글 logNo 추출 (페이지 이동 없음)
    try:
        log_no = driver.execute_script("""
            var blogId = arguments[0];
            var xhr = new XMLHttpRequest();
            xhr.open('GET',
                'https://blog.naver.com/PostTitleListAsync.naver'
                + '?blogId=' + blogId + '&currentPage=1&countPerPage=1',
                false);
            xhr.send();
            if (xhr.status === 200) {
                var m = xhr.responseText.match(/"logNo"\\s*:\\s*"(\\d+)"/);
                if (m) return m[1];
            }
            return null;
        """, blog_id)
        if log_no:
            url = f"https://blog.naver.com/{blog_id}/{log_no}"
            print(f"  발행 URL: {url}")
            return url
    except Exception as e:
        print(f"  URL 추출 실패: {e}")

    return None


# ────────────────────────────────────────────────
#  메인 발행 루프
# ────────────────────────────────────────────────

def discover_selectors(config: dict):
    """에디터를 열고 JS로 DOM을 스캔하여 템플릿 관련 셀렉터를 탐색."""
    # blog_id가 필요하므로 config에서 가져오거나 기본값 사용
    blog_id = config.get("discover_blog_id", "")
    if not blog_id:
        blog_id = input("  탐색할 블로그 ID를 입력하세요: ").strip()
        if not blog_id:
            print("  블로그 ID가 필요합니다.")
            return

    poster = NaverBlogPoster(blog_id=blog_id)
    poster.driver = poster.create_driver(headless=False)

    try:
        # 로그인 확인
        poster.driver.get("https://www.naver.com")
        time.sleep(2)
        if not poster._is_logged_in():
            poster.driver.get("https://nid.naver.com/nidlogin.login")
            print("  로그인이 필요합니다. 브라우저에서 로그인해주세요.")
            input("  로그인 완료 후 Enter 키를 누르세요... ")

        # 에디터 이동
        poster.navigate_to_editor()

        # iframe 밖으로 나와서 전체 DOM 탐색
        try:
            poster.driver.switch_to.default_content()
        except Exception:
            pass

        print(f"\n{'='*60}")
        print("  에디터 DOM 탐색 결과")
        print(f"{'='*60}")

        # 1) 모든 toolbar 버튼 스캔
        buttons_info = poster.driver.execute_script("""
            var results = [];
            var buttons = document.querySelectorAll('button, [role="button"]');
            for (var b of buttons) {
                var info = {
                    tag: b.tagName,
                    text: (b.textContent || '').trim().substring(0, 50),
                    title: b.title || '',
                    ariaLabel: b.getAttribute('aria-label') || '',
                    dataCommand: b.getAttribute('data-command') || '',
                    dataName: b.getAttribute('data-name') || '',
                    dataType: b.getAttribute('data-type') || '',
                    className: (b.className || '').substring(0, 80),
                    id: b.id || ''
                };
                // 의미 있는 정보가 있는 버튼만
                if (info.text || info.title || info.ariaLabel || info.dataCommand
                    || info.dataName || info.dataType) {
                    results.push(info);
                }
            }
            return results;
        """)

        if buttons_info:
            print(f"\n  [버튼 목록] 총 {len(buttons_info)}개\n")
            for i, btn in enumerate(buttons_info):
                parts = []
                if btn.get("text"):
                    parts.append(f"text=\"{btn['text']}\"")
                if btn.get("title"):
                    parts.append(f"title=\"{btn['title']}\"")
                if btn.get("ariaLabel"):
                    parts.append(f"aria-label=\"{btn['ariaLabel']}\"")
                if btn.get("dataCommand"):
                    parts.append(f"data-command=\"{btn['dataCommand']}\"")
                if btn.get("dataName"):
                    parts.append(f"data-name=\"{btn['dataName']}\"")
                if btn.get("dataType"):
                    parts.append(f"data-type=\"{btn['dataType']}\"")
                if btn.get("className"):
                    parts.append(f"class=\"{btn['className']}\"")
                if btn.get("id"):
                    parts.append(f"id=\"{btn['id']}\"")
                print(f"  {i+1:3d}. {' | '.join(parts)}")

        # 2) 템플릿 관련 요소 하이라이트
        template_hits = poster.driver.execute_script("""
            var hits = [];
            var all = document.querySelectorAll('*');
            for (var el of all) {
                var attrs = '';
                for (var a of el.attributes || []) {
                    attrs += a.name + '=' + a.value + ' ';
                }
                var text = (el.textContent || '').trim();
                var combined = attrs + text;
                if (combined.includes('템플릿') || combined.toLowerCase().includes('template')) {
                    hits.push({
                        tag: el.tagName,
                        text: text.substring(0, 60),
                        className: (typeof el.className === 'string' ? el.className : '').substring(0, 80),
                        id: el.id || '',
                        attrs: attrs.substring(0, 200)
                    });
                }
            }
            return hits;
        """)

        if template_hits:
            print(f"\n  ['템플릿' 관련 요소] {len(template_hits)}개\n")
            for i, hit in enumerate(template_hits):
                print(f"  {i+1}. <{hit['tag']}> text=\"{hit['text']}\"")
                if hit.get("className"):
                    print(f"     class=\"{hit['className']}\"")
                if hit.get("id"):
                    print(f"     id=\"{hit['id']}\"")
                if hit.get("attrs"):
                    print(f"     attrs: {hit['attrs']}")
        else:
            print("\n  [!] '템플릿' 관련 요소를 찾지 못했습니다.")
            print("  → 에디터가 완전히 로드되었는지 확인하세요.")
            print("  → 수동으로 '템플릿' 버튼을 클릭한 후 다시 스캔할 수 있습니다.")

        print(f"\n{'='*60}")
        print("  r: 패널 재스캔 / p: 발행 다이얼로그 스캔 / c: 카테고리 스캔 / q: 종료")
        while True:
            cmd = input("  명령(r/p/q): ").strip().lower()
            if cmd == "q":
                break
            elif cmd == "p":
                # 발행 다이얼로그 스캔 (발행 버튼 클릭 후 나타나는 팝업)
                hits = poster.driver.execute_script("""
                    var hits = [];
                    // 팝업/모달/다이얼로그 요소 찾기
                    var containers = document.querySelectorAll(
                        '[class*="popup"], [class*="modal"], [class*="dialog"], '
                        + '[class*="layer"], [class*="publish"], [class*="setting"], '
                        + '[role="dialog"], [class*="dimmed"]'
                    );
                    var targets = [];
                    containers.forEach(function(c) {
                        c.querySelectorAll('*').forEach(function(el) { targets.push(el); });
                        targets.push(c);
                    });
                    var seen = new Set();
                    for (var el of targets) {
                        if (seen.has(el)) continue;
                        seen.add(el);
                        var text = (el.textContent || '').trim();
                        if (text.length > 200) continue;
                        var attrs = '';
                        for (var a of el.attributes || []) {
                            attrs += a.name + '=' + a.value + ' ';
                        }
                        hits.push({
                            tag: el.tagName,
                            text: text.substring(0, 80),
                            className: (typeof el.className === 'string' ? el.className : '').substring(0, 120),
                            attrs: attrs.substring(0, 250)
                        });
                    }
                    return hits;
                """)
                print(f"\n  [발행 다이얼로그 스캔] {len(hits)}개\n")
                if len(hits) == 0:
                    print("  다이얼로그를 찾지 못했습니다. 발행 버튼을 클릭했는지 확인하세요.")
                for i, hit in enumerate(hits):
                    print(f"  {i+1}. <{hit['tag']}> text=\"{hit['text']}\"")
                    if hit.get("className"):
                        print(f"     class=\"{hit['className']}\"")
                    if hit.get("attrs"):
                        print(f"     attrs: {hit['attrs']}")
                print()
            elif cmd == "r":
                # 재스캔: 템플릿 패널 내부 요소만 집중 스캔
                hits = poster.driver.execute_script("""
                    var hits = [];
                    // 1) template-panel 클래스를 가진 컨테이너 찾기
                    var panels = document.querySelectorAll(
                        '[class*="template-panel"], [class*="template_panel"], '
                        + '[class*="templatePanel"], [class*="se-panel"]'
                    );
                    // 2) 패널 내부 클릭 가능한 요소들 수집
                    var targets = [];
                    if (panels.length > 0) {
                        panels.forEach(function(p) {
                            var children = p.querySelectorAll('*');
                            children.forEach(function(c) { targets.push(c); });
                            targets.push(p);
                        });
                    } else {
                        // 패널 못 찾으면 template 키워드로 fallback
                        document.querySelectorAll('*').forEach(function(el) {
                            var cls = (typeof el.className === 'string' ? el.className : '').toLowerCase();
                            if (cls.includes('template') || cls.includes('panel')) {
                                targets.push(el);
                            }
                        });
                    }
                    // 중복 제거 + 정보 수집
                    var seen = new Set();
                    for (var el of targets) {
                        if (seen.has(el)) continue;
                        seen.add(el);
                        var text = (el.textContent || '').trim();
                        // 너무 긴 텍스트는 컨테이너이므로 건너뛰기
                        if (text.length > 200) continue;
                        var attrs = '';
                        for (var a of el.attributes || []) {
                            attrs += a.name + '=' + a.value + ' ';
                        }
                        hits.push({
                            tag: el.tagName,
                            text: text.substring(0, 80),
                            className: (typeof el.className === 'string' ? el.className : '').substring(0, 120),
                            attrs: attrs.substring(0, 250)
                        });
                    }
                    return hits;
                """)
                print(f"\n  [패널 내부 스캔] {len(hits)}개\n")
                if len(hits) == 0:
                    print("  패널을 찾지 못했습니다. 템플릿 버튼을 클릭했는지 확인하세요.")
                for i, hit in enumerate(hits):
                    print(f"  {i+1}. <{hit['tag']}> text=\"{hit['text']}\"")
                    if hit.get("className"):
                        print(f"     class=\"{hit['className']}\"")
                    if hit.get("attrs"):
                        print(f"     attrs: {hit['attrs']}")
                print()

            elif cmd == "c":
                # 카테고리 관련 요소 스캔
                hits = poster.driver.execute_script("""
                    var hits = [];
                    var all = document.querySelectorAll('*');
                    for (var el of all) {
                        var text = (el.textContent || '').trim();
                        var cls = (typeof el.className === 'string') ? el.className : '';
                        var attrs = '';
                        for (var a of el.attributes || []) {
                            attrs += a.name + '=' + a.value + ' ';
                        }
                        var combined = (text + cls + attrs).toLowerCase();
                        if (combined.includes('categ') || combined.includes('카테고리')
                            || combined.includes('주제')) {
                            if (text.length < 200) {
                                hits.push({
                                    tag: el.tagName,
                                    text: text.substring(0, 80),
                                    className: cls.substring(0, 120),
                                    attrs: attrs.substring(0, 250)
                                });
                            }
                        }
                    }
                    return hits;
                """)
                print(f"\n  [카테고리 스캔] {len(hits)}개\n")
                if len(hits) == 0:
                    print("  카테고리 관련 요소를 찾지 못했습니다.")
                for i, hit in enumerate(hits):
                    print(f"  {i+1}. <{hit['tag']}> text=\"{hit['text']}\"")
                    if hit.get("className"):
                        print(f"     class=\"{hit['className']}\"")
                    if hit.get("attrs"):
                        print(f"     attrs: {hit['attrs']}")
                print()

    finally:
        if poster.driver:
            poster.driver.quit()
            poster.driver = None


def run_publish(config: dict):
    """시트에서 대기 행을 읽어 순차 발행."""
    # 시트 연결
    ws = sheets_handler.connect(
        config["sheet_id"], config["tab_name"], config["credentials_path"]
    )
    if not ws:
        return

    # 대기 행 조회
    pending = sheets_handler.get_pending_rows(ws, config)
    if not pending:
        print("\n발행할 글이 없습니다. (E열이 모두 채워져 있음)")
        return

    skip_title = config.get("skip_title_input", False)
    publish_delay = config.get("publish_delay_sec", 3)

    print(f"\n{'='*50}")
    print(f"  {len(pending)}개 글 발행 예정")
    if skip_title:
        print(f"  (제목 입력: 스킵 — 템플릿 제목 사용)")
    print(f"{'='*50}")
    for p in pending:
        print(f"  행 {p['row_num']}: [{p['blog_id']}] {p['title'][:40]}")
    print()

    # 첫 행의 blog_id로 포스터 생성 (행마다 변경됨)
    poster = NaverBlogPoster(blog_id=pending[0]["blog_id"])
    poster.driver = poster.create_driver(headless=False)

    try:
        # 로그인 확인
        poster.driver.get("https://www.naver.com")
        time.sleep(1)
        if not poster._is_logged_in():
            poster.driver.get("https://nid.naver.com/nidlogin.login")
            print("  로그인이 필요합니다. 브라우저에서 로그인해주세요.")
            input("  로그인 완료 후 Enter 키를 누르세요... ")
            poster.driver.get("https://www.naver.com")
            time.sleep(1)
            if not poster._is_logged_in():
                print("[오류] 로그인 실패. 다시 시도해주세요.")
                return

        print("  로그인 확인 완료\n")

        # 발행 루프
        success_count = 0
        fail_count = 0

        for idx, row in enumerate(pending, 1):
            row_num = row["row_num"]
            blog_id = row["blog_id"]
            title = row["title"]
            template_name = row["template_name"]
            category = row.get("category", "")
            is_public = row.get("is_public", False)

            # 행마다 blog_id 갱신
            poster.blog_id = blog_id

            print(f"[{idx}/{len(pending)}] 행 {row_num}: [{blog_id}] {title[:40]}")
            if template_name != title:
                print(f"  템플릿: {template_name}")
            if category:
                print(f"  카테고리: {category}")
            print(f"  공개: {'전체공개' if is_public else '비공개'}")

            try:
                # 에디터 이동
                poster.navigate_to_editor()

                # 템플릿 적용 (C열 키워드 = 템플릿명)
                template_applied = apply_template(poster.driver, template_name)

                # 제목 입력 (D열 실제 제목으로 교체)
                if not skip_title:
                    poster.input_title(title)
                elif not template_applied:
                    poster.input_title(title)

                # 발행 (설정 → 카테고리 → 최종발행) + URL 추출
                url = publish_and_get_url(poster, category=category, is_public=is_public)

                if url:
                    sheets_handler.write_url(ws, row_num, config["publish_url_col"], url)
                    success_count += 1
                    print(f"  → 완료!\n")
                else:
                    sheets_handler.write_url(
                        ws, row_num, config["publish_url_col"], "발행완료(URL미확인)"
                    )
                    success_count += 1
                    print(f"  → 발행됨 (URL 미확인)\n")

            except Exception as e:
                fail_count += 1
                print(f"  [!] 오류: {e}")
                try:
                    poster.driver.save_screenshot(
                        os.path.join(BASE_DIR, f"error_row{row_num}.png")
                    )
                    print(f"  스크린샷: error_row{row_num}.png")
                except Exception:
                    pass
                print()

            # 행 간 대기
            if idx < len(pending):
                time.sleep(publish_delay)

        # 완료 요약
        print(f"{'='*50}")
        print(f"  완료: 성공 {success_count}건, 실패 {fail_count}건")
        print(f"{'='*50}")

    finally:
        if poster.driver:
            poster.driver.quit()
            poster.driver = None


# ────────────────────────────────────────────────
#  CLI
# ────────────────────────────────────────────────

def cmd_login(config: dict):
    """수동 로그인 — 브라우저 창만 열어줌."""
    poster = NaverBlogPoster(blog_id="login")
    poster.login_interactive()


def cmd_test(config: dict):
    """시트 연결 테스트."""
    ws = sheets_handler.connect(
        config["sheet_id"], config["tab_name"], config["credentials_path"]
    )
    if not ws:
        return

    pending = sheets_handler.get_pending_rows(ws, config)
    print(f"\n  발행 대기: {len(pending)}건")
    for p in pending[:10]:
        tpl = p.get("template_name", "")
        cat = p.get("category", "")
        extras = []
        if tpl and tpl != p['title']:
            extras.append(f"템플릿: {tpl}")
        if cat:
            extras.append(f"카테고리: {cat}")
        extra_str = f" ({', '.join(extras)})" if extras else ""
        print(f"    행 {p['row_num']}: [{p['blog_id']}] {p['title'][:40]}{extra_str}")
    if len(pending) > 10:
        print(f"    ... 외 {len(pending) - 10}건")


def main():
    config = load_config()

    if len(sys.argv) < 2:
        # 기본: 자동 발행
        if not validate_config(config):
            return
        run_publish(config)
        return

    cmd = sys.argv[1]

    if cmd == "login":
        cmd_login(config)
    elif cmd == "test":
        if not validate_config(config):
            return
        cmd_test(config)
    elif cmd == "discover":
        discover_selectors(config)
    else:
        print(f"알 수 없는 명령: {cmd}")
        print()
        print("사용법:")
        print("  python blog_auto_publisher.py            시트 읽어 자동 발행")
        print("  python blog_auto_publisher.py login      수동 로그인")
        print("  python blog_auto_publisher.py test       시트 연결 테스트")
        print("  python blog_auto_publisher.py discover   에디터 셀렉터 탐색")


if __name__ == "__main__":
    main()
