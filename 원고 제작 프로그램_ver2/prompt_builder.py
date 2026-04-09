"""원고 작성기 — 프롬프트 조립"""
import re
import os


def build_product_link(base_link, product_code, date, keyword, medium=""):
    """
    제품 추적 링크 생성.

    형식: base_link?nt_source=blog&nt_medium={medium}&nt_detail={날짜+키워드}&nt_keyword={제품코드}
    """
    if not base_link:
        return ""

    nt_detail = date + keyword.replace(" ", "")
    params = ["nt_source=blog"]

    if medium:
        params.append(f"nt_medium={medium}")

    params.append(f"nt_detail={nt_detail}")

    if product_code:
        params.append(f"nt_keyword={product_code}")

    if "?" not in base_link:
        return base_link + "?" + "&".join(params)
    else:
        return base_link + "&" + "&".join(params)


def _strip_reference_doc_4(instruction_text):
    """
    지침 텍스트에서 [참조 문서 4] 제품별 기본정보 섹션을 제거.
    선택한 제품 정보만 별도로 삽입하기 위함.
    """
    # [참조 문서 4] 시작부터 파일 끝까지 제거
    pattern = r'#\s*\[참조 문서 4\].*'
    result = re.split(pattern, instruction_text, maxsplit=1)
    return result[0].rstrip()


def _load_product_md(product_file_path):
    """제품 MD 파일 전체 내용 읽기"""
    if not product_file_path or not os.path.exists(product_file_path):
        return ""
    with open(product_file_path, 'r', encoding='utf-8') as f:
        return f.read()


def build_prompt(instructions, keyword, product_name="", product_link="",
                 product_file_path=""):
    """
    지침 + 키워드 + 선택 제품 정보 → 최종 프롬프트 조립.

    Args:
        instructions: OrderedDict {파일명: 내용}
        keyword: 작성 키워드
        product_name: 제품명
        product_link: 완성된 제품 링크
        product_file_path: 선택한 제품의 MD 파일 경로
    """
    parts = []

    # 1) 지침 파일들을 순서대로 이어붙임 ([참조 문서 4] 제거)
    for fname, content in instructions.items():
        stripped = _strip_reference_doc_4(content)
        parts.append(stripped)
        parts.append("")

    # 2) 선택한 제품의 정보만 삽입 ([참조 문서 4] 대체)
    product_md = _load_product_md(product_file_path)
    if product_md:
        parts.append("# [참조 문서 4] 제품별 기본정보\n")
        parts.append(product_md)
        parts.append("")

    # 3) 사용자 입력 정보
    parts.append("=== 사용자 입력 ===")
    parts.append(f"키워드: {keyword}")
    if product_name:
        parts.append(f"제품명: {product_name}")
    if product_link:
        parts.append(f"제품 링크: {product_link}")

    return "\n".join(parts)


def parse_phases(full_output):
    """
    Claude 출력에서 [PHASE_A], [PHASE_B], [PHASE_C] 구분자로 분리.

    Returns:
        dict: {"phase_a": str, "phase_b": str, "phase_c": str}
    """
    result = {"phase_a": "", "phase_b": "", "phase_c": ""}

    # [PHASE_A], [PHASE_B], [PHASE_C] 구분자로 분할
    # 구분자가 없으면 전체를 phase_c로 취급
    parts = re.split(r'\[PHASE_([ABC])\]', full_output)

    if len(parts) == 1:
        # 구분자 없음 → 전체가 최종 글
        result["phase_c"] = full_output.strip()
        return result

    # parts: [앞부분, 'A', 내용A, 'B', 내용B, 'C', 내용C]
    for i in range(1, len(parts), 2):
        if i + 1 < len(parts):
            phase_key = parts[i].lower()
            content = parts[i + 1].strip()
            result[f"phase_{phase_key}"] = content

    return result
