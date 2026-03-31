"""
원고 치환기 v1.0 — 참고 원고를 자사 제품 소구점에 맞춰 치환

[흐름]
  1. 레퍼런스 원고 입력 (텍스트 붙여넣기 or DOCX/PDF 파일)
  2. 제품 선택 → 소구점 자동 로드 (기존 원고제작기 시트 공유)
  3. 추가 지시사항 입력
  4. Claude API → 치환 원고 생성
  5. Word 저장

[파일 구조]
  1. 설정/초기화     — import, 경로, 버전
  2. 데이터 로드      — Google Sheets, 파일 읽기
  3. 프롬프트 빌드    — 치환용 프롬프트 조립
  4. Claude API      — API 호출
  5. GUI             — TransformerApp 클래스
  6. 실행 (main)
"""
import os
import sys
import re
import threading
import datetime
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox

try:
    import gspread
    from google.oauth2.service_account import Credentials
    HAS_GSPREAD = True
except ImportError:
    HAS_GSPREAD = False

VERSION = "1.4"

# 제품코드 매핑 (시트 D열 우선, 없으면 하드코딩 폴백)
PRODUCT_CODE_MAP = {
    "hc": "헬리컷", "bc": "블러드싸이클", "gc": "글루코컷",
    "sc": "상어연골환", "pt": "퓨어톤 부스트", "po": "판토오틴",
    "ml": "멜라토닌", "af": "액티플 활성엽산",
}

def _get_product_code(product_name, sheet_data=None):
    """제품명 → 제품코드"""
    if sheet_data and sheet_data.get("product_codes", {}).get(product_name):
        return sheet_data["product_codes"][product_name]
    for code, name in PRODUCT_CODE_MAP.items():
        if name == product_name:
            return code
    return ""


# ╔══════════════════════════════════════════════════════════════╗
# ║  1. 설정 / 초기화                                           ║
# ╚══════════════════════════════════════════════════════════════╝

def base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

# 원고제작기 폴더 (설정 파일 공유)
GENERATOR_DIR = os.path.join(os.path.dirname(base_dir()), "manuscript_generator")
OUTPUT_DIR = os.path.join(base_dir(), "output")
REFERENCES_DIR = os.path.join(GENERATOR_DIR, "references")

os.makedirs(OUTPUT_DIR, exist_ok=True)

# 설정 파일 경로 (원고제작기와 공유, 없으면 로컬)
def _find_file(name):
    local = os.path.join(base_dir(), name)
    if os.path.exists(local):
        return local
    shared = os.path.join(GENERATOR_DIR, name)
    if os.path.exists(shared):
        return shared
    return local  # 없으면 로컬 경로 반환 (저장용)

API_KEY_FILE = _find_file(".api_key")
CRED_FILE = _find_file("credentials.json")
SHEET_CONFIG_FILE = _find_file(".sheet_id")


# ╔══════════════════════════════════════════════════════════════╗
# ║  2. 데이터 로드                                              ║
# ╚══════════════════════════════════════════════════════════════╝

def load_api_key():
    if os.path.exists(API_KEY_FILE):
        with open(API_KEY_FILE, 'r') as f:
            return f.read().strip()
    return ""

def save_api_key(key):
    with open(API_KEY_FILE, 'w') as f:
        f.write(key.strip())

def load_sheet_id():
    if os.path.exists(SHEET_CONFIG_FILE):
        with open(SHEET_CONFIG_FILE, 'r') as f:
            return f.read().strip()
    return ""

def save_sheet_id(sid):
    with open(SHEET_CONFIG_FILE, 'w') as f:
        f.write(sid.strip())

def connect_sheet(sheet_id):
    if not HAS_GSPREAD:
        return None, "gspread 미설치"
    cred = _find_file("credentials.json")
    if not os.path.exists(cred):
        return None, f"credentials.json 없음: {cred}"
    try:
        scope = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(cred, scopes=scope)
        gc = gspread.authorize(creds)
        return gc.open_by_key(sheet_id), None
    except Exception as e:
        return None, f"시트 연결 실패: {e}"

def load_sheet_data(spreadsheet):
    """원고제작기와 동일한 시트에서 필요한 탭만 로드"""
    data = {
        "products": {}, "product_links": {}, "product_codes": {},
        "guidelines": [], "format_instructions": "", "papers": {},
    }

    # 제품소구점
    try:
        ws = spreadsheet.worksheet("제품소구점")
        for row in ws.get_all_values()[1:]:
            if len(row) >= 2 and row[0].strip():
                data["products"][row[0].strip()] = row[1].strip()
                if len(row) >= 3 and row[2].strip():
                    data["product_links"][row[0].strip()] = row[2].strip()
                if len(row) >= 4 and row[3].strip():
                    data["product_codes"][row[0].strip()] = row[3].strip()
    except Exception:
        pass

    # 공통지침
    try:
        ws = spreadsheet.worksheet("공통지침")
        for row in ws.get_all_values()[1:]:
            if len(row) >= 2 and row[1].strip():
                data["guidelines"].append(row[1].strip())
    except Exception:
        pass

    # 서식규칙
    try:
        ws = spreadsheet.worksheet("서식규칙")
        for row in ws.get_all_values()[1:]:
            if len(row) >= 2 and row[0].strip() == "format_instructions":
                data["format_instructions"] = row[1].strip()
                break
    except Exception:
        pass

    # 참고논문
    try:
        ws = spreadsheet.worksheet("참고논문")
        for row in ws.get_all_values()[1:]:
            if len(row) >= 2 and row[0].strip() and row[1].strip():
                pname = row[0].strip()
                parts = [f"연구명: {row[1].strip()}"]
                if len(row) >= 3 and row[2].strip():
                    parts.append(f"출처: {row[2].strip()}")
                if len(row) >= 4 and row[3].strip():
                    parts.append(f"대상: {row[3].strip()}")
                if len(row) >= 5 and row[4].strip():
                    parts.append(f"핵심 결과: {row[4].strip()}")
                if len(row) >= 6 and row[5].strip():
                    parts.append(f"수치: {row[5].strip()}")
                if pname not in data["papers"]:
                    data["papers"][pname] = []
                data["papers"][pname].append("\n".join(parts))
    except Exception:
        pass

    return data

def read_file_content(fpath):
    ext = os.path.splitext(fpath)[1].lower()
    try:
        if ext in ('.txt', '.md', '.csv'):
            with open(fpath, 'r', encoding='utf-8') as f:
                return f.read()
        elif ext == '.docx':
            from docx import Document
            doc = Document(fpath)
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        elif ext == '.pdf':
            try:
                import fitz
                doc = fitz.open(fpath)
                parts = [page.get_text() for page in doc]
                doc.close()
                return "\n".join(parts)
            except ImportError:
                return f"[PDF - PyMuPDF 미설치: {os.path.basename(fpath)}]"
    except Exception as e:
        return f"[읽기 오류: {e}]"
    return ""

# 참고자료 로드 (references/ 폴더)
VALID_REF_EXTS = ('.txt', '.md', '.csv', '.docx', '.pdf')

def _load_refs_from_dir(dirpath, prefix=""):
    refs = {}
    if not os.path.exists(dirpath):
        return refs
    for fname in os.listdir(dirpath):
        fpath = os.path.join(dirpath, fname)
        if os.path.isfile(fpath) and os.path.splitext(fname)[1].lower() in VALID_REF_EXTS:
            display_name = f"[{prefix}] {fname}" if prefix else fname
            refs[display_name] = read_file_content(fpath)
    return refs

def load_refs_for_product(product_name=""):
    refs = {}
    common_dir = os.path.join(REFERENCES_DIR, "공통")
    refs.update(_load_refs_from_dir(common_dir, "공통"))
    if product_name:
        product_dir = os.path.join(REFERENCES_DIR, product_name)
        refs.update(_load_refs_from_dir(product_dir, product_name))
    return refs


# ╔══════════════════════════════════════════════════════════════╗
# ║  3. 프롬프트 빌드 (치환용)                                   ║
# ╚══════════════════════════════════════════════════════════════╝

