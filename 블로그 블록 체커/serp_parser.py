# -*- coding: utf-8 -*-
"""네이버 SERP 블록 분류 + 날짜 추출/환산 + 셀 포맷."""
import re

# 날짜 토큰: 상대형(N초/분/시간/일/주/개월 전, 어제/그제) + 절대형(YYYY.MM.DD)
DATE_RE = re.compile(
    r'(\d+초 전|\d+분 전|\d+시간 전|\d+일 전|\d+주 전|\d+개월 전|어제|그제|\d{4}\.\d{2}\.\d{2}\.?)'
)


def extract_dates(text):
    """유닛 텍스트에서 날짜 토큰을 등장 순서대로 모두 추출(중복 허용 = 글 수 반영)."""
    return DATE_RE.findall(text or "")
