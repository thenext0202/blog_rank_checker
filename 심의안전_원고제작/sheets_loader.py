"""
심의안전 원고제작기 — Google Sheets 연동
기존 원고제작기 탭 + 심의안전 전용 탭 로딩
"""
import os
from config import CRED_FILE, SHEET_CONFIG_FILE, REFERENCES_DIR, PRODUCT_CODE_MAP

try:
    import gspread
    from google.oauth2.service_account import Credentials
    HAS_GSPREAD = True
except ImportError:
    HAS_GSPREAD = False


def connect_sheet(sheet_id):
    """Google Sheets 연결. 성공 시 spreadsheet 객체, 실패 시 None"""
    if not HAS_GSPREAD:
        return None
    if not os.path.exists(CRED_FILE):
        return None
    try:
        creds = Credentials.from_service_account_file(
            CRED_FILE,
            scopes=[
                "https://spreadsheets.google.com/feeds",
                "https://www.googleapis.com/auth/drive",
            ]
        )
        gc = gspread.authorize(creds)
        return gc.open_by_key(sheet_id)
    except Exception:
        return None


def save_sheet_id(sheet_id):
    with open(SHEET_CONFIG_FILE, 'w') as f:
        f.write(sheet_id)


def load_sheet_id():
    if os.path.exists(SHEET_CONFIG_FILE):
        with open(SHEET_CONFIG_FILE, 'r') as f:
            return f.read().strip()
    return ""


def load_all_from_sheet(spreadsheet):
    """시트에서 모든 데이터 로드 (기존 탭 + 심의안전 탭)"""
    data = {
        "prompts": {}, "styles": {}, "guidelines": [],
        "products": {}, "product_links": {}, "product_codes": {},
        "format_instructions": "", "papers": {},
        # 심의안전 전용
        "safety_prompts": {}, "safety_appeals": {},
    }

    # 일반 프롬프트 — 심의안전에서는 사용하지 않음 (충돌 방지)

    # 작가스타일
    try:
        ws = spreadsheet.worksheet("작가스타일")
        for row in ws.get_all_values()[1:]:
            if len(row) >= 2 and row[0].strip():
                data["styles"][row[0].strip()] = row[1].strip()
    except Exception:
        pass

    # 공통지침 — 심의안전에서는 SAFETY_GUIDELINES 상수 사용 (충돌 방지)

    # 제품소구점 → A:제품명, B:가이드, C:링크, D:약어(제품코드)
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

    # 서식규칙
    try:
        ws = spreadsheet.worksheet("서식규칙")
        for row in ws.get_all_values()[1:]:
            if len(row) >= 2 and row[0].strip() == "format_instructions":
                data["format_instructions"] = row[1].strip()
                break
    except Exception:
        pass

    # 참고논문 → A:제품명, B:연구명, C:출처, D:대상, E:핵심 결과, F:수치
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

    # ━━━ 심의안전 전용 탭 ━━━

    # 심의안전_프롬프트 → A:유형명, B:프롬프트 (A가 비면 이전 유형에 이어붙임)
    try:
        ws = spreadsheet.worksheet("심의안전_프롬프트")
        current_type = None
        for row in ws.get_all_values()[1:]:
            b_val = row[1].strip() if len(row) >= 2 else ""
            if row[0].strip():
                current_type = row[0].strip()
                data["safety_prompts"][current_type] = b_val
            elif current_type and b_val:
                data["safety_prompts"][current_type] += "\n" + b_val
    except Exception:
        pass

    # 심의안전_소구점 → A:제품명, B:키워드그룹명, C:강조점 조합, D:강조점A, E:강조점B, F:강조점C
    try:
        ws = spreadsheet.worksheet("심의안전_소구점")
        for row in ws.get_all_values()[1:]:
            if len(row) >= 4 and row[0].strip() and row[1].strip():
                pname = row[0].strip()
                if pname not in data["safety_appeals"]:
                    data["safety_appeals"][pname] = []
                entry = {
                    "group": row[1].strip(),
                    "combo": row[2].strip() if len(row) >= 3 else "",
                    "points": {
                        "A": row[3].strip() if len(row) >= 4 else "",
                        "B": row[4].strip() if len(row) >= 5 else "",
                        "C": row[5].strip() if len(row) >= 6 else "",
                    }
                }
                data["safety_appeals"][pname].append(entry)
    except Exception:
        pass

    return data


