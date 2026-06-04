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
