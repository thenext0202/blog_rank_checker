"""원고 작성기 — MD 지침 파일 로더"""
import os
import re
from collections import OrderedDict


def load_instructions(folder_path):
    """
    폴더 내 MD 파일을 파일명 순서로 읽어 반환.

    Returns:
        OrderedDict: {파일명: 내용} (파일명 오름차순 정렬)
    """
    if not folder_path or not os.path.isdir(folder_path):
        return OrderedDict()

    instructions = OrderedDict()
    md_files = sorted([
        f for f in os.listdir(folder_path)
        if f.lower().endswith('.md')
    ])

    for fname in md_files:
        fpath = os.path.join(folder_path, fname)
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                instructions[fname] = f.read()
        except Exception:
            instructions[fname] = f"[읽기 실패: {fname}]"

    return instructions


def extract_block_definitions(instructions):
    """
    지침 내용에서 블록 정의를 추출.

    블록 정의 형식 (MD 지침 내):
        [블록: 블록명] 또는 ## 블록: 블록명

    Returns:
        list: 블록명 리스트 (순서 유지)
    """
    blocks = []
    # 모든 지침 파일에서 블록 정의 탐색
    for content in instructions.values():
        # 패턴 1: [블록: 이름] 또는 [블록:이름]
        found = re.findall(r'\[블록:\s*(.+?)\]', content)
        blocks.extend(found)

        # 패턴 2: ## 블록: 이름
        found = re.findall(r'^##\s*블록:\s*(.+)$', content, re.MULTILINE)
        blocks.extend(found)

    # 중복 제거 (순서 유지)
    seen = set()
    unique = []
    for b in blocks:
        b = b.strip()
        if b not in seen:
            seen.add(b)
            unique.append(b)

    return unique


def parse_manuscript_blocks(manuscript_text, block_names):
    """
    완성 원고에서 블록 구분자를 기준으로 내용을 분리.

    원고 내 구분자 형식: [블록: 블록명]

    Args:
        manuscript_text: 전체 원고 텍스트
        block_names: 블록명 리스트

    Returns:
        OrderedDict: {블록명: 블록내용}
    """
    result = OrderedDict()

    if not block_names:
        result["전체"] = manuscript_text.strip()
        return result

    # 블록 구분자 패턴 생성
    # [블록: 제목], [블록: 서론] 등
    pattern = r'\[블록:\s*(.+?)\]'
    splits = re.split(pattern, manuscript_text)

    # splits: [앞부분, 블록명1, 내용1, 블록명2, 내용2, ...]
    # 첫 번째 요소는 구분자 앞의 텍스트 (보통 비어있음)
    if splits[0].strip():
        result["머리말"] = splits[0].strip()

    for i in range(1, len(splits), 2):
        if i + 1 < len(splits):
            block_name = splits[i].strip()
            block_content = splits[i + 1].strip()
            result[block_name] = block_content

    return result


def get_md_file_list(folder_path):
    """폴더 내 MD 파일 목록 반환 (정렬됨)"""
    if not folder_path or not os.path.isdir(folder_path):
        return []
    return sorted([
        f for f in os.listdir(folder_path)
        if f.lower().endswith('.md')
    ])


def load_product_info_from_folder(folder_path):
    """
    제품 정보 폴더에서 MD 파일을 읽어 제품 목록 반환.

    각 MD 파일의 '기본 정보' 테이블에서 제품명, 기본 링크, 제품코드를 추출.
    테이블 형식:
        | 제품명 | 메디셜 블러드싸이클 |
        | 기본 링크 | https://smartstore.naver.com/... |
        | 제품코드 | bc |

    Returns:
        list of dict: [{"name": 제품명, "base_link": 기본링크, "code": 제품코드, "file": 파일경로}, ...]
    """
    if not folder_path or not os.path.isdir(folder_path):
        return []

    products = []
    md_files = sorted([
        f for f in os.listdir(folder_path)
        if f.lower().endswith('.md')
    ])

    for fname in md_files:
        fpath = os.path.join(folder_path, fname)
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception:
            continue

        product = _parse_product_md(content, fpath)
        if product:
            products.append(product)

    return products


def _parse_product_md(content, fpath):
    """MD 파일에서 제품 정보 추출"""
    info = {"name": "", "base_link": "", "code": "", "file": fpath}

    # 마크다운 테이블에서 항목 추출 (| 항목 | 값 | 형식)
    rows = re.findall(r'\|\s*(.+?)\s*\|\s*(.+?)\s*\|', content)
    for key, value in rows:
        key = key.strip()
        value = value.strip()
        if key == "제품명":
            info["name"] = value
        elif key in ("기본 링크", "기본링크", "상품 링크", "상품링크"):
            info["base_link"] = value
        elif key in ("제품코드", "제품 코드"):
            info["code"] = value

    # 제품명이 없으면 파일명에서 추출 (예: "블러드싸이클 기본정보.md" → "블러드싸이클")
    if not info["name"]:
        basename = os.path.splitext(os.path.basename(fpath))[0]
        info["name"] = basename.replace(" 기본정보", "").strip()

    return info if info["name"] else None