def build_transform_prompt(
    sheet_data, product_name, reference_text, extra_instructions,
    tone, font_size, alignment, quote_num,
    color_positive, color_negative, highlight_emphasis,
    color_product, highlight_product, emphasis_fontsize,
    product_link="", include_toc=True, title_repeat=True,
    selected_refs=None,
):
    """레퍼런스 원고 치환을 위한 프롬프트 조립"""
    parts = []

    # 레퍼런스 원고 글자수 계산 (분량 기준)
    ref_body_chars = 0
    for line in reference_text.split('\n'):
        s = line.strip()
        if s and not s.startswith('ㄴ') and not re.match(r'^\d{1,2}$', s):
            ref_body_chars += len(s)

    # 1) 역할 및 핵심 지시
    parts.append("당신은 블로그 원고 치환 전문가입니다.")
    parts.append("")
    parts.append("===== 핵심 작업 =====")
    parts.append("아래 '레퍼런스 원고'의 타사 제품 내용을 자사 제품으로 치환해주세요.")
    parts.append("이것은 '새 원고 작성'이 아니라 '기존 원고의 제품 부분만 교체'하는 작업입니다.")
    parts.append("")
    parts.append("[치환 규칙 — 반드시 준수]")
    parts.append("1. 레퍼런스 원고의 톤, 문체, 구조, 줄 끊기 방식, 글 전체의 흐름을 최대한 유지")
    parts.append("2. 타사 제품명/브랜드 → 자사 제품명으로 교체")
    parts.append("3. 타사 제품의 특징/장점/효과 → 자사 제품의 소구점으로 자연스럽게 치환")
    parts.append("4. 구체적인 수치(기간, 용량, 횟수 등)는 자사 제품 소구점에 맞게 변형")
    parts.append("5. 개인 경험담 부분은 자사 제품 사용 경험으로 자연스럽게 변형 (상황은 자사 제품에 맞게)")
    parts.append("6. '치환했다'는 느낌이 나지 않도록 자연스럽게 — 처음부터 이 제품으로 쓴 것처럼")
    parts.append("7. 레퍼런스에 제품 링크가 있으면 자사 제품 링크로 교체")
    parts.append("8. 이미지 번호(00, 01, 02...)는 레퍼런스와 동일한 위치/개수로 유지")
    parts.append("9. 해시태그가 있으면 자사 제품에 맞게 변경")
    parts.append("")
    parts.append("[정보 깊이 — 레퍼런스와 동일하게 유지]")
    parts.append("- 각 섹션의 정보 깊이(전문성 수준)를 레퍼런스와 똑같이 맞추세요")
    parts.append("- 레퍼런스가 성분을 '한 줄 요약'으로 가볍게 썼으면 → 치환도 한 줄 요약으로")
    parts.append("- 레퍼런스가 일상적 숫자(칼로리, 가격 등)를 썼으면 → 의학 수치(mg/dL 등)로 바꾸지 말고 같은 수준의 일상 숫자로")
    parts.append("- 레퍼런스가 '맛있었다, 식감이 좋았다' 같은 감각 후기면 → 치환도 체감 후기로 (효능 분석 X)")
    parts.append("- 레퍼런스의 글 무게감(가벼운 후기 vs 진지한 정보글)을 그대로 유지하세요")
    parts.append("")
    parts.append("[절대 금지 사항]")
    parts.append("- 레퍼런스 원고에 없는 새로운 문단, 설명, 성분 분석을 추가하지 마세요")
    parts.append("- 레퍼런스보다 성분/효능을 더 깊이 파고들지 마세요")
    parts.append("- 레퍼런스에 없는 논문/연구를 새로 인용하지 마세요")
    parts.append("- 소구점에 있다고 해서 레퍼런스에 없는 내용을 끼워넣지 마세요")
    parts.append("- 소구점은 '치환할 때 참고하는 정보'이지, '전부 넣어야 할 내용'이 아닙니다")
    parts.append("- 레퍼런스가 가벼운 후기인데 치환 결과가 전문 정보글이 되면 안 됩니다")
    parts.append("")
    parts.append(f"[분량 기준] 레퍼런스 원고 본문: 약 {ref_body_chars:,}자")
    parts.append(f"치환 결과도 ±15% 이내로 맞춰주세요 ({int(ref_body_chars*0.85):,}~{int(ref_body_chars*1.15):,}자).")
    parts.append("레퍼런스보다 길어지는 것은 새 내용을 추가했다는 뜻이므로 특히 주의하세요.")

    # 2) 레퍼런스 원고
    parts.append("\n\n===== 레퍼런스 원고 =====")
    parts.append("아래 원고의 구조와 톤을 그대로 따르되, 제품 관련 내용만 자사 제품으로 치환하세요.")
    parts.append(f"\n{reference_text}")

    # 3) 자사 제품 정보
    product_guide = sheet_data.get("products", {}).get(product_name, "")
    parts.append("\n\n===== 자사 제품 정보 =====")
    parts.append(f"제품명: {product_name}")
    if product_guide:
        parts.append(f"소구점/가이드:\n{product_guide}")
    if product_link:
        parts.append(f"상품 링크: {product_link}")

    # 4) 공통지침 — 치환 관련 항목만 선별
    guidelines = sheet_data.get("guidelines", [])
    if guidelines:
        parts.append("\n\n===== 참고 지침 (치환 시 유의) =====")
        parts.append("아래는 원고 작성 시 공통 지침입니다. 치환 작업에 해당하는 항목만 참고하세요.")
        parts.append("(새 내용을 추가하라는 의미가 아닙니다. 레퍼런스 원고에 이미 있는 내용이 아래 지침에 위배되면 수정하세요.)")
        for i, g in enumerate(guidelines, 1):
            parts.append(f"{i}. {g}")

    # 5) 참고자료 + 논문 — 레퍼런스에 연구 인용이 있을 때만 교체용으로 제공
    if selected_refs is None:
        selected_refs = {}
    papers = sheet_data.get("papers", {}).get(product_name, [])
    has_refs = bool(selected_refs) or bool(papers)
    if has_refs:
        parts.append("\n\n===== 참고자료 (치환용) =====")
        parts.append("레퍼런스 원고에 이미 논문/연구 인용이 있는 경우, 아래 자사 제품 관련 논문으로 교체하세요.")
        parts.append("레퍼런스 원고에 연구 인용이 없다면, 아래 논문을 새로 추가하지 마세요.")
        parts.append("레퍼런스에 있는 인용 개수와 깊이를 그대로 유지하세요.")
        for fname, content in selected_refs.items():
            if len(content) > 8000:
                content = content[:8000] + "\n... (이하 생략)"
            parts.append(f"\n--- {fname} ---\n{content}")
        if papers:
            parts.append("\n--- 참고 논문 (스프레드시트) ---")
            for i, paper in enumerate(papers, 1):
                parts.append(f"\n[논문 {i}]\n{paper}")

    # 6) 서식 규칙
    fmt_template = sheet_data.get("format_instructions") or ""
    if fmt_template:
        link_text = product_link if product_link else "(제품 링크)"
        toc_instruction = "글 서두에 목차를 포함" if include_toc else "목차 없이 바로 본문 시작"
        title_repeat_instruction = "원고 끝에 제목을 3번 반복" if title_repeat else "제목 반복 없음"
        hl_emphasis = highlight_emphasis if highlight_emphasis != "없음" else "글꼴 두껍게"
        hl_product = highlight_product if highlight_product != "없음" else "글꼴 두껍게"
        try:
            parts.append(fmt_template.format(
                font_size=font_size,
                align_text=alignment,
                quote_num=quote_num,
                toc_instruction=toc_instruction,
                product_link=link_text,
                color_positive=color_positive,
                color_negative=color_negative,
                highlight_emphasis=hl_emphasis,
                color_product=color_product,
                highlight_product=hl_product,
                title_repeat=title_repeat_instruction,
                emphasis_fontsize=emphasis_fontsize,
            ))
        except KeyError as e:
            parts.append(f"\n\n[서식규칙 오류: 알 수 없는 플레이스홀더 {e}]")

    parts.append(f"\n[중요] 'ㄴ' 서식 지시에서 글자 크기는 반드시 11, 13, 15, 16, 19, 24, 28 중 하나만 사용하세요.")
    parts.append(f"[중요] 기본 글자 크기는 {font_size}입니다. 'ㄴ 글자 크기 {font_size}'처럼 기본 크기와 같은 값을 지시하지 마세요.")

    # 7) 추가 지시사항
    if extra_instructions:
        parts.append(f"\n\n===== 추가 지시사항 =====\n{extra_instructions}")

    # 8) 최종 체크리스트 — 치환 품질 확인용
    parts.append("\n\n===== 최종 체크리스트 =====")
    parts.append("치환 완료 후, 아래 항목을 반드시 확인하세요:")
    parts.append(f"  □ 1. 본문 글자수가 레퍼런스(약 {ref_body_chars:,}자) 대비 ±15% 이내인가?")
    parts.append("  □ 2. 레퍼런스에 없는 새로운 문단이나 성분 설명을 추가하지 않았는가?")
    parts.append("  □ 3. 타사 제품명/브랜드가 남아있지 않은가?")
    parts.append("  □ 4. 자사 제품의 소구점과 모순되는 내용이 없는가?")
    parts.append("  □ 5. 이미지 번호 위치/개수가 레퍼런스와 동일한가?")
    parts.append("  □ 6. 레퍼런스의 톤과 자연스러움을 유지하고 있는가?")

    return "\n".join(parts)


# ╔══════════════════════════════════════════════════════════════╗
# ║  4. Claude API                                              ║
# ╚══════════════════════════════════════════════════════════════╝

# ╔══════════════════════════════════════════════════════════════╗
# ║  3.5 검수 로직 (규칙 기반)                                    ║
# ╚══════════════════════════════════════════════════════════════╝

# 유효한 서식 지시 패턴들
_VALID_FORMAT_KEYS = [
    "글자 크기", "글자크기", "정렬", "가운데정렬", "왼쪽정렬", "오른쪽정렬",
    "글꼴 두껍게", "글꼴 색깔", "인용구", "형광펜", "취소선", "밑줄",
]

def _extract_image_numbers(text):
    """본문에서 이미지 번호(숫자만 있는 줄) 추출"""
    nums = []
    for line in text.split('\n'):
        stripped = line.strip()
        if re.match(r'^\d{1,2}$', stripped):
            nums.append(int(stripped))
    return nums

def _extract_format_lines(text):
    """ㄴ 서식 지시 줄 추출"""
    lines = []
    for line in text.split('\n'):
        stripped = line.strip()
        if stripped.startswith('ㄴ'):
            lines.append(stripped)
    return lines

def _count_quotes(text):
    """인용구 개수 세기 (ㄴ 인용구 패턴)"""
    count = 0
    for line in text.split('\n'):
        stripped = line.strip()
        if re.match(r'^ㄴ\s*인용구', stripped):
            count += 1
    return count

def _has_toc(text):
    """목차 존재 여부 (초반 30줄 내 목차 패턴)"""
    lines = text.split('\n')[:30]
    for line in lines:
        stripped = line.strip()
        # "목차" 단어 또는 순번+제목 패턴이 3개 이상
        if '목차' in stripped:
            return True
    # 1. 2. 3. 패턴이 연속 3개 이상이면 목차로 간주
    numbered = 0
    for line in lines:
        if re.match(r'^\d+[\.\)]\s+.+', line.strip()):
            numbered += 1
        else:
            if numbered >= 3:
                return True
            numbered = 0
    return numbered >= 3

