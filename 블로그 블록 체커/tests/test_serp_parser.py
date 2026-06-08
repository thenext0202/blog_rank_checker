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

def _u(header, fe_view, blog, cafe, ad_blog=0, ad_cafe=0):
    """글 단위 유닛 모사. blog/cafe = 실제 글 수, ad_* = 광고 배지 붙은 글 수."""
    posts = []
    for _ in range(blog):     posts.append({"kind": "blog", "url": "", "date": "", "ad": False})
    for _ in range(cafe):     posts.append({"kind": "cafe", "url": "", "date": "", "ad": False})
    for _ in range(ad_blog):  posts.append({"kind": "blog", "url": "", "date": "", "ad": True})
    for _ in range(ad_cafe):  posts.append({"kind": "cafe", "url": "", "date": "", "ad": True})
    return {"header": header, "fe_view": fe_view, "posts": posts}

def test_classify_인기글():  # 블로그2 + 카페4 (식물성멜라토닌)
    assert classify(_u("인기글", True, 2, 4)) == ("인기글", "인기글")

def test_classify_분야인기글():
    assert classify(_u("건강·의학 인기글", True, 2, 0)) == ("인기글", "건강·의학 인기글")

def test_classify_스블_키워드인기글():  # fe_view 없음 → 스블
    assert classify(_u("'오메가3추천' 인기글", False, 3, 0)) == ("스블", "'오메가3추천' 인기글")

def test_classify_스블_주제():  # 콘드로이친
    assert classify(_u("맥스콘드로이친", False, 3, 0)) == ("스블", "맥스콘드로이친")

def test_classify_스블_카페():  # 글루타치온 인기 카페글
    assert classify(_u("글루타치온 인기 카페글", False, 0, 3)) == ("스블", "글루타치온 인기 카페글")

def test_classify_통검블로그_낱개():
    assert classify(_u("어쩌고 블로그 글", False, 1, 0)) == ("통검블로그", "어쩌고 블로그 글")

def test_classify_낱개카페_제외():  # 카페 낱개는 블로그계열 아님
    assert classify(_u("예쁜카페 예카", False, 0, 1)) is None

def test_classify_외부카드_제외():  # 헤더에 ›(도메인 경로) → 외부 사이트 카드, 스블 아님
    assert classify(_u("하이닥news.hidoc.co.kr›news", False, 1, 0)) is None
    assert classify(_u("11번가search.11st.co.kr›식물성멜라토닌", False, 2, 0)) is None

def test_classify_광고글만_제외():  # 광고 글만 있으면 실제 글 0 → None
    assert classify(_u("어쩌고", False, 0, 0, ad_blog=2)) is None

def test_classify_광고제외후_낱개():  # 블로그2 중 1개 광고 → 실제 1글 → 통검 낱개
    assert classify(_u("어쩌고", False, 1, 0, ad_blog=1)) == ("통검블로그", "어쩌고")

def test_classify_브랜드콘텐츠_제외():
    assert classify(_u("'콘드로이친' 관련 브랜드 콘텐츠", True, 0, 0)) is None

def test_classify_비블로그_제외():
    assert classify(_u("네이버 가격비교", False, 0, 0)) is None
    assert classify(_u("네이버 지식iN", False, 0, 0)) is None


from serp_parser import fmt_popular, fmt_smartblock, fmt_general

T = date(2026, 6, 4)

def test_fmt_popular_분야명():
    blocks = [{"header": "건강·의학 인기글",
               "dates": [date(2026,5,7), date(2026,3,27)]}]
    flag, dates = fmt_popular(blocks, T)
    assert flag == "✅ 건강·의학"
    assert dates == "2건: 5/7(28일 전), 3/27(69일 전)"

def test_fmt_popular_접두어없음():
    blocks = [{"header": "인기글", "dates": [date(2026,6,3)]}]
    flag, dates = fmt_popular(blocks, T)
    assert flag == "✅"
    assert dates == "1건: 6/3(1일 전)"

def test_fmt_popular_없음():
    assert fmt_popular([], T) == ("❌", "")

def test_fmt_smartblock_여러블록_줄바꿈():
    blocks = [
        {"header": "맥스콘드로이친", "dates": [date(2026,5,14), date(2025,9,18)]},
        {"header": "관절엔 콘드로이친", "dates": [date(2026,5,31)]},
    ]
    flag, text = fmt_smartblock(blocks, T)
    assert flag == "✅ 2블록"
    assert text == "맥스콘드로이친(2): 5/14(21일 전), 2025/9/18(259일 전)\n관절엔 콘드로이친(1): 5/31(4일 전)"

def test_fmt_general():
    blocks = [
        {"header": "x", "dates": [date(2026,5,30)]},
        {"header": "y", "dates": [date(2026,5,21)]},
    ]
    flag, dates = fmt_general(blocks, T)
    assert flag == "✅ 2건"
    assert dates == "2건: 5/30(5일 전), 5/21(14일 전)"
