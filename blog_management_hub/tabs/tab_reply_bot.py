"""탭 1: 대댓글 봇 — 네이버 블로그/카페 대댓글 자동 작성 + 공개/비공개 전환
원본: blog_reply_bot/naver_reply_bot.py → GUI 탭으로 변환
"""

import os
import re
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from shared.browser_manager import create_visible_driver
from shared.gui_helpers import create_log_area


# ═══════════════════════════════════════════════════════
#  헬퍼 함수 (원본 유지)
# ═══════════════════════════════════════════════════════
def is_checked(value):
    if value is None:
        return False
    v = str(value).strip().upper()
    return v in ["TRUE", "완료", "O", "V", "Y", "YES", "1", "✓", "✔"]


def is_cafe_url(url):
    return "cafe.naver.com" in url


def switch_to_cafe_frame(driver):
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


def is_post_author(driver, post_url):
    if is_cafe_url(post_url):
        switch_to_cafe_frame(driver)
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


# ── 대댓글 작성 ──────────────────────────────────────
def find_and_reply(driver, target_comment, reply_text, post_url="", log=print, ask_manual=None):
    """댓글을 찾아 대댓글 작성. ask_manual: 수동 처리 요청 콜백"""
    if is_cafe_url(post_url):
        switch_to_cafe_frame(driver)
    else:
        switch_to_blog_frame(driver)
    time.sleep(2)

    try:
        cmt_btn = driver.find_element(By.CSS_SELECTOR, "a._cmtList")
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", cmt_btn)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", cmt_btn)
        log("    댓글 목록 펼치기")
        time.sleep(3)
    except:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight * 0.7)")
        time.sleep(2)

    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".u_cbox_comment_box"))
        )
    except:
        log("    댓글 로드 대기 시간 초과")

    try:
        cbox = driver.find_element(By.CSS_SELECTOR, ".u_cbox")
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", cbox)
        time.sleep(1)
    except:
        pass

    expand_all_comments(driver)

    comments = []
    for sel in [".u_cbox_comment_box", ".u_cbox_comment",
                "li.u_cbox_comment", ".comment_item"]:
        comments = driver.find_elements(By.CSS_SELECTOR, sel)
        if comments:
            break

    if not comments:
        log("    댓글 요소를 찾을 수 없습니다.")
        driver.switch_to.default_content()
        return False

    log(f"    {len(comments)}개 댓글 발견")
    target_clean = target_comment.strip()

    for comment_elem in comments:
        try:
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

            t1 = re.sub(r'\s+', '', target_clean)
            t2 = re.sub(r'\s+', '', comment_text)
            if t1 not in t2 and t2 not in t1:
                continue

            log(f"    매칭됨: \"{comment_text[:40]}\"")

            # 답글 버튼
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
                log("    답글 버튼을 찾을 수 없습니다.")
                continue

            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", reply_btn)
            time.sleep(0.5)
            driver.execute_script("arguments[0].click();", reply_btn)
            log("    답글 버튼 클릭")
            time.sleep(2)

            # 대댓글 입력
            text_input = None
            try:
                reply_areas = driver.find_elements(By.CSS_SELECTOR, ".u_cbox_reply_area")
                for ra in reply_areas:
                    if ra.is_displayed():
                        try:
                            guide = ra.find_element(By.CSS_SELECTOR, ".u_cbox_guide")
                            driver.execute_script("arguments[0].click();", guide)
                            time.sleep(1)
                        except:
                            try:
                                write_box = ra.find_element(By.CSS_SELECTOR, ".u_cbox_write")
                                driver.execute_script("arguments[0].click();", write_box)
                                time.sleep(1)
                            except:
                                pass
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

            if not text_input:
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
                log("    대댓글 입력창을 찾을 수 없습니다.")
                continue

            driver.execute_script("arguments[0].focus();", text_input)
            driver.execute_script("arguments[0].click();", text_input)
            time.sleep(0.5)
            text_input.send_keys(Keys.CONTROL, 'a')
            text_input.send_keys(Keys.DELETE)
            time.sleep(0.3)
            for char in reply_text:
                if char == '\n':
                    text_input.send_keys(Keys.SHIFT, Keys.ENTER)
                else:
                    text_input.send_keys(char)
                time.sleep(0.02)
            log(f"    대댓글 입력 완료: \"{reply_text[:40]}\"")
            time.sleep(1)

            # 등록 버튼
            submit_btn = None
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
                log("    등록 버튼을 찾을 수 없습니다.")
                if ask_manual:
                    ask_manual("등록 버튼을 찾을 수 없습니다. 수동으로 등록해주세요.")
                driver.switch_to.default_content()
                return True

            driver.execute_script("arguments[0].click();", submit_btn)
            log("    등록 완료!")
            time.sleep(2)
            driver.switch_to.default_content()
            return True

        except Exception as e:
            log(f"    처리 중 오류: {e}")
            continue

    log(f"    \"{target_clean[:30]}\" 댓글을 찾지 못했습니다.")
    driver.switch_to.default_content()
    return False