def run_inspection(result_text, ref_text, product_name, settings):
    """
    치환 결과 검수. settings = {quote_num, include_toc, product_link, font_size}
    반환: [(항목명, 상태, 설명), ...] 상태: "pass"/"fail"/"warn"
    """
    items = []

    # 1) 글자수
    body_chars = 0
    for line in result_text.split('\n'):
        s = line.strip()
        if not s or s.startswith('ㄴ') or re.match(r'^\d{1,2}$', s):
            continue
        body_chars += len(s)

    if body_chars == 0:
        items.append(("글자수", "fail", "본문 없음"))
    elif body_chars < 800:
        items.append(("글자수", "warn", f"{body_chars:,}자 — 800자 미만 (짧음)"))
    elif body_chars > 5000:
        items.append(("글자수", "warn", f"{body_chars:,}자 — 5,000자 초과 (긺)"))
    else:
        items.append(("글자수", "pass", f"{body_chars:,}자"))

    # 2) 이미지 번호
    ref_imgs = _extract_image_numbers(ref_text)
    res_imgs = _extract_image_numbers(result_text)
    if ref_imgs:
        if len(res_imgs) == len(ref_imgs):
            # 연속성 체크
            expected = list(range(min(res_imgs), min(res_imgs) + len(res_imgs))) if res_imgs else []
            if res_imgs == expected:
                items.append(("이미지 번호", "pass", f"{len(res_imgs)}개 (레퍼런스 동일)"))
            else:
                items.append(("이미지 번호", "warn", f"{len(res_imgs)}개 — 번호 불연속: {res_imgs}"))
        else:
            items.append(("이미지 번호", "fail",
                          f"레퍼런스 {len(ref_imgs)}개 → 결과 {len(res_imgs)}개 (불일치)"))
    else:
        if res_imgs:
            items.append(("이미지 번호", "warn", f"레퍼런스에 없는 이미지 {len(res_imgs)}개 발견"))
        else:
            items.append(("이미지 번호", "pass", "이미지 없음 (레퍼런스 동일)"))

    # 3) 서식 지시(ㄴ) 유효성
    fmt_lines = _extract_format_lines(result_text)
    invalid_lines = []
    valid_sizes = {"11", "13", "15", "16", "19", "24", "28"}
    base_size = settings.get("font_size", "16")
    base_size_warns = []

    for fl in fmt_lines:
        body = fl[1:].strip()  # ㄴ 제거
        # 글자 크기 값 검증
        size_match = re.search(r'글자\s*크기\s*(\d+)', body)
        if size_match:
            size_val = size_match.group(1)
            if size_val not in valid_sizes:
                invalid_lines.append(f"'{fl}' → 크기 {size_val} 유효하지 않음")
            elif size_val == base_size:
                base_size_warns.append(f"'{fl}' → 기본 크기({base_size})와 동일")

    if invalid_lines:
        items.append(("서식 지시", "fail", f"유효하지 않은 {len(invalid_lines)}건: {invalid_lines[0]}"))
    elif base_size_warns:
        items.append(("서식 지시", "warn", f"기본 크기 지시 {len(base_size_warns)}건 (불필요)"))
    else:
        items.append(("서식 지시", "pass", f"ㄴ {len(fmt_lines)}줄 정상"))

    # 4) 제품명 포함
    if product_name:
        count = result_text.count(product_name)
        if count == 0:
            items.append(("제품명", "fail", f"'{product_name}' 미포함"))
        elif count < 3:
            items.append(("제품명", "warn", f"'{product_name}' {count}회 (적음)"))
        else:
            items.append(("제품명", "pass", f"'{product_name}' {count}회"))

    # 5) 타사 제품명 잔존 체크
    if ref_text and product_name:
        # 레퍼런스에서 자주 등장하는 고유명사 후보 추출 (제품명과 다른 것)
        # 간단 휴리스틱: PRODUCT_CODE_MAP의 제품명 중 레퍼런스에 있고 치환 결과에도 남아있는 것
        leftover = []
        for code, name in PRODUCT_CODE_MAP.items():
            if name != product_name and name in ref_text and name in result_text:
                leftover.append(name)
        if leftover:
            items.append(("타사 잔존", "fail", f"치환 안 된 제품명: {', '.join(leftover)}"))
        else:
            items.append(("타사 잔존", "pass", "타사 제품명 없음"))

    # 6) 상품 링크
    product_link = settings.get("product_link", "")
    if product_link:
        if product_link in result_text or "http" in result_text:
            items.append(("상품 링크", "pass", "링크 포함됨"))
        else:
            items.append(("상품 링크", "fail", "링크 미포함"))
    else:
        items.append(("상품 링크", "warn", "링크 미설정"))

    # 7) 인용구 수
    target_quotes = int(settings.get("quote_num", "3"))
    actual_quotes = _count_quotes(result_text)
    diff = abs(actual_quotes - target_quotes)
    if diff == 0:
        items.append(("인용구", "pass", f"{actual_quotes}개 (설정과 일치)"))
    elif diff <= 1:
        items.append(("인용구", "warn", f"{actual_quotes}개 (설정: {target_quotes}개, ±1)"))
    else:
        items.append(("인용구", "fail", f"{actual_quotes}개 (설정: {target_quotes}개, 차이 {diff})"))

    # 8) 목차
    if settings.get("include_toc", True):
        if _has_toc(result_text):
            items.append(("목차", "pass", "목차 있음"))
        else:
            items.append(("목차", "fail", "목차 옵션 ON인데 목차 없음"))
    else:
        if _has_toc(result_text):
            items.append(("목차", "warn", "목차 옵션 OFF인데 목차 있음"))
        else:
            items.append(("목차", "pass", "목차 없음 (설정과 일치)"))

    return items


DEFAULT_REVIEW_CRITERIA = """## 1. 부정 표현 감지
자사 제품을 홍보하는 원고에서 마이너스가 되는 표현을 찾아주세요.
- 제품의 단점, 부작용, 불만, 실망 등 부정적 경험 서술
- 고객센터 불만, 대응 미흡 등 브랜드 이미지 훼손 표현
- '솔직히 아쉬운 점', '단점도 있었다' 같은 부정 프레임
- 경쟁사 대비 열등한 것처럼 읽힐 수 있는 표현
※ 서식 지시(ㄴ으로 시작하는 줄)와 이미지 번호(숫자만 있는 줄)는 무시하세요.

## 2. 소구점 일치 검증
원고 내용이 위 제품 소구점과 맞는지 확인해주세요.
- 소구점에 없는 효능/효과를 과장하거나 지어낸 부분
- 소구점과 모순되는 내용
- 소구점 중 원고에 잘 반영된 것과 빠진 것

## 3. 복용법/사용법 정확성
제품 소구점에 명시된 복용법, 용량, 타이밍 등과 원고 내용이 일치하는지 확인해주세요.
- 복용 시간(아침/저녁/식전/식후 등)이 소구점과 다른 경우
- 용량, 섭취 방법이 다른 경우
- 소구점에 복용법이 없으면 이 항목은 '확인 불가'로 표시""".strip()


def build_content_review_prompt(result_text, product_name, product_guide, custom_criteria=None):
    """AI 내용 검수 프롬프트 — 부정표현, 소구점 일치, 복용법 검증"""
    criteria = custom_criteria.strip() if custom_criteria and custom_criteria.strip() else DEFAULT_REVIEW_CRITERIA

    parts = []
    parts.append("당신은 마케팅 원고 품질 검수 전문가입니다.")
    parts.append("")
    parts.append("아래 '치환 원고'는 자사 제품을 홍보하기 위한 블로그 원고입니다.")
    parts.append("이 원고가 홍보 목적에 부합하는지 검수해주세요.")
    parts.append("")

    parts.append("===== 검수 대상 원고 =====")
    parts.append(result_text)
    parts.append("")

    parts.append("===== 자사 제품 정보 =====")
    parts.append(f"제품명: {product_name}")
    if product_guide:
        parts.append(f"소구점/가이드:\n{product_guide}")
    parts.append("")

    parts.append("===== 검수 항목 =====")
    parts.append("")
    parts.append(criteria)
    parts.append("")

    parts.append("===== 출력 형식 =====")
    parts.append("아래 형식을 정확히 따라주세요. 각 항목마다 문제가 없으면 '없음'으로 표시.")
    parts.append("")
    parts.append("[부정 표현]")
    parts.append("상태: 발견 N건 / 없음")
    parts.append("1. (해당 문장 인용) → (문제 이유)")
    parts.append("2. ...")
    parts.append("")
    parts.append("[소구점 일치]")
    parts.append("상태: 일치 / 부분 일치 / 불일치")
    parts.append("- 잘 반영됨: ...")
    parts.append("- 누락됨: ...")
    parts.append("- 문제: ...")
    parts.append("")
    parts.append("[복용법]")
    parts.append("상태: 정확 / 오류 N건 / 확인 불가")
    parts.append("1. (해당 문장 인용) → (올바른 정보)")
    parts.append("")
    parts.append("[종합 판정]")
    parts.append("PASS / WARN / FAIL")
    parts.append("(한 줄 요약)")

    return "\n".join(parts)


def build_fix_prompt(original_text, review_result, product_name, product_guide, user_instruction=""):
    """검수 결과를 반영하여 원고를 수정하는 프롬프트"""
    parts = []
    parts.append("당신은 마케팅 원고 수정 전문가입니다.")
    parts.append("")
    parts.append("아래 '원본 원고'에 대해 AI 검수 결과가 나왔습니다.")
    parts.append("검수에서 지적된 문제점을 수정한 원고를 작성해주세요.")
    parts.append("")
    parts.append("===== 수정 규칙 =====")
    parts.append("- 검수에서 지적된 부분만 최소한으로 수정")
    parts.append("- 원고의 전체 구조, 톤, 서식 지시(ㄴ으로 시작하는 줄)는 그대로 유지")
    parts.append("- 이미지 번호(숫자만 있는 줄)는 절대 변경하지 않음")
    parts.append("- 부정 표현은 긍정/중립 표현으로 자연스럽게 교체")
    parts.append("- 소구점에 없는 내용은 삭제하거나 소구점에 맞게 수정")
    parts.append("- 복용법 오류는 소구점 정보에 맞게 정정")
    parts.append("- 수정하지 않아도 되는 부분은 원문 그대로 유지")
    if user_instruction:
        parts.append(f"- 추가 지시: {user_instruction}")
    parts.append("")

    parts.append("===== 자사 제품 정보 =====")
    parts.append(f"제품명: {product_name}")
    if product_guide:
        parts.append(f"소구점/가이드:\n{product_guide}")
    parts.append("")

    parts.append("===== AI 검수 결과 =====")
    parts.append(review_result)
    parts.append("")

    parts.append("===== 원본 원고 =====")
    parts.append(original_text)
    parts.append("")

    parts.append("===== 출력 =====")
    parts.append("수정된 원고 전체를 출력해주세요. 설명 없이 원고만 출력.")

    return "\n".join(parts)


def parse_content_review(response):
    """AI 검수 응답 파싱 → (부정표현 상태, 소구점 상태, 복용법 상태, 종합, 전체 텍스트)"""
    result = {
        "부정 표현": ("warn", "파싱 실패"),
        "소구점": ("warn", "파싱 실패"),
        "복용법": ("warn", "파싱 실패"),
        "종합": ("warn", "파싱 실패"),
    }

    # 부정 표현
    m = re.search(r'\[부정\s*표현\]\s*\n상태:\s*(.+)', response)
    if m:
        status_text = m.group(1).strip()
        if '없음' in status_text:
            result["부정 표현"] = ("pass", status_text)
        else:
            result["부정 표현"] = ("fail", status_text)

    # 소구점 일치
    m = re.search(r'\[소구점\s*일치\]\s*\n상태:\s*(.+)', response)
    if m:
        status_text = m.group(1).strip()
        if '일치' == status_text.strip() or status_text.startswith('일치'):
            result["소구점"] = ("pass", status_text)
        elif '부분' in status_text:
            result["소구점"] = ("warn", status_text)
        else:
            result["소구점"] = ("fail", status_text)

    # 복용법
    m = re.search(r'\[복용법\]\s*\n상태:\s*(.+)', response)
    if m:
        status_text = m.group(1).strip()
        if '정확' in status_text:
            result["복용법"] = ("pass", status_text)
        elif '확인 불가' in status_text:
            result["복용법"] = ("warn", status_text)
        else:
            result["복용법"] = ("fail", status_text)

    # 종합
    m = re.search(r'\[종합\s*판정\]\s*\n(PASS|WARN|FAIL)', response)
    if m:
        verdict = m.group(1)
        # 다음 줄 = 한줄 요약
        after = response[m.end():]
        summary_line = after.strip().split('\n')[0].strip() if after.strip() else ""
        status_map = {"PASS": "pass", "WARN": "warn", "FAIL": "fail"}
        result["종합"] = (status_map.get(verdict, "warn"), f"{verdict} — {summary_line}")

    return result


