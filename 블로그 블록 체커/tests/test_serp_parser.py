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
