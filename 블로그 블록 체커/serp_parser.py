# -*- coding: utf-8 -*-
"""네이버 SERP 블록 분류 + 날짜 추출/환산 + 셀 포맷."""
import re
from datetime import date, timedelta

# 날짜 토큰: 상대형(N초/분/시간/일/주/개월 전, 어제/그제) + 절대형(YYYY.MM.DD)
DATE_RE = re.compile(
    r'(\d+초 전|\d+분 전|\d+시간 전|\d+일 전|\d+주 전|\d+개월 전|어제|그제|\d{4}\.\d{2}\.\d{2}\.?)'
)


def extract_dates(text):
    """유닛 텍스트에서 날짜 토큰을 등장 순서대로 모두 추출(중복 허용 = 글 수 반영)."""
    return DATE_RE.findall(text or "")


def normalize_date(token, today):
    """날짜 토큰을 date 객체로 환산. 상대형은 today 기준. 개월은 30일 근사."""
    token = token.strip()
    # 절대형 YYYY.MM.DD
    m = re.match(r'(\d{4})\.(\d{2})\.(\d{2})', token)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if token == "어제":
        return today - timedelta(days=1)
    if token == "그제":
        return today - timedelta(days=2)
    m = re.match(r'(\d+)(초|분|시간|일|주|개월) 전', token)
    if m:
        n = int(m.group(1)); unit = m.group(2)
        if unit in ("초", "분", "시간"):
            return today  # 당일
        if unit == "일":
            return today - timedelta(days=n)
        if unit == "주":
            return today - timedelta(days=7 * n)
        if unit == "개월":
            return today - timedelta(days=30 * n)
    return today  # 해석 불가 시 당일로 폴백(드묾)
