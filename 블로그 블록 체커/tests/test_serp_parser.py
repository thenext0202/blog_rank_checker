# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from serp_parser import extract_dates


def test_extract_dates_상대형():
    # 인기글 블록 텍스트 모사 — 글마다 날짜 1개
    text = "글제목A 2일 전 글제목B 1주 전 글제목C 3주 전"
    assert extract_dates(text) == ["2일 전", "1주 전", "3주 전"]


def test_extract_dates_절대형_혼합():
    text = "2026.02.13. ... 14시간 전 ... 2025.09.18."
    assert extract_dates(text) == ["2026.02.13.", "14시간 전", "2025.09.18."]


def test_extract_dates_없으면_빈리스트():
    assert extract_dates("날짜 없는 텍스트") == []


from datetime import date
from serp_parser import normalize_date

TODAY = date(2026, 6, 4)

def test_normalize_상대_일():
    assert normalize_date("2일 전", TODAY) == date(2026, 6, 2)

def test_normalize_상대_주():
    assert normalize_date("1주 전", TODAY) == date(2026, 5, 28)

def test_normalize_상대_시간은_오늘():
    assert normalize_date("14시간 전", TODAY) == date(2026, 6, 4)

def test_normalize_어제_그제():
    assert normalize_date("어제", TODAY) == date(2026, 6, 3)
    assert normalize_date("그제", TODAY) == date(2026, 6, 2)

def test_normalize_절대형():
    assert normalize_date("2025.09.18.", TODAY) == date(2025, 9, 18)

def test_normalize_개월_근사30일():
    assert normalize_date("2개월 전", TODAY) == date(2026, 6, 4) - __import__("datetime").timedelta(days=60)


from serp_parser import classify

def _u(header, fe_view, blog, cafe):
    return {"header": header, "fe_view": fe_view, "blog": blog, "cafe": cafe}

def test_classify_인기글():  # 오메가3 영양제
    assert classify(_u("인기글", True, 10, 15), n_posts=7) == ("인기글", "인기글")

def test_classify_분야인기글():  # 코큐텐 영양제
    assert classify(_u("건강·의학 인기글", True, 13, 6), n_posts=7) == ("인기글", "건강·의학 인기글")

def test_classify_스블_키워드인기글():  # 오메가3 추천 (fe_view 없음)
    assert classify(_u("'오메가3추천' 인기글", False, 17, 10), n_posts=3) == ("스블", "'오메가3추천' 인기글")

def test_classify_스블_주제():  # 콘드로이친
    assert classify(_u("맥스콘드로이친", False, 19, 0), n_posts=3) == ("스블", "맥스콘드로이친")

def test_classify_통검블로그_낱개():  # 고혈압 수치
    assert classify(_u("팬더2주 전Keep에 저장", False, 3, 0), n_posts=1) == ("통검블로그", "팬더2주 전Keep에 저장")

def test_classify_낱개카페_제외():  # 고혈압 예쁜카페 오탐 방지
    assert classify(_u("예쁜카페 예카4주 전", False, 0, 9), n_posts=1) is None

def test_classify_브랜드콘텐츠_제외():
    assert classify(_u("'콘드로이친' 관련 브랜드 콘텐츠", True, 0, 0), n_posts=0) is None

def test_classify_비블로그_제외():
    assert classify(_u("네이버 가격비교", False, 0, 0), n_posts=0) is None
    assert classify(_u("네이버 지식iN 2주 전", False, 0, 0), n_posts=1) is None
