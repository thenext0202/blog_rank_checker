"""공통 유틸 — 단계 간 공유되는 작은 함수들"""
import re


def count_body_chars(text: str) -> int:
    """
    본문 글자수 카운트.
    - HTML 엔티티 제거 (&nbsp;, &amp; 등)
    - 별표 마크업 제거
    - [가-힣A-Za-z0-9]만 카운트

    카운트 제외: 공백, 줄바꿈, 문장부호, 한글 자모 단독,
    한자, 이모지, 전각 영숫자
    """
    text = re.sub(r'&[a-zA-Z]+;', '', text)
    text = re.sub(r'&#\d+;', '', text)
    text = text.replace('*', '')
    return len(re.findall(r'[가-힣A-Za-z0-9]', text))