# ── 비공개/공개 전환 ──────────────────────────────────
def make_post_private(driver, post_url, log=print, ask_manual=None):
    try:
        switch_to_blog_frame(driver)

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
            log("    수정 버튼을 찾을 수 없습니다.")
            driver.switch_to.default_content()
            return "need_relogin"

        driver.execute_script("arguments[0].click();", edit_btn)
        log("    수정 버튼 클릭")

        # 에디터 로드 대기 (고정 5초 → 조건부 대기)
        driver.switch_to.default_content()
        try:
            iframe = WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.ID, "mainFrame"))
            )
            driver.switch_to.frame(iframe)
        except:
            log("    에디터 로드 실패")
            driver.switch_to.default_content()
            return False

        publish_btn = None
        try:
            publish_btn = WebDriverWait(driver, 15).until(
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
            log("    발행 버튼을 찾을 수 없습니다.")
            if ask_manual:
                ask_manual("발행 버튼을 찾을 수 없습니다. 수동으로 비공개 처리해주세요.")
            driver.switch_to.default_content()
            return True

        driver.execute_script("arguments[0].click();", publish_btn)
        log("    발행 버튼 클릭")

        # 발행 옵션 패널 대기 (고정 2초 → 조건부 대기)
        try:
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "label.radio_label__mB6ia, span.input_radio__yZcoa"))
            )
        except:
            time.sleep(1)

        private_clicked = False
        for label in driver.find_elements(By.CSS_SELECTOR, "label.radio_label__mB6ia"):
            try:
                if label.is_displayed() and "비공개" in label.text:
                    driver.execute_script("arguments[0].click();", label)
                    private_clicked = True
                    log("    비공개 선택")
                    time.sleep(0.3)
                    break
            except:
                pass
        if not private_clicked:
            for span in driver.find_elements(By.CSS_SELECTOR, "span.input_radio__yZcoa"):
                try:
                    if span.is_displayed() and "비공개" in span.text:
                        driver.execute_script("arguments[0].click();", span)
                        private_clicked = True
                        log("    비공개 선택 (span)")
                        time.sleep(0.3)
                        break
                except:
                    pass
        if not private_clicked:
            log("    비공개 옵션을 찾을 수 없습니다.")
            if ask_manual:
                ask_manual("비공개 옵션을 찾을 수 없습니다. 수동으로 처리해주세요.")
            driver.switch_to.default_content()
            return True

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
            log("    발행(비공개) 확인 클릭")
            time.sleep(1.5)
        else:
            log("    발행 확인 버튼을 찾을 수 없습니다.")
            if ask_manual:
                ask_manual("발행 확인 버튼을 찾을 수 없습니다. 수동으로 발행해주세요.")

        log("    글 비공개 처리 완료!")
        driver.switch_to.default_content()
        return True
    except Exception as e:
        log(f"    글 비공개 처리 오류: {e}")
        driver.switch_to.default_content()
        return False