def call_claude_api(api_key, prompt, on_complete, on_error, max_tokens=8192,
                    cancel_flag=None, on_stream=None):
    """Claude API 호출 (스트리밍). cancel_flag: threading.Event — set()하면 중단."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        collected = []
        with client.messages.stream(
            model="claude-sonnet-4-20250514",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}]
        ) as stream:
            for text in stream.text_stream:
                if cancel_flag and cancel_flag.is_set():
                    # 중단 요청 — 지금까지 수집한 텍스트 반환
                    on_complete("".join(collected) + "\n\n[사용자 중단]")
                    return
                collected.append(text)
                if on_stream:
                    on_stream(text)
        on_complete("".join(collected))
    except Exception as e:
        on_error(str(e))


# ╔══════════════════════════════════════════════════════════════╗
# ║  5. GUI                                                     ║
# ╚══════════════════════════════════════════════════════════════╝

class TransformerApp:

    THEME = {
        "bg": "#dcdad5",
        "fg": "#000000",
        "accent": "#4a6984",
        "accent2": "#2e7d32",
        "warn": "#c62828",
        "surface": "#dcdad5",
        "text_bg": "#ffffff",
        "text_fg": "#000000",
        "sash": "#dcdad5",
        "inspect_bg": "#333333",
        "inspect_chars": "#66cc66",
    }

    def __init__(self, root):
        self.root = root
        self.root.title(f"원고 치환기 v{VERSION}")
        self.root.geometry("1400x960")
        self.root.minsize(1100, 750)
        self.root.configure(bg=self.THEME["bg"])

        self.sheet_data = {"products": {}, "product_codes": {}, "guidelines": [], "format_instructions": "", "papers": {}}
        self.reference_files = {}
        self.is_generating = False
        self.cancel_flag = None
        self._preview_backup = ""
        self.spreadsheet = None

        self._setup_styles()
        self._build_ui()
        self._setup_traces()
        self._bind_shortcuts()
        self._init_load()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        if self.is_generating:
            if not messagebox.askyesno("생성 중", "치환이 진행 중입니다.\n정말 종료하시겠습니까?"):
                return
        self.root.destroy()

    def _setup_styles(self):
        s = ttk.Style()
        s.theme_use('clam')
        s.configure('.', font=('맑은 고딕', 9))
        s.configure('TLabelframe.Label', font=('맑은 고딕', 10, 'bold'))
        s.configure('TNotebook.Tab', padding=[14, 5], font=('맑은 고딕', 10))
        s.configure('Generate.TButton', font=('맑은 고딕', 11, 'bold'), padding=9)
        s.configure('Refresh.TButton', font=('맑은 고딕', 9, 'bold'))

    def _setup_traces(self):
        self.product_var.trace_add('write', lambda *a: self._on_product_changed())
        self.date_var.trace_add('write', lambda *a: self._update_product_link())
        self.nt_medium_var.trace_add('write', lambda *a: self._update_product_link())
        self.keyword_var.trace_add('write', lambda *a: self._update_product_link())

    def _bind_shortcuts(self):
        self.root.bind('<Control-g>', lambda e: self._on_generate())
        self.root.bind('<Control-G>', lambda e: self._on_generate())
        self.root.bind('<Control-s>', lambda e: self._on_save_docx())
        self.root.bind('<Control-S>', lambda e: self._on_save_docx())
        self.root.bind('<Control-p>', lambda e: self._on_preview())
        self.root.bind('<Control-P>', lambda e: self._on_preview())
        self.root.bind('<F5>', lambda e: self._on_refresh_sheet())
        self.root.bind('<F6>', lambda e: self._run_inspection())
        self.root.bind('<F7>', lambda e: self._run_ai_inspection())
        self.root.bind('<Escape>', lambda e: self._on_stop())

    # ── UI 빌드 ──
    def _build_ui(self):
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # ═══ 탭1: 원고 치환 ═══
        tab1 = ttk.Frame(notebook)
        notebook.add(tab1, text="  원고 치환  ")

        paned = tk.PanedWindow(tab1, orient=tk.VERTICAL, sashwidth=8,
                               sashrelief=tk.RAISED, bg=self.THEME["sash"], bd=1)
        paned.pack(fill=tk.BOTH, expand=True)

        # 상단: 설정 (스크롤)
        top_pane = ttk.Frame(paned)
        paned.add(top_pane, stretch="never", minsize=200)

        canvas = tk.Canvas(top_pane, highlightthickness=0, bg=self.THEME["bg"])
        scrollbar = ttk.Scrollbar(top_pane, orient=tk.VERTICAL, command=canvas.yview)
        self.scroll_frame = ttk.Frame(canvas)
        self.scroll_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        self._settings_canvas = canvas
        self._settings_top_pane = top_pane

        def _on_mousewheel(event):
            """마우스 위치 기반 스크롤 — 설정 영역이면 캔버스, 아니면 기본 동작"""
            x, y = event.widget.winfo_pointerxy()
            tp_x = top_pane.winfo_rootx()
            tp_y = top_pane.winfo_rooty()
            tp_w = top_pane.winfo_width()
            tp_h = top_pane.winfo_height()
            if tp_x <= x <= tp_x + tp_w and tp_y <= y <= tp_y + tp_h:
                # 설정 영역 위 → 캔버스 스크롤
                canvas.yview_scroll(int(-1*(event.delta/120)), "units")
                return "break"
            # 그 외 → 이벤트 전파 (ScrolledText 등 자체 스크롤)

        self.root.bind_all("<MouseWheel>", _on_mousewheel)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas.find_all()[0], width=e.width))

        sc = self.scroll_frame

        # ── 기본 설정 ──
        row1 = ttk.LabelFrame(sc, text="기본 설정", padding=10)
        row1.pack(fill=tk.X, padx=10, pady=(10, 5))

        # 행 0: 제품, 작가명, 날짜
        ttk.Label(row1, text="제품:").grid(row=0, column=0, sticky='e', padx=(0, 5))
        self.product_var = tk.StringVar()
        self.product_combo = ttk.Combobox(row1, textvariable=self.product_var, state='readonly', width=18)
        self.product_combo.grid(row=0, column=1, sticky='w', padx=(0, 15))

        ttk.Label(row1, text="작가명:").grid(row=0, column=2, sticky='e', padx=(0, 5))
        self.author_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.author_var, width=12).grid(row=0, column=3, sticky='w', padx=(0, 15))

        ttk.Label(row1, text="날짜:").grid(row=0, column=4, sticky='e', padx=(0, 5))
        self.date_var = tk.StringVar(value=datetime.datetime.now().strftime("%y%m%d"))
        ttk.Entry(row1, textvariable=self.date_var, width=10).grid(row=0, column=5, sticky='w', padx=(0, 5))
        ttk.Label(row1, text="(예: 260327)", font=('맑은 고딕', 8)).grid(row=0, column=6, sticky='w')

        # 행 1: 메인 키워드, nt_medium
        ttk.Label(row1, text="메인 키워드:").grid(row=1, column=0, sticky='e', padx=(0, 5), pady=(5, 0))
        self.keyword_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.keyword_var, width=30).grid(row=1, column=1, columnspan=2, sticky='w', padx=(0, 15), pady=(5, 0))

        ttk.Label(row1, text="nt_medium:").grid(row=1, column=3, sticky='e', padx=(0, 5), pady=(5, 0))
        self.nt_medium_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.nt_medium_var, width=10).grid(row=1, column=4, sticky='w', pady=(5, 0))

        # 행 2: 상품 링크 (자동 생성)
        ttk.Label(row1, text="상품 링크:").grid(row=2, column=0, sticky='e', padx=(0, 5), pady=(5, 0))
        self.link_entry = ttk.Entry(row1, width=90)
        self.link_entry.grid(row=2, column=1, columnspan=5, sticky='w', padx=(0, 5), pady=(5, 0))
        ttk.Label(row1, text="(자동 생성)", font=('맑은 고딕', 8)).grid(row=2, column=6, sticky='w', pady=(5, 0))

        # ── 레퍼런스 원고 입력 ──
        ref_frame = ttk.LabelFrame(sc, text="레퍼런스 원고 (붙여넣기 or 파일 첨부)", padding=10)
        ref_frame.pack(fill=tk.X, padx=10, pady=5)

        # 파일 첨부 버튼
        file_bar = ttk.Frame(ref_frame)
        file_bar.pack(fill=tk.X, pady=(0, 5))
        ttk.Button(file_bar, text="파일 열기 (DOCX/PDF/TXT)", command=self._on_load_file).pack(side=tk.LEFT)
        self._file_label = tk.StringVar(value="파일 미선택")
        ttk.Label(file_bar, textvariable=self._file_label, font=('맑은 고딕', 8),
                  foreground='#666').pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(file_bar, text="초기화", command=self._on_clear_ref).pack(side=tk.RIGHT)

        self.ref_text = scrolledtext.ScrolledText(ref_frame, wrap=tk.WORD, font=('맑은 고딕', 10), height=10,
                                                   bg=self.THEME["text_bg"], fg=self.THEME["text_fg"])
        self.ref_text.pack(fill=tk.BOTH, expand=True)

        # ── 서식 옵션 ──
        row2 = ttk.LabelFrame(sc, text="서식 옵션", padding=10)
        row2.pack(fill=tk.X, padx=10, pady=5)

        col = 0
        ttk.Label(row2, text="문체:").grid(row=0, column=col, sticky='e', padx=(0, 5)); col += 1
        self.tone_var = tk.StringVar(value="존댓말")
        ttk.Combobox(row2, textvariable=self.tone_var, state='readonly', width=8,
                     values=["존댓말", "반말"]).grid(row=0, column=col, sticky='w', padx=(0, 15)); col += 1

        ttk.Label(row2, text="글자크기:").grid(row=0, column=col, sticky='e', padx=(0, 5)); col += 1
        self.fontsize_var = tk.StringVar(value="16")
        ttk.Combobox(row2, textvariable=self.fontsize_var, state='readonly', width=6,
                     values=["11", "13", "15", "16", "19", "24", "28"]).grid(row=0, column=col, sticky='w', padx=(0, 15)); col += 1

        ttk.Label(row2, text="정렬:").grid(row=0, column=col, sticky='e', padx=(0, 5)); col += 1
        self.align_var = tk.StringVar(value="가운데정렬")
        ttk.Combobox(row2, textvariable=self.align_var, state='readonly', width=10,
                     values=["가운데정렬", "왼쪽정렬", "오른쪽정렬"]).grid(row=0, column=col, sticky='w', padx=(0, 15)); col += 1

        ttk.Label(row2, text="인용구:").grid(row=0, column=col, sticky='e', padx=(0, 5)); col += 1
        self.quote_var = tk.StringVar(value="3")
        ttk.Combobox(row2, textvariable=self.quote_var, state='readonly', width=5,
                     values=["1", "2", "3", "4", "5", "6"]).grid(row=0, column=col, sticky='w', padx=(0, 15)); col += 1

        self.toc_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row2, text="목차 포함", variable=self.toc_var).grid(row=0, column=col, sticky='w', padx=(0, 15)); col += 1

        self.title_repeat_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row2, text="제목 3번 반복", variable=self.title_repeat_var).grid(row=0, column=col, sticky='w')

        # ── 색상 규칙 ──
        color_choices = ["없음", "빨간색", "파란색", "청록색", "초록색", "보라색", "주황색"]
        highlight_choices = ["없음", "노란 형광펜", "검정 형광펜", "파란 형광펜", "빨간 형광펜", "초록 형광펜", "청록 형광펜"]

        row3c = ttk.LabelFrame(sc, text="색상 규칙", padding=10)
        row3c.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(row3c, text="긍정/개선:").grid(row=0, column=0, sticky='e', padx=(0, 5))
        self.color_positive_var = tk.StringVar(value="파란색")
        ttk.Combobox(row3c, textvariable=self.color_positive_var, state='readonly', width=10,
                     values=color_choices).grid(row=0, column=1, sticky='w', padx=(0, 15))

        ttk.Label(row3c, text="부정/경고:").grid(row=0, column=2, sticky='e', padx=(0, 5))
        self.color_negative_var = tk.StringVar(value="빨간색")
        ttk.Combobox(row3c, textvariable=self.color_negative_var, state='readonly', width=10,
                     values=color_choices).grid(row=0, column=3, sticky='w', padx=(0, 15))

        ttk.Label(row3c, text="강조 형광펜:").grid(row=0, column=4, sticky='e', padx=(0, 5))
        self.highlight_emphasis_var = tk.StringVar(value="노란 형광펜")
        ttk.Combobox(row3c, textvariable=self.highlight_emphasis_var, state='readonly', width=12,
                     values=highlight_choices).grid(row=0, column=5, sticky='w', padx=(0, 15))

        ttk.Label(row3c, text="강조 글자크기:").grid(row=0, column=6, sticky='e', padx=(0, 5))
        self.emphasis_fontsize_var = tk.StringVar(value="19")
        ttk.Combobox(row3c, textvariable=self.emphasis_fontsize_var, state='readonly', width=6,
                     values=["11", "13", "15", "16", "19", "24", "28"]).grid(row=0, column=7, sticky='w')

        ttk.Label(row3c, text="제품명:").grid(row=1, column=0, sticky='e', padx=(0, 5), pady=(5, 0))
        self.color_product_var = tk.StringVar(value="없음")
        ttk.Combobox(row3c, textvariable=self.color_product_var, state='readonly', width=10,
                     values=color_choices).grid(row=1, column=1, sticky='w', padx=(0, 15), pady=(5, 0))

        ttk.Label(row3c, text="제품명 형광펜:").grid(row=1, column=2, sticky='e', padx=(0, 5), pady=(5, 0))
        self.highlight_product_var = tk.StringVar(value="없음")
        ttk.Combobox(row3c, textvariable=self.highlight_product_var, state='readonly', width=12,
                     values=highlight_choices).grid(row=1, column=3, sticky='w', padx=(0, 15), pady=(5, 0))

        # ── 추가 지시사항 ──
        row4 = ttk.LabelFrame(sc, text="추가 지시사항", padding=10)
        row4.pack(fill=tk.X, padx=10, pady=5)
        self.extra_text = tk.Text(row4, height=2, font=('맑은 고딕', 9))
        self.extra_text.pack(fill=tk.X)

        # ── 참고자료 ──
        ref_files_frame = ttk.LabelFrame(sc, text="참고자료 (제품 선택 시 자동 매칭)", padding=10)
        ref_files_frame.pack(fill=tk.X, padx=10, pady=5)

        self.ref_listbox = tk.Listbox(ref_files_frame, height=3, font=('맑은 고딕', 9),
                                       state='disabled', disabledforeground='#333333')
        self.ref_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ref_scroll = ttk.Scrollbar(ref_files_frame, orient=tk.VERTICAL, command=self.ref_listbox.yview)
        ref_scroll.pack(side=tk.LEFT, fill=tk.Y)
        self.ref_listbox.config(yscrollcommand=ref_scroll.set)

        # ── 하단: 버튼 + 결과 ──
        bottom_pane = ttk.Frame(paned)
        paned.add(bottom_pane, stretch="always", minsize=200)

        btn = ttk.Frame(bottom_pane)
        btn.pack(fill=tk.X, padx=10, pady=5)

        self.generate_btn = ttk.Button(btn, text="치환 생성 (Ctrl+G)", style='Generate.TButton', command=self._on_generate)
        self.generate_btn.pack(side=tk.LEFT, padx=(0, 5))
        self.stop_btn = ttk.Button(btn, text="■ 중단", command=self._on_stop, state='disabled')
        self.stop_btn.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(btn, text="프롬프트 미리보기 (Ctrl+P)", command=self._on_preview).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(btn, text="Word 저장 (Ctrl+S)", command=self._on_save_docx).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(btn, text="텍스트 저장", command=self._on_save_txt).pack(side=tk.LEFT, padx=(0, 5))
        self._restore_btn = ttk.Button(btn, text="본문 복원", command=self._on_restore)
        # 처음에는 숨김 — 미리보기 시에만 표시
        ttk.Button(btn, text="크게 보기", command=self._on_compare_view).pack(side=tk.LEFT, padx=(5, 0))
        ttk.Button(btn, text="시트 새로고침 (F5)", style='Refresh.TButton',
                   command=self._on_refresh_sheet).pack(side=tk.LEFT, padx=(5, 0))

        self.status_var = tk.StringVar(value="스프레드시트를 연결해주세요 (설정 탭)")
        ttk.Label(btn, textvariable=self.status_var, font=('맑은 고딕', 9)).pack(side=tk.RIGHT)

        # 검수 전광판
        inspect_frame = tk.Frame(bottom_pane, bg=self.THEME["inspect_bg"], relief=tk.RIDGE, bd=2)
        inspect_frame.pack(fill=tk.X, padx=10, pady=(5, 0))

        # 상단: 제목 + 검수 버튼
        inspect_header = tk.Frame(inspect_frame, bg=self.THEME["inspect_bg"], padx=12)
        inspect_header.pack(fill=tk.X, pady=(8, 4))
        tk.Label(inspect_header, text="검수 전광판", font=('맑은 고딕', 10, 'bold'),
                 fg='#ffffff', bg=self.THEME["inspect_bg"]).pack(side=tk.LEFT)
        self._inspect_btn = tk.Button(inspect_header, text="서식 검수 (F6)", font=('맑은 고딕', 8, 'bold'),
                                       fg='#ffffff', bg='#555555', activebackground='#777777',
                                       relief=tk.FLAT, padx=8, pady=2, command=self._run_inspection)
        self._inspect_btn.pack(side=tk.LEFT, padx=(15, 0))
        self._ai_inspect_btn = tk.Button(inspect_header, text="AI 내용 검수 (F7)", font=('맑은 고딕', 8, 'bold'),
                                          fg='#ffffff', bg='#2e7d32', activebackground='#388e3c',
                                          relief=tk.FLAT, padx=8, pady=2, command=self._run_ai_inspection)
        self._ai_inspect_btn.pack(side=tk.LEFT, padx=(8, 0))
        self._inspect_summary = tk.StringVar(value="")
        tk.Label(inspect_header, textvariable=self._inspect_summary,
                 font=('맑은 고딕', 9, 'bold'), fg='#aaaaaa',
                 bg=self.THEME["inspect_bg"]).pack(side=tk.RIGHT)

        # 하단: 검수 항목 그리드
        inspect_grid = tk.Frame(inspect_frame, bg=self.THEME["inspect_bg"], padx=12)
        inspect_grid.pack(fill=tk.X, pady=(0, 4))
        self._inspect_labels = {}

        # 서식 검수 항목 (2행 4열)
        _items = ["글자수", "이미지 번호", "서식 지시", "제품명", "타사 잔존", "상품 링크", "인용구", "목차"]
        for i, name in enumerate(_items):
            row, col = divmod(i, 4)
            cell = tk.Frame(inspect_grid, bg=self.THEME["inspect_bg"])
            cell.grid(row=row, column=col, sticky='w', padx=(0, 25), pady=1)
            icon_var = tk.StringVar(value="—")
            icon_lbl = tk.Label(cell, textvariable=icon_var, font=('맑은 고딕', 9, 'bold'),
                                fg='#888888', bg=self.THEME["inspect_bg"], width=2)
            icon_lbl.pack(side=tk.LEFT)
            tk.Label(cell, text=name, font=('맑은 고딕', 9),
                     fg='#cccccc', bg=self.THEME["inspect_bg"]).pack(side=tk.LEFT, padx=(2, 4))
            desc_var = tk.StringVar(value="-")
            desc_lbl = tk.Label(cell, textvariable=desc_var, font=('맑은 고딕', 8),
                                fg='#aaaaaa', bg=self.THEME["inspect_bg"])
            desc_lbl.pack(side=tk.LEFT)
            self._inspect_labels[name] = (icon_var, icon_lbl, desc_var, desc_lbl)

        # 구분선
        sep = tk.Frame(inspect_frame, bg='#555555', height=1)
        sep.pack(fill=tk.X, padx=12, pady=(4, 4))

        # AI 내용 검수 항목 (1행 4열)
        ai_grid = tk.Frame(inspect_frame, bg=self.THEME["inspect_bg"], padx=12)
        ai_grid.pack(fill=tk.X, pady=(0, 8))
        _ai_items = ["부정 표현", "소구점", "복용법", "종합"]
        for i, name in enumerate(_ai_items):
            cell = tk.Frame(ai_grid, bg=self.THEME["inspect_bg"])
            cell.grid(row=0, column=i, sticky='w', padx=(0, 25), pady=1)
            icon_var = tk.StringVar(value="—")
            icon_lbl = tk.Label(cell, textvariable=icon_var, font=('맑은 고딕', 9, 'bold'),
                                fg='#888888', bg=self.THEME["inspect_bg"], width=2)
            icon_lbl.pack(side=tk.LEFT)
            lbl_color = '#99ccff' if name != "종합" else '#ffcc66'
            tk.Label(cell, text=name, font=('맑은 고딕', 9),
                     fg=lbl_color, bg=self.THEME["inspect_bg"]).pack(side=tk.LEFT, padx=(2, 4))
            desc_var = tk.StringVar(value="AI 검수 대기")
            desc_lbl = tk.Label(cell, textvariable=desc_var, font=('맑은 고딕', 8),
                                fg='#aaaaaa', bg=self.THEME["inspect_bg"])
            desc_lbl.pack(side=tk.LEFT)
            self._inspect_labels[name] = (icon_var, icon_lbl, desc_var, desc_lbl)

        # 결과
        result_frame = ttk.LabelFrame(bottom_pane, text="치환 결과", padding=5)
        result_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(5, 10))
        self.result_text = scrolledtext.ScrolledText(result_frame, wrap=tk.WORD, font=('맑은 고딕', 10), height=18,
                                                     bg=self.THEME["text_bg"], fg=self.THEME["text_fg"])
        self.result_text.pack(fill=tk.BOTH, expand=True)
        self.result_text.tag_configure("annotation", foreground=self.THEME["accent2"], font=('맑은 고딕', 9, 'bold'))

        # ═══ 탭2: 설정 ═══
        tab2 = ttk.Frame(notebook)
        notebook.add(tab2, text="  설정  ")

        api_frame = ttk.LabelFrame(tab2, text="Claude API Key", padding=15)
        api_frame.pack(fill=tk.X, padx=15, pady=(15, 10))
        self.api_key_var = tk.StringVar(value=load_api_key())
        ttk.Entry(api_frame, textvariable=self.api_key_var, width=65, show='*').pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(api_frame, text="저장", command=self._save_api_key).pack(side=tk.LEFT)

        sheet_frame = ttk.LabelFrame(tab2, text="Google Sheets 연결", padding=15)
        sheet_frame.pack(fill=tk.X, padx=15, pady=(0, 10))
        ttk.Label(sheet_frame, text="스프레드시트 ID:").pack(anchor='w')
        self.sheet_id_var = tk.StringVar(value=load_sheet_id())
        ttk.Entry(sheet_frame, textvariable=self.sheet_id_var, width=65).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(sheet_frame, text="연결", command=self._on_connect_sheet).pack(side=tk.LEFT)

        # AI 검수 항목 편집
        review_frame = ttk.LabelFrame(tab2, text="AI 검수 항목 (편집 가능)", padding=15)
        review_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 10))
        ttk.Label(review_frame, text="검수 시 사용할 항목을 자유롭게 수정하세요. 비우면 기본값 사용.",
                  font=('맑은 고딕', 8)).pack(anchor='w')
        self.review_criteria_text = scrolledtext.ScrolledText(
            review_frame, wrap=tk.WORD, font=('맑은 고딕', 9), height=8,
            bg=self.THEME["text_bg"], fg=self.THEME["text_fg"])
        self.review_criteria_text.pack(fill=tk.BOTH, expand=True, pady=(5, 5))
        self.review_criteria_text.insert('1.0', DEFAULT_REVIEW_CRITERIA)
        rc_btn_frame = ttk.Frame(review_frame)
        rc_btn_frame.pack(fill=tk.X)
        ttk.Button(rc_btn_frame, text="기본값 복원",
                   command=lambda: (self.review_criteria_text.delete('1.0', tk.END),
                                    self.review_criteria_text.insert('1.0', DEFAULT_REVIEW_CRITERIA))
                   ).pack(side=tk.LEFT)

        info_frame = ttk.LabelFrame(tab2, text="정보", padding=15)
        info_frame.pack(fill=tk.X, padx=15, pady=(0, 10))
        ttk.Label(info_frame, text=f"버전: {VERSION}").pack(anchor='w')
        ttk.Label(info_frame, text=f"원고제작기 폴더: {GENERATOR_DIR}").pack(anchor='w')
        ttk.Label(info_frame, text=f"출력 폴더: {OUTPUT_DIR}").pack(anchor='w')
        ttk.Button(info_frame, text="출력 폴더 열기",
                   command=lambda: os.startfile(OUTPUT_DIR)).pack(anchor='w', pady=(5, 0))

    # ── 초기 로드 ──
    def _init_load(self):
        sid = load_sheet_id()
        if sid:
            self._connect_and_load(sid)

    def _connect_and_load(self, sheet_id):
        def worker():
            spreadsheet, err = connect_sheet(sheet_id)
            if err:
                self.root.after(0, lambda: self.status_var.set(f"연결 실패: {err}"))
                return
            self.spreadsheet = spreadsheet
            data = load_sheet_data(spreadsheet)
            def update():
                self.sheet_data = data
                products = list(data["products"].keys())
                self.product_combo['values'] = products
                if products:
                    self.product_var.set(products[0])
                self.status_var.set(f"연결 완료 — 제품 {len(products)}개")
            self.root.after(0, update)
        threading.Thread(target=worker, daemon=True).start()

    def _on_connect_sheet(self):
        sid = self.sheet_id_var.get().strip()
        if not sid:
            messagebox.showwarning("입력 필요", "스프레드시트 ID를 입력해주세요.")
            return
        save_sheet_id(sid)
        self.status_var.set("연결 중...")
        self._connect_and_load(sid)

    def _on_refresh_sheet(self):
        if self.spreadsheet:
            self.status_var.set("새로고침 중...")
            def worker():
                data = load_sheet_data(self.spreadsheet)
                def update():
                    self.sheet_data = data
                    products = list(data["products"].keys())
                    self.product_combo['values'] = products
                    self.status_var.set(f"새로고침 완료 — 제품 {len(products)}개")
                self.root.after(0, update)
            threading.Thread(target=worker, daemon=True).start()

    def _save_api_key(self):
        save_api_key(self.api_key_var.get())
        messagebox.showinfo("저장", "API Key가 저장되었습니다.")

    def _update_product_link(self):
        """상품 링크 자동 생성 (추적 파라미터 포함) — 원고 제작기와 동일"""
        product = self.product_var.get()
        base_link = self.sheet_data.get("product_links", {}).get(product, "")
        if not base_link:
            self.link_entry.delete(0, tk.END)
            return

        product_code = _get_product_code(product, self.sheet_data)

        # nt_detail: 날짜 + 키워드 (띄어쓰기 제거)
        date = self.date_var.get().strip()
        keyword = self.keyword_var.get().strip().split(',')[0].strip()
        nt_detail = f"{date}{keyword}".replace(" ", "")

        # nt_medium
        nt_medium = self.nt_medium_var.get().strip()

        # 링크 조립
        params = f"nt_source=blog"
        if nt_medium:
            params += f"&nt_medium={nt_medium}"
        if nt_detail:
            params += f"&nt_detail={nt_detail}"
        if product_code:
            params += f"&nt_keyword={product_code}"

        full_link = f"{base_link}?{params}"
        self.link_entry.delete(0, tk.END)
        self.link_entry.insert(0, full_link)

    def _on_product_changed(self):
        product = self.product_var.get()
        # 상품 링크 자동 생성
        self._update_product_link()
        # 참고자료 갱신
        self.reference_files = load_refs_for_product(product)
        self.ref_listbox.config(state='normal')
        self.ref_listbox.delete(0, tk.END)
        for fname, content in self.reference_files.items():
            char_count = len(content)
            self.ref_listbox.insert(tk.END, f"  {fname}  ({char_count:,}자)")
        self.ref_listbox.config(state='disabled')

    # ── 파일 입력 ──
    def _on_load_file(self):
        fpath = filedialog.askopenfilename(
            title="레퍼런스 원고 선택",
            filetypes=[("지원 파일", "*.docx *.pdf *.txt *.md"), ("모든 파일", "*.*")]
        )
        if fpath:
            content = read_file_content(fpath)
            self.ref_text.delete('1.0', tk.END)
            self.ref_text.insert('1.0', content)
            self._file_label.set(os.path.basename(fpath))

    def _on_clear_ref(self):
        self.ref_text.delete('1.0', tk.END)
        self._file_label.set("파일 미선택")

    # ── 프롬프트 빌드 ──
    def _build_prompt(self):
        reference_text = self.ref_text.get('1.0', tk.END).strip()
        if not reference_text:
            messagebox.showwarning("입력 필요", "레퍼런스 원고를 입력해주세요.")
            return None

        product = self.product_var.get()
        if not product:
            messagebox.showwarning("입력 필요", "제품을 선택해주세요.")
            return None

        extra = self.extra_text.get('1.0', tk.END).strip()
        product_link = self.link_entry.get().strip()

        # 문체 지시 (톤)
        tone = self.tone_var.get()
        # 레퍼런스 톤 유지하되 지정된 문체로
        tone_instruction = f"\n문체는 '{tone}'로 통일해주세요." if tone else ""
        if tone_instruction:
            extra = tone_instruction + ("\n" + extra if extra else "")

        prompt = build_transform_prompt(
            sheet_data=self.sheet_data,
            product_name=product,
            reference_text=reference_text,
            extra_instructions=extra,
            tone=tone,
            font_size=self.fontsize_var.get(),
            alignment=self.align_var.get(),
            quote_num=self.quote_var.get(),
            color_positive=self.color_positive_var.get(),
            color_negative=self.color_negative_var.get(),
            highlight_emphasis=self.highlight_emphasis_var.get(),
            color_product=self.color_product_var.get(),
            highlight_product=self.highlight_product_var.get(),
            emphasis_fontsize=self.emphasis_fontsize_var.get(),
            product_link=product_link,
            include_toc=self.toc_var.get(),
            title_repeat=self.title_repeat_var.get(),
            selected_refs=self.reference_files,
        )
        return prompt

    # ── 미리보기 ──
    def _on_preview(self):
        prompt = self._build_prompt()
        if prompt:
            # 현재 본문 백업
            current = self.result_text.get('1.0', tk.END).strip()
            if current and current != self._preview_backup:
                self._preview_backup = current
            self.result_text.delete('1.0', tk.END)
            self.result_text.insert('1.0', prompt)
            self._update_char_count()
            self._restore_btn.pack(side=tk.LEFT, padx=(5, 0))
            self.status_var.set("프롬프트 미리보기 — 본문 복원 버튼으로 되돌릴 수 있습니다")

    def _on_restore(self):
        """미리보기 전 본문 복원"""
        if self._preview_backup:
            self.result_text.delete('1.0', tk.END)
            self.result_text.insert('1.0', self._preview_backup)
            self._highlight_annotations()
            self._update_char_count()
            self._restore_btn.pack_forget()
            self.status_var.set("본문 복원됨")

    # ── 크게 보기 (비교 뷰) ──
    def _on_compare_view(self):
        """레퍼런스 원고(왼쪽) vs 치환 결과(오른쪽) 비교 팝업"""
        ref_content = self.ref_text.get('1.0', tk.END).strip()
        result_content = self.result_text.get('1.0', tk.END).strip()

        if not ref_content and not result_content:
            messagebox.showinfo("크게 보기", "레퍼런스 원고 또는 치환 결과가 없습니다.")
            return

        win = tk.Toplevel(self.root)
        win.title("원고 비교 — 레퍼런스 vs 치환 결과")
        win.geometry("1500x850")
        win.minsize(900, 500)
        win.configure(bg=self.THEME["bg"])

        # 상단 안내
        header = tk.Frame(win, bg=self.THEME["bg"])
        header.pack(fill=tk.X, padx=15, pady=(10, 5))
        tk.Label(header, text="왼쪽: 레퍼런스 원고 (읽기 전용)  |  오른쪽: 치환 결과 (편집 가능 → 적용 버튼으로 반영)",
                 font=('맑은 고딕', 9), fg='#555555', bg=self.THEME["bg"]).pack(side=tk.LEFT)

        # 좌우 분할
        paned = tk.PanedWindow(win, orient=tk.HORIZONTAL, sashwidth=6,
                               sashrelief=tk.RAISED, bg=self.THEME["sash"], bd=1)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # 왼쪽: 레퍼런스 (읽기 전용)
        left_frame = ttk.LabelFrame(paned, text="레퍼런스 원고", padding=5)
        paned.add(left_frame, stretch="always", minsize=300)
        left_text = scrolledtext.ScrolledText(
            left_frame, wrap=tk.WORD, font=('맑은 고딕', 10),
            bg='#f5f5f0', fg=self.THEME["text_fg"])
        left_text.pack(fill=tk.BOTH, expand=True)
        left_text.insert('1.0', ref_content)
        left_text.configure(state='disabled')

        # 오른쪽: 치환 결과 (편집 가능)
        right_frame = ttk.LabelFrame(paned, text="치환 결과 (편집 가능)", padding=5)
        paned.add(right_frame, stretch="always", minsize=300)
        right_text = scrolledtext.ScrolledText(
            right_frame, wrap=tk.WORD, font=('맑은 고딕', 10),
            bg=self.THEME["text_bg"], fg=self.THEME["text_fg"])
        right_text.pack(fill=tk.BOTH, expand=True)
        right_text.insert('1.0', result_content)

        # 하단 버튼
        btn_frame = tk.Frame(win, bg=self.THEME["bg"])
        btn_frame.pack(fill=tk.X, padx=15, pady=(5, 10))

        def apply_and_close():
            edited = right_text.get('1.0', tk.END).strip()
            self.result_text.delete('1.0', tk.END)
            self.result_text.insert('1.0', edited)
            self._highlight_annotations()
            self._update_char_count()
            self.status_var.set("비교 뷰에서 수정 내용 적용됨")
            win.destroy()

        ttk.Button(btn_frame, text="수정 내용 적용 후 닫기", style='Generate.TButton',
                   command=apply_and_close).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(btn_frame, text="적용 없이 닫기",
                   command=win.destroy).pack(side=tk.LEFT)

        # 글자수 표시
        def _count_body(text):
            chars = 0
            for line in text.split('\n'):
                s = line.strip()
                if s and not s.startswith('ㄴ') and not re.match(r'^\d{1,2}$', s):
                    chars += len(s)
            return chars

        def _update_counts(*_):
            ref_chars = _count_body(ref_content)
            res_text = right_text.get('1.0', tk.END).strip()
            res_chars = _count_body(res_text)
            diff_pct = ((res_chars - ref_chars) / ref_chars * 100) if ref_chars else 0
            sign = "+" if diff_pct > 0 else ""
            color = '#c62828' if abs(diff_pct) > 15 else '#2e7d32'
            count_label.configure(text=f"레퍼런스 {ref_chars:,}자 → 치환 {res_chars:,}자 ({sign}{diff_pct:.1f}%)",
                                  fg=color)

        count_label = tk.Label(btn_frame, text="", font=('맑은 고딕', 9, 'bold'),
                               bg=self.THEME["bg"])
        count_label.pack(side=tk.RIGHT)
        _update_counts()
        right_text.bind('<KeyRelease>', _update_counts)

        # 동기 스크롤 (선택적 — 줄 수가 다를 수 있어서 독립 스크롤 기본)
        win.focus_set()

    # ── 생성 ──
    def _on_generate(self):
        if self.is_generating:
            return

        # 필수값 검증
        missing = []
        if not self.keyword_var.get().strip():
            missing.append("메인 키워드")
        if not self.author_var.get().strip():
            missing.append("작가명")
        if not self.nt_medium_var.get().strip():
            missing.append("nt_medium")
        if missing:
            messagebox.showwarning("필수 설정 누락",
                f"다음 항목을 입력해주세요:\n\n• {'  • '.join(missing)}")
            return

        prompt = self._build_prompt()
        if not prompt:
            return

        api_key = self.api_key_var.get().strip()
        if not api_key:
            messagebox.showwarning("API Key", "설정 탭에서 Claude API Key를 입력해주세요.")
            return

        self.is_generating = True
        self.cancel_flag = threading.Event()
        self.generate_btn.config(state='disabled')
        self.stop_btn.config(state='normal')
        self.status_var.set("치환 생성 중... (Esc로 중단)")
        self.result_text.delete('1.0', tk.END)

        def on_stream(text):
            """스트리밍 텍스트를 실시간으로 표시"""
            def append():
                self.result_text.insert(tk.END, text)
                self.result_text.see(tk.END)
            self.root.after(0, append)

        def on_complete(result):
            def update():
                self.is_generating = False
                self.generate_btn.config(state='normal')
                self.stop_btn.config(state='disabled')
                # 마크다운 ** 제거 + 이미지 설명 제거
                clean = result.replace('**', '')
                clean = re.sub(r'^ㄴ\s*\([^)]+\)$', '', clean, flags=re.MULTILINE)
                clean = re.sub(r'^0(\d)$', r'\1', clean, flags=re.MULTILINE)
                self.result_text.delete('1.0', tk.END)
                self.result_text.insert('1.0', clean)
                self._highlight_annotations()
                self._update_char_count()
                was_cancelled = self.cancel_flag.is_set()
                self.status_var.set("중단됨 (부분 결과)" if was_cancelled else "치환 완료!")
                # 자동 저장 (텍스트)
                self._auto_save(clean)
            self.root.after(0, update)

        def on_error(err):
            def update():
                self.is_generating = False
                self.generate_btn.config(state='normal')
                self.stop_btn.config(state='disabled')
                self.result_text.delete('1.0', tk.END)
                self.result_text.insert('1.0', f"오류: {err}")
                self.status_var.set("오류 발생")
            self.root.after(0, update)

        threading.Thread(
            target=call_claude_api,
            args=(api_key, prompt, on_complete, on_error, 8192,
                  self.cancel_flag, on_stream),
            daemon=True
        ).start()

    def _on_stop(self):
        """생성 중단"""
        if self.is_generating and self.cancel_flag:
            self.cancel_flag.set()
            self.stop_btn.config(state='disabled')
            self.status_var.set("중단 요청 중...")

    # ── 결과 하이라이팅 ──
    def _highlight_annotations(self):
        text_widget = self.result_text
        content = text_widget.get('1.0', tk.END)
        for i, line in enumerate(content.split('\n'), 1):
            stripped = line.strip()
            if stripped.startswith('ㄴ'):
                start = f"{i}.0"
                end = f"{i}.end"
                text_widget.tag_add("annotation", start, end)

    def _run_inspection(self):
        """검수 전광판 실행"""
        result = self.result_text.get('1.0', tk.END).strip()
        if not result or result.startswith("생성 중"):
            return

        ref = self.ref_text.get('1.0', tk.END).strip()
        product = self.product_var.get()
        settings = {
            "quote_num": self.quote_var.get(),
            "include_toc": self.toc_var.get(),
            "product_link": self.link_entry.get().strip(),
            "font_size": self.fontsize_var.get(),
        }

        items = run_inspection(result, ref, product, settings)

        # 색상 매핑
        STATUS_COLORS = {
            "pass": ("#00cc44", "✓"),
            "fail": ("#ff4444", "✗"),
            "warn": ("#ffaa00", "!"),
        }

        pass_count = sum(1 for _, s, _ in items if s == "pass")
        fail_count = sum(1 for _, s, _ in items if s == "fail")
        warn_count = sum(1 for _, s, _ in items if s == "warn")

        # 요약
        parts = []
        if fail_count:
            parts.append(f"실패 {fail_count}")
        if warn_count:
            parts.append(f"주의 {warn_count}")
        parts.append(f"통과 {pass_count}/{len(items)}")
        self._inspect_summary.set(" | ".join(parts))

        # 각 항목 업데이트
        for name, status, desc in items:
            if name in self._inspect_labels:
                icon_var, icon_lbl, desc_var, desc_lbl = self._inspect_labels[name]
                color, symbol = STATUS_COLORS.get(status, ("#888888", "—"))
                icon_var.set(symbol)
                icon_lbl.config(fg=color)
                desc_var.set(desc)
                desc_lbl.config(fg=color)

    def _update_char_count(self):
        """글자수 업데이트 (호환용) — 검수 전광판으로 대체"""
        self._run_inspection()

    def _run_ai_inspection(self):
        """AI 내용 검수 — Claude API로 부정표현/소구점/복용법 체크"""
        result = self.result_text.get('1.0', tk.END).strip()
        if not result or result.startswith("생성 중"):
            messagebox.showwarning("검수 불가", "치환 결과가 없습니다.")
            return

        api_key = self.api_key_var.get().strip()
        if not api_key:
            messagebox.showwarning("API Key", "설정 탭에서 Claude API Key를 입력해주세요.")
            return

        product = self.product_var.get()
        product_guide = self.sheet_data.get("products", {}).get(product, "")

        if not product:
            messagebox.showwarning("입력 필요", "제품을 선택해주세요.")
            return

        # UI 상태: 검수 중
        self._ai_inspect_btn.config(state='disabled', text="AI 검수 중...")
        STATUS_COLORS = {
            "pass": ("#00cc44", "✓"),
            "fail": ("#ff4444", "✗"),
            "warn": ("#ffaa00", "!"),
        }
        for name in ["부정 표현", "소구점", "복용법", "종합"]:
            icon_var, icon_lbl, desc_var, desc_lbl = self._inspect_labels[name]
            icon_var.set("…")
            icon_lbl.config(fg='#ffaa00')
            desc_var.set("검수 중...")
            desc_lbl.config(fg='#ffaa00')

        custom_criteria = self.review_criteria_text.get('1.0', tk.END).strip()
        prompt = build_content_review_prompt(result, product, product_guide, custom_criteria)

        def on_complete(response):
            def update():
                self._ai_inspect_btn.config(state='normal', text="AI 내용 검수 (F7)")
                parsed = parse_content_review(response)

                for name, (status, desc) in parsed.items():
                    if name in self._inspect_labels:
                        icon_var, icon_lbl, desc_var, desc_lbl = self._inspect_labels[name]
                        color, symbol = STATUS_COLORS.get(status, ("#888888", "—"))
                        icon_var.set(symbol)
                        icon_lbl.config(fg=color)
                        desc_var.set(desc)
                        desc_lbl.config(fg=color)

                # 상세 결과를 별도 창으로 표시
                self._show_ai_review_detail(response)
                self.status_var.set("AI 내용 검수 완료!")
            self.root.after(0, update)

        def on_error(err):
            def update():
                self._ai_inspect_btn.config(state='normal', text="AI 내용 검수 (F7)")
                for name in ["부정 표현", "소구점", "복용법", "종합"]:
                    icon_var, icon_lbl, desc_var, desc_lbl = self._inspect_labels[name]
                    icon_var.set("✗")
                    icon_lbl.config(fg='#ff4444')
                    desc_var.set(f"오류: {err[:30]}")
                    desc_lbl.config(fg='#ff4444')
                self.status_var.set(f"AI 검수 오류: {err[:50]}")
            self.root.after(0, update)

        threading.Thread(
            target=call_claude_api,
            args=(api_key, prompt, on_complete, on_error, 4096),
            daemon=True
        ).start()

    def _show_ai_review_detail(self, response):
        """AI 검수 상세 결과 팝업 + 검수 기반 수정 기능"""
        self._last_review_response = response

        win = tk.Toplevel(self.root)
        win.title("AI 내용 검수 결과")
        win.geometry("750x600")
        win.configure(bg=self.THEME["bg"])

        # 상단 안내
        header = tk.Frame(win, bg=self.THEME["inspect_bg"], padx=12, pady=8)
        header.pack(fill=tk.X)
        tk.Label(header, text="AI 내용 검수 상세", font=('맑은 고딕', 11, 'bold'),
                 fg='#ffffff', bg=self.THEME["inspect_bg"]).pack(side=tk.LEFT)
        tk.Button(header, text="결과 복사", font=('맑은 고딕', 8),
                  command=lambda: (win.clipboard_clear(), win.clipboard_append(response)),
                  fg='#ffffff', bg='#555555', relief=tk.FLAT, padx=8).pack(side=tk.RIGHT)

        # 결과 텍스트
        text_widget = scrolledtext.ScrolledText(win, wrap=tk.WORD, font=('맑은 고딕', 10),
                                                  bg='#1e1e1e', fg='#d4d4d4', padx=10, pady=10)
        text_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 5))

        # 색상 태그
        text_widget.tag_configure("section", foreground="#569cd6", font=('맑은 고딕', 11, 'bold'))
        text_widget.tag_configure("pass_text", foreground="#00cc44")
        text_widget.tag_configure("fail_text", foreground="#ff4444")
        text_widget.tag_configure("warn_text", foreground="#ffaa00")

        # 텍스트 삽입 + 색상 적용
        for line in response.split('\n'):
            stripped = line.strip()
            if stripped.startswith('[') and stripped.endswith(']'):
                text_widget.insert(tk.END, line + '\n', "section")
            elif 'PASS' in stripped or '없음' in stripped or '정확' in stripped or '일치' == stripped.strip():
                text_widget.insert(tk.END, line + '\n', "pass_text")
            elif 'FAIL' in stripped or '발견' in stripped or '오류' in stripped:
                text_widget.insert(tk.END, line + '\n', "fail_text")
            elif 'WARN' in stripped or '부분' in stripped or '주의' in stripped:
                text_widget.insert(tk.END, line + '\n', "warn_text")
            else:
                text_widget.insert(tk.END, line + '\n')

        # 하단: 검수 기반 원고 수정
        fix_frame = tk.Frame(win, bg=self.THEME["bg"])
        fix_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        tk.Label(fix_frame, text="추가 수정 지시 (선택):", font=('맑은 고딕', 9),
                 bg=self.THEME["bg"]).pack(anchor='w')
        fix_instruction = tk.Entry(fix_frame, font=('맑은 고딕', 9), width=60)
        fix_instruction.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8), pady=(3, 0))

        fix_btn = tk.Button(fix_frame, text="검수 기반 원고 수정", font=('맑은 고딕', 9, 'bold'),
                            fg='#ffffff', bg='#2e7d32', activebackground='#388e3c',
                            relief=tk.FLAT, padx=12, pady=4,
                            command=lambda: self._apply_review_fix(
                                text_widget.get('1.0', tk.END).strip(),
                                fix_instruction.get().strip(), fix_btn, win))
        fix_btn.pack(side=tk.RIGHT, pady=(3, 0))

    def _apply_review_fix(self, review_result, user_instruction, fix_btn, win):
        """검수 결과를 반영하여 원고 수정"""
        original = self.result_text.get('1.0', tk.END).strip()
        if not original:
            messagebox.showwarning("수정 불가", "치환 결과가 없습니다.", parent=win)
            return

        api_key = self.api_key_var.get().strip()
        if not api_key:
            messagebox.showwarning("API Key", "설정 탭에서 API Key를 입력해주세요.", parent=win)
            return

        product = self.product_var.get()
        product_guide = self.sheet_data.get("products", {}).get(product, "")

        prompt = build_fix_prompt(original, review_result, product, product_guide, user_instruction)

        fix_btn.config(state='disabled', text="수정 중...")
        self.status_var.set("검수 기반 원고 수정 중...")
        self.cancel_flag = threading.Event()

        # 실시간 표시를 위해 메인 결과창에 바로 스트리밍
        self.result_text.delete('1.0', tk.END)

        def on_stream(text):
            def append():
                self.result_text.insert(tk.END, text)
                self.result_text.see(tk.END)
            self.root.after(0, append)

        def on_complete(result):
            def update():
                clean = result.replace('**', '')
                clean = re.sub(r'^ㄴ\s*\([^)]+\)$', '', clean, flags=re.MULTILINE)
                clean = re.sub(r'^0(\d)$', r'\1', clean, flags=re.MULTILINE)
                self.result_text.delete('1.0', tk.END)
                self.result_text.insert('1.0', clean)
                self._highlight_annotations()
                self._update_char_count()
                was_cancelled = self.cancel_flag.is_set()
                self.status_var.set("수정 중단됨 (부분 결과)" if was_cancelled else "검수 기반 수정 완료!")
                fix_btn.config(state='normal', text="검수 기반 원고 수정")
                self._auto_save(clean)
            self.root.after(0, update)

        def on_error(err):
            def update():
                fix_btn.config(state='normal', text="검수 기반 원고 수정")
                self.status_var.set(f"수정 오류: {err[:50]}")
                messagebox.showerror("수정 오류", str(err), parent=win)
            self.root.after(0, update)

        threading.Thread(
            target=call_claude_api,
            args=(api_key, prompt, on_complete, on_error, 8192,
                  self.cancel_flag, on_stream),
            daemon=True
        ).start()

    # ── 파일명 생성 (원고 제작기와 동일 형식) ──
    def _default_name(self, ext):
        """작가명_날짜키워드_제품코드.확장자"""
        author = self.author_var.get().strip()
        date = self.date_var.get().strip()
        keyword = self.keyword_var.get().strip().split(',')[0].strip().replace(' ', '')
        product = self.product_var.get()
        product_code = _get_product_code(product, self.sheet_data)

        parts = []
        parts.append(author if author else "작가")
        parts.append(f"{date}{keyword}" if keyword else date)
        if product_code:
            parts.append(product_code)

        return f"{'_'.join(parts)}.{ext}"

    # ── 저장 ──
    def _auto_save(self, content):
        fname = self._default_name("txt")
        fpath = os.path.join(OUTPUT_DIR, fname)
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(content)
        self.status_var.set(f"치환 완료! 자동저장: {fname}")

    def _on_save_docx(self):
        content = self.result_text.get('1.0', tk.END).strip()
        if not content:
            messagebox.showwarning("저장", "저장할 내용이 없습니다.")
            return

        default_name = self._default_name("docx")

        fpath = filedialog.asksaveasfilename(
            title="Word 저장",
            initialdir=OUTPUT_DIR,
            initialfile=default_name,
            defaultextension=".docx",
            filetypes=[("Word 문서", "*.docx")]
        )
        if fpath:
            from docx_writer import save_as_docx
            save_as_docx(content, fpath)
            messagebox.showinfo("저장 완료", f"저장: {os.path.basename(fpath)}")

    def _on_save_txt(self):
        content = self.result_text.get('1.0', tk.END).strip()
        if not content:
            messagebox.showwarning("저장", "저장할 내용이 없습니다.")
            return

        default_name = self._default_name("txt")

        fpath = filedialog.asksaveasfilename(
            title="텍스트 저장",
            initialdir=OUTPUT_DIR,
            initialfile=default_name,
            defaultextension=".txt",
            filetypes=[("텍스트 파일", "*.txt")]
        )
        if fpath:
            with open(fpath, 'w', encoding='utf-8') as f:
                f.write(content)
            messagebox.showinfo("저장 완료", f"저장: {os.path.basename(fpath)}")


# ╔══════════════════════════════════════════════════════════════╗
# ║  6. 실행                                                    ║
# ╚══════════════════════════════════════════════════════════════╝

def main():
    root = tk.Tk()
    TransformerApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