# ── 파일 읽기 ──
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


# ── 참고자료 로드 ──
VALID_REF_EXTS = ('.txt', '.md', '.csv', '.docx', '.pdf')

def load_refs_for_product(product_name=""):
    """제품에 맞는 참고자료 자동 로드 (공통 + 제품 폴더)"""
    refs = {}
    # 공통 폴더
    common_dir = os.path.join(REFERENCES_DIR, "공통")
    if os.path.exists(common_dir):
        for fname in os.listdir(common_dir):
            fpath = os.path.join(common_dir, fname)
            if os.path.isfile(fpath) and os.path.splitext(fname)[1].lower() in VALID_REF_EXTS:
                refs[f"[공통] {fname}"] = read_file_content(fpath)
    # 제품 폴더
    if product_name:
        product_dir = os.path.join(REFERENCES_DIR, product_name)
        if os.path.exists(product_dir):
            for fname in os.listdir(product_dir):
                fpath = os.path.join(product_dir, fname)
                if os.path.isfile(fpath) and os.path.splitext(fname)[1].lower() in VALID_REF_EXTS:
                    refs[f"[{product_name}] {fname}"] = read_file_content(fpath)
    return refs


# ── 샘플 원고 로드 ──
KNOWN_PROMPT_TYPES = [
    '1인칭 경험담_내부', '시나리오형(수치)', '시나리오형(질병)',
    '공감 정보형_내부', 'GEO 정보성_내부', '독자 칼럼_내부',
    '수치 충격형', '돌발 증상형', '증상 악화 진행형',
    '정보 탐색 큐레이션형', '제3자 관찰형',
    '후기형(ver3)', '후기형(ver2)', '원료기반형', '에어서치',
    '1인칭 경험담', '공감 정보형', 'GEO 정보성', '독자 칼럼',
]


def get_product_code(product_name, sheet_data=None):
    """제품명 → 제품코드"""
    if sheet_data and sheet_data.get("product_codes", {}).get(product_name):
        return sheet_data["product_codes"][product_name]
    for code, name in PRODUCT_CODE_MAP.items():
        if name == product_name:
            return code
    return ""


def load_sample_for_type(prompt_type, product_name="", sheet_data=None):
    """원고 유형(+제품)에 맞는 샘플 원고 1개를 랜덤 선택. 없으면 ("", "")."""
    import random
    from config import SAMPLES_DIR
    if not os.path.exists(SAMPLES_DIR):
        return "", ""

    target_code = get_product_code(product_name, sheet_data)
    same_product = []
    other_product = []

    for fname in os.listdir(SAMPLES_DIR):
        if not (fname.endswith('.docx') or fname.endswith('.txt')):
            continue
        name = os.path.splitext(fname)[0]
        # 파일명에서 원고유형 추출
        parts = name.split('_')
        ftype = None
        for t in KNOWN_PROMPT_TYPES:
            if t in parts:
                ftype = t
                break
        if name.startswith('참고원고_'):
            type_part = name.replace('참고원고_', '').replace('_', ' ')
            for t in KNOWN_PROMPT_TYPES:
                if t == type_part:
                    ftype = t
                    break

        fcode = parts[-1].split('(')[0].strip() if parts else ""

        if ftype == prompt_type:
            if target_code and fcode == target_code:
                same_product.append(fname)
            else:
                other_product.append(fname)

    pool = same_product if same_product else other_product
    if not pool:
        return "", ""

    selected = random.choice(pool)
    content = read_file_content(os.path.join(SAMPLES_DIR, selected))
    if content and not content.startswith("["):
        if len(content) > 4000:
            content = content[:4000] + "\n... (이하 생략)"
        return selected, content
    return "", ""


# ── API Key 관리 ──
def save_api_key(key):
    from config import API_KEY_FILE
    with open(API_KEY_FILE, 'w') as f:
        f.write(key)


def load_api_key():
    from config import API_KEY_FILE
    if os.path.exists(API_KEY_FILE):
        with open(API_KEY_FILE, 'r') as f:
            return f.read().strip()
    return ""