def make_post_public(driver, post_url, log=print, ask_manual=None):
    try:
        switch_to_blog_frame(driver)

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
            log("    수정 버튼을 찾을 수 없습니다.")
            driver.switch_to.default_content()
            return "need_relogin"

        driver.execute_script("arguments[0].click();", edit_btn)
        log("    수정 버튼 클릭")

        # 에디터 로드 대기 (고정 5초 → 조건부 대기)
        driver.switch_to.default_content()
        try:
            iframe = WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.ID, "mainFrame"))
            )
            driver.switch_to.frame(iframe)
        except:
            log("    에디터 로드 실패")
            driver.switch_to.default_content()
            return False

        publish_btn = None
        try:
            publish_btn = WebDriverWait(driver, 15).until(
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
            log("    발행 버튼을 찾을 수 없습니다.")
            if ask_manual:
                ask_manual("수동으로 공개 처리해주세요.")
            driver.switch_to.default_content()
            return True

        driver.execute_script("arguments[0].click();", publish_btn)
        log("    발행 버튼 클릭")

        # 발행 옵션 패널 대기 (고정 2초 → 조건부 대기)
        try:
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "label.radio_label__mB6ia, span.input_radio__yZcoa"))
            )
        except:
            time.sleep(1)

        public_clicked = False
        for label in driver.find_elements(By.CSS_SELECTOR, "label.radio_label__mB6ia"):
            try:
                txt = label.text.strip()
                if label.is_displayed() and ("전체 공개" in txt or "전체공개" in txt):
                    driver.execute_script("arguments[0].click();", label)
                    public_clicked = True
                    log("    전체 공개 선택")
                    time.sleep(0.3)
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
                        log("    전체 공개 선택 (span)")
                        time.sleep(0.3)
                        break
                except:
                    pass
        if not public_clicked:
            log("    전체 공개 옵션을 찾을 수 없습니다.")
            if ask_manual:
                ask_manual("수동으로 전체 공개 설정해주세요.")
            driver.switch_to.default_content()
            return True

        # 체크박스 (공감/외부공유 등)
        SKIP_KEYWORDS = ["기본값", "공지"]
        try:
            for label in driver.find_elements(By.CSS_SELECTOR, "label.checkbox_label__n5RMI, label[class*='checkbox']"):
                try:
                    if not label.is_displayed():
                        continue
                    label_text = label.text.strip()
                    if any(kw in label_text for kw in SKIP_KEYWORDS):
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
                        log(f"    체크: {label_text[:20]}")
                        time.sleep(0.2)
                except:
                    pass
        except:
            pass

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
            log("    발행(공개) 확인 클릭")
            time.sleep(1.5)
        else:
            log("    발행 확인 버튼을 찾을 수 없습니다.")
            if ask_manual:
                ask_manual("수동으로 발행해주세요.")

        log("    글 공개 처리 완료!")
        driver.switch_to.default_content()
        return True
    except Exception as e:
        log(f"    글 공개 처리 오류: {e}")
        driver.switch_to.default_content()
        return False


def make_cafe_post_private(driver, post_url, log=print, ask_manual=None):
    try:
        switch_to_cafe_frame(driver)
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
            log("    수정 버튼을 찾을 수 없습니다.")
            driver.switch_to.default_content()
            return "need_relogin"

        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", edit_btn)
        time.sleep(0.3)
        ActionChains(driver).click(edit_btn).perform()
        log("    수정 버튼 클릭")

        # 새 탭 대기 (0.5초 간격으로 체크)
        for _ in range(20):
            time.sleep(0.5)
            if len(driver.window_handles) > len(windows_before):
                break

        windows_after = driver.window_handles
        if len(windows_after) <= len(windows_before):
            log("    새 탭이 열리지 않았습니다.")
            if ask_manual:
                ask_manual("새 탭이 열리지 않았습니다. 수동으로 비공개 처리해주세요.")
            driver.switch_to.default_content()
            return True

        new_window = [w for w in windows_after if w not in windows_before][0]
        original_window = windows_before[0]
        driver.switch_to.window(new_window)

        # 카페 에디터 로드 대기 (고정 5초 → 공개설정 버튼 직접 대기)
        open_set_btn = None
        try:
            open_set_btn = WebDriverWait(driver, 15).until(
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
            log("    공개 설정 패널 열기")
            time.sleep(0.5)

        # 멤버공개
        member_set = False
        for label in driver.find_elements(By.TAG_NAME, "label"):
            try:
                if label.is_displayed() and label.text.strip() == "멤버공개":
                    driver.execute_script("arguments[0].click();", label)
                    member_set = True
                    log("    멤버공개 선택")
                    time.sleep(0.3)
                    break
            except:
                pass
        if not member_set:
            for div in driver.find_elements(By.CSS_SELECTOR, "div.FormInputRadio"):
                try:
                    if div.is_displayed() and "멤버" in div.text:
                        driver.execute_script("arguments[0].click();", div)
                        member_set = True
                        time.sleep(0.3)
                        break
                except:
                    pass
        if not member_set and ask_manual:
            ask_manual("멤버공개를 자동 선택할 수 없습니다. 수동 처리해주세요.")

        # 검색·서비스공개 해제
        for label in driver.find_elements(By.TAG_NAME, "label"):
            try:
                txt = label.text.strip()
                if not label.is_displayed():
                    continue
                if "검색" in txt and "서비스" in txt:
                    try:
                        cb = label.find_element(By.CSS_SELECTOR, "input[type='checkbox']")
                        if cb.is_selected():
                            driver.execute_script("arguments[0].click();", label)
                            log("    검색·서비스공개 체크 해제")
                            time.sleep(0.3)
                    except:
                        driver.execute_script("arguments[0].click();", label)
                        time.sleep(0.3)
                    break
            except:
                pass

        # 등록
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
            log("    등록 클릭")
            time.sleep(1.5)
        elif ask_manual:
            ask_manual("등록 버튼을 찾을 수 없습니다. 수동 등록해주세요.")

        try:
            driver.close()
            driver.switch_to.window(original_window)
        except:
            pass

        log("    카페 글 멤버공개 처리 완료!")
        driver.switch_to.default_content()
        return True
    except Exception as e:
        log(f"    카페 비공개 처리 오류: {e}")
        try:
            if len(driver.window_handles) > 1:
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
        except:
            pass
        driver.switch_to.default_content()
        return False


def make_cafe_post_public(driver, post_url, log=print, ask_manual=None):
    try:
        switch_to_cafe_frame(driver)
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
            log("    수정 버튼을 찾을 수 없습니다.")
            driver.switch_to.default_content()
            return "need_relogin"

        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", edit_btn)
        time.sleep(0.3)
        ActionChains(driver).click(edit_btn).perform()
        log("    수정 버튼 클릭")

        # 새 탭 대기 (0.5초 간격으로 체크)
        for _ in range(20):
            time.sleep(0.5)
            if len(driver.window_handles) > len(windows_before):
                break

        windows_after = driver.window_handles
        if len(windows_after) <= len(windows_before):
            log("    새 탭이 열리지 않았습니다.")
            if ask_manual:
                ask_manual("수동으로 공개 처리해주세요.")
            driver.switch_to.default_content()
            return True

        new_window = [w for w in windows_after if w not in windows_before][0]
        original_window = windows_before[0]
        driver.switch_to.window(new_window)

        # 카페 에디터 로드 대기 (고정 5초 → 공개설정 버튼 직접 대기)
        open_set_btn = None
        try:
            open_set_btn = WebDriverWait(driver, 15).until(
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
            log("    공개 설정 패널 열기")
            time.sleep(0.5)

        # 전체공개
        public_set = False
        for label in driver.find_elements(By.TAG_NAME, "label"):
            try:
                if label.is_displayed() and label.text.strip() == "전체공개":
                    driver.execute_script("arguments[0].click();", label)
                    public_set = True
                    log("    전체공개 선택")
                    time.sleep(0.3)
                    break
            except:
                pass
        if not public_set:
            for div in driver.find_elements(By.CSS_SELECTOR, "div.FormInputRadio"):
                try:
                    if div.is_displayed() and "전체" in div.text:
                        driver.execute_script("arguments[0].click();", div)
                        public_set = True
                        time.sleep(0.3)
                        break
                except:
                    pass
        if not public_set and ask_manual:
            ask_manual("전체공개를 자동 선택할 수 없습니다. 수동 처리해주세요.")

        # 검색·서비스공개 체크
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
                            log("    검색·서비스공개 체크")
                            time.sleep(0.3)
                    except:
                        driver.execute_script("arguments[0].click();", label)
                        time.sleep(0.3)
                    break
            except:
                pass

        # 등록
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
            log("    등록 클릭")
            time.sleep(1.5)
        elif ask_manual:
            ask_manual("등록 버튼을 찾을 수 없습니다. 수동 등록해주세요.")

        try:
            driver.close()
            driver.switch_to.window(original_window)
        except:
            pass

        log("    카페 글 전체공개 처리 완료!")
        driver.switch_to.default_content()
        return True
    except Exception as e:
        log(f"    카페 공개 처리 오류: {e}")
        try:
            if len(driver.window_handles) > 1:
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
        except:
            pass
        driver.switch_to.default_content()
        return False


# ═══════════════════════════════════════════════════════
#  GUI 탭
# ═══════════════════════════════════════════════════════
class ReplyBotTab(ttk.Frame):
    """대댓글 봇 탭"""

    def __init__(self, parent, sheets_client):
        super().__init__(parent, padding=10)
        self.root = self.winfo_toplevel()
        self.sheets = sheets_client
        self.driver = None
        self.running = False
        self._manual_event = threading.Event()
        self._build()

    def _build(self):
        # 시트 설정
        f1 = ttk.LabelFrame(self, text="시트 설정", padding=10)
        f1.pack(fill="x", pady=(0, 5))

        row1 = ttk.Frame(f1)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="시트 URL:", width=10).pack(side="left")
        self.sheet_url_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.sheet_url_var, width=60).pack(side="left", padx=5)
        ttk.Button(row1, text="시트 불러오기", command=self._load_sheet).pack(side="left", padx=5)

        # 로그인 버튼
        f_login = ttk.Frame(f1)
        f_login.pack(fill="x", pady=2)
        ttk.Button(f_login, text="네이버 로그인", command=self._login).pack(side="left")
        self.login_status = ttk.Label(f_login, text="미로그인", foreground="red")
        self.login_status.pack(side="left", padx=10)

        # 데이터 테이블
        f2 = ttk.LabelFrame(self, text="대기 목록", padding=5)
        f2.pack(fill="both", expand=True, pady=5)

        cols = [
            ("row", "행", 40),
            ("type", "유형", 50),
            ("link", "링크", 250),
            ("comment", "대상 댓글", 150),
            ("reply", "답글", 150),
            ("task", "작업", 80),
            ("status", "상태", 80),
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
        self.tree.tag_configure("warn", background="#fff3cd")
        self.tree.tag_configure("processing", background="#cce5ff")

        # 컨트롤
        f3 = ttk.Frame(self, padding=5)
        f3.pack(fill="x")

        self.btn_run = ttk.Button(f3, text="전체 실행", command=self._start_run)
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

    def _load_sheet(self):
        url = self.sheet_url_var.get().strip()
        if not url:
            messagebox.showwarning("경고", "시트 URL을 입력하세요.")
            return

        match = re.search(r'/d/([a-zA-Z0-9-_]+)', url)
        if not match:
            messagebox.showwarning("경고", "올바른 Google Sheets URL이 아닙니다.")
            return

        sheet_id = match.group(1)
        self.log("시트 연결 중...")

        def work():
            try:
                ss = self.sheets.get_spreadsheet(sheet_id)
                ws = ss.sheet1
                all_data = ws.get_all_values()
                self.root.after(0, lambda: self._on_sheet_loaded(ws, all_data))
            except Exception as e:
                self.log(f"[에러] 시트 연결 실패: {e}")

        threading.Thread(target=work, daemon=True).start()

    def _on_sheet_loaded(self, ws, all_data):
        self._ws = ws
        self.tree.delete(*self.tree.get_children())
        self._pending = []

        if len(all_data) < 2:
            self.log("데이터가 없습니다.")
            return

        rows = all_data[1:]
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

            if not need_reply and not need_private and not need_public:
                continue

            row_num = i + 2
            ptype = "카페" if is_cafe_url(link) else "블로그"
            tasks = []
            if need_reply:
                tasks.append("대댓글")
            if need_private:
                tasks.append("비공개")
            if need_public:
                tasks.append("공개")

            item = {
                "row_num": row_num, "link": link,
                "comment": comment, "reply": reply,
                "need_reply": need_reply,
                "need_private": need_private,
                "need_public": need_public,
            }
            self._pending.append(item)

            self.tree.insert("", "end", iid=str(row_num), values=(
                row_num, ptype, link[:50], comment[:30], reply[:30],
                "+".join(tasks), "대기"
            ))

        self.log(f"시트 로드 완료 — {len(self._pending)}건 대기")

    def _login(self):
        """네이버 로그인 (visible Chrome)"""
        self.log("브라우저 열기 중...")

        def work():
            try:
                if self.driver:
                    try:
                        self.driver.quit()
                    except:
                        pass
                self.driver = create_visible_driver()
                self.driver.get("https://nid.naver.com/nidlogin.login")
                self.root.after(0, lambda: self.login_status.configure(
                    text="로그인 페이지 열림 — 로그인 후 아래 확인 클릭", foreground="orange"
                ))
                self.root.after(0, self._show_login_confirm)
            except Exception as e:
                self.log(f"[에러] 브라우저 열기 실패: {e}")

        threading.Thread(target=work, daemon=True).start()

    def _show_login_confirm(self):
        result = messagebox.showinfo("네이버 로그인", "네이버에 로그인한 후 확인을 눌러주세요.")
        self.login_status.configure(text="로그인 완료", foreground="green")
        self.log("네이버 로그인 완료")

    def _ask_manual(self, msg):
        """수동 처리 요청 (input() 대체)"""
        self._manual_event.clear()

        def show():
            messagebox.showinfo("수동 처리 필요", msg)
            self._manual_event.set()

        self.root.after(0, show)
        self._manual_event.wait()

    def _start_run(self):
        if not self._pending:
            messagebox.showwarning("경고", "먼저 시트를 불러오세요.")
            return
        if not self.driver:
            messagebox.showwarning("경고", "먼저 네이버 로그인을 해주세요.")
            return
        if self.running:
            return

        self.running = True
        self.btn_run.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        threading.Thread(target=self._run_all, daemon=True).start()

    def _stop(self):
        self.running = False
        self.log("중지 요청됨...")

    def _run_all(self):
        total = len(self._pending)
        results = []

        for i, item in enumerate(self._pending):
            if not self.running:
                break

            row_num = item["row_num"]
            self.root.after(0, lambda r=row_num: (
                self.tree.set(str(r), "status", "진행중"),
                self.tree.item(str(r), tags=("processing",)),
            ))
            self.root.after(0, lambda idx=i: self.progress_label.configure(
                text=f"{idx+1}/{total}"
            ))

            status = self._process_item(item, f"{i+1}/{total}")
            results.append((row_num, status))

            tag = "ok" if status == "완료" else "error"
            self.root.after(0, lambda r=row_num, s=status, t=tag: (
                self.tree.set(str(r), "status", s),
                self.tree.item(str(r), tags=(t,)),
            ))

            time.sleep(1)

        # 결과 요약
        ok_cnt = sum(1 for _, s in results if s == "완료")
        fail_cnt = len(results) - ok_cnt
        self.log(f"\n결과: 성공 {ok_cnt}건, 실패 {fail_cnt}건")

        self.root.after(0, self._on_run_done)

    def _process_item(self, item, label):
        self.log(f"\n[{label}] 행{item['row_num']}")
        self.log(f"  링크: {item['link'][:60]}")

        try:
            self.driver.get(item["link"])
            # 페이지 로드 대기 (고정 3초 → 조건부)
            try:
                WebDriverWait(self.driver, 10).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
                time.sleep(0.5)
            except:
                time.sleep(2)

            # 비공개 글 alert
            try:
                alert = self.driver.switch_to.alert
                alert_text = alert.text
                alert.accept()
                if "비공개" in alert_text:
                    self.log("    → 비공개 글입니다. 재로그인 필요")
                    return "재로그인 필요"
            except:
                pass

            if not is_post_author(self.driver, item["link"]):
                self.log("    → 내 글이 아닙니다. 재로그인 필요")
                return "재로그인 필요"

            need_reload = False

            # 대댓글
            if item["need_reply"]:
                reply_ok = find_and_reply(
                    self.driver, item["comment"], item["reply"],
                    item["link"], log=self.log, ask_manual=self._ask_manual
                )
                if reply_ok:
                    item["need_reply"] = False
                    need_reload = True
                    try:
                        self._ws.update_cell(item["row_num"], 4, True)
                        self.log("    D열 체크 완료")
                    except Exception as e:
                        self.log(f"    D열 업데이트 실패: {e}")
                else:
                    return "대댓글 실패"

            # 비공개
            if item["need_private"]:
                if need_reload:
                    self.driver.get(item["link"])
                    try:
                        WebDriverWait(self.driver, 10).until(
                            lambda d: d.execute_script("return document.readyState") == "complete"
                        )
                        time.sleep(0.5)
                    except:
                        time.sleep(2)
                    need_reload = False
                if is_cafe_url(item["link"]):
                    priv_ok = make_cafe_post_private(
                        self.driver, item["link"], log=self.log, ask_manual=self._ask_manual
                    )
                else:
                    priv_ok = make_post_private(
                        self.driver, item["link"], log=self.log, ask_manual=self._ask_manual
                    )
                if priv_ok == "need_relogin":
                    return "재로그인 필요"
                elif priv_ok:
                    item["need_private"] = False
                    need_reload = True
                    try:
                        self._ws.update_cell(item["row_num"], 6, True)
                        self.log("    F열 체크 완료")
                    except Exception as e:
                        self.log(f"    F열 업데이트 실패: {e}")
                else:
                    return "비공개 실패"

            # 공개
            if item["need_public"]:
                if need_reload:
                    self.driver.get(item["link"])
                    try:
                        WebDriverWait(self.driver, 10).until(
                            lambda d: d.execute_script("return document.readyState") == "complete"
                        )
                        time.sleep(0.5)
                    except:
                        time.sleep(2)
                if is_cafe_url(item["link"]):
                    pub_ok = make_cafe_post_public(
                        self.driver, item["link"], log=self.log, ask_manual=self._ask_manual
                    )
                else:
                    pub_ok = make_post_public(
                        self.driver, item["link"], log=self.log, ask_manual=self._ask_manual
                    )
                if pub_ok == "need_relogin":
                    return "재로그인 필요"
                elif pub_ok:
                    item["need_public"] = False
                    try:
                        self._ws.update_cell(item["row_num"], 8, True)
                        self.log("    H열 체크 완료")
                    except Exception as e:
                        self.log(f"    H열 업데이트 실패: {e}")
                else:
                    return "공개 실패"

            return "완료"
        except Exception as e:
            self.log(f"  오류: {e}")
            return "실패"

    def _on_run_done(self):
        self.running = False
        self.btn_run.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.log("작업 완료!")
