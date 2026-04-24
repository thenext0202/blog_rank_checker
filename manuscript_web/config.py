"""블록 원고 생성기 — 설정 (경로, API키, 시트 ID, 지침 폴더, 제품 목록)"""
import os
import sys

VERSION = "1.2"

# 지침 폴더 기본 경로 (manuscript_web/지침 모음/ 내부의 6개 모듈 MD)
DEFAULT_INSTRUCTIONS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "지침 모음"
)

# 7개 모듈 파일명 (모듈1이 오케스트레이터, 나머지를 참조)
MODULE_FILES = {
    "orchestrator": "모듈1_오케스트레이터.md",
    "blocks":       "모듈2_블록구조설명서.md",
    "persona":      "모듈3_페르소나분석.md",
    "product_db":   "모듈4_제품데이터베이스.md",
    "regulation":   "모듈5_심의규칙.md",
    "papers":       "모듈6_논문데이터베이스.md",
    "formatting":   "모듈7_서식적용지침.md",
}

# 제품 목록 (드롭다운 + 모듈4/6 섹션 매칭)
# (제품명, 허브키워드, 모듈4 섹션 제목 키워드)
PRODUCTS = [
    ("블러드싸이클",   "블러디션 배합",   "블러드싸이클"),
    ("글루코컷",       "급원알파정",      "글루코컷"),
    ("멜라토닌",       "피스좀 멜라토닌", "멜라토닌"),
    ("상어연골환",     "나노카틸",        "상어연골환"),
    ("판토오틴",       "판토오틴",        "판토오틴"),
    ("퓨어톤 부스트",  "리포글루정",      "퓨어톤"),
    ("헬리컷",         "스토마이신 배합", "헬리컷"),
    ("활성엽산",       "액티플 엽산",     "엽산"),
]
PRODUCT_NAMES = [p[0] for p in PRODUCTS]

# 제품별 강조 성분 목록 — 쉼표 나열 라인에 볼드+노란 형광펜 강제 적용할 때 참조
# (모듈4 제품DB에서 핵심 기능성 성분 위주로 발췌. 부분 매칭이므로 표현 변주 포괄)
PRODUCT_INGREDIENTS = {
    "블러드싸이클": ["오메가3", "EPA", "DHA", "코엔자임Q10", "코큐텐",
                     "홍국", "모나콜린", "비타민E", "비타민A", "아연"],
    "글루코컷":     ["바나바잎추출물", "바나바", "코로솔산", "알파리포산",
                     "사과초모식초", "애사비", "아연", "비타민B1", "비오틴", "엽산"],
    "멜라토닌":     ["멜라토닌", "L-테아닌", "테아닌", "L-트립토판", "트립토판",
                     "가바", "GABA", "타트체리", "피스타치오"],
    "상어연골환":   ["상어연골", "콘드로이친", "해조칼슘", "초록입홍합",
                     "보스웰리아", "울금", "커큐민"],
    "판토오틴":     ["비오틴", "판토텐산", "비타민B1", "비타민B2", "나이아신",
                     "비타민B6", "엽산", "비타민B12", "아연"],
    "퓨어톤 부스트": ["글루타치온", "비타민C", "밀크씨슬", "피쉬콜라겐",
                     "콜라겐", "엘라스틴", "히알루론산"],
    "헬리컷":       ["스페인감초추출물", "감초추출물", "감초", "프로바이오틱스",
                     "아연", "산화아연"],
    "활성엽산":     ["활성형엽산", "엽산", "Quatrefolic", "비타민K2", "셀레늄",
                     "비타민D3", "아연", "비타민B6", "비타민B2", "비타민B12", "비피더스"],
}

# 카테고리 고정값 (사용자 지시: 현재 "생활형C"만)
DEFAULT_CATEGORY = "생활형C"


def base_dir():
    """실행 경로 자동 감지 (EXE / 개발 환경)"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# ── 경로 ──
OUTPUT_DIR = os.path.join(base_dir(), "output")
API_KEY_FILE = os.path.join(base_dir(), ".api_key")
SHEET_CONFIG_FILE = os.path.join(base_dir(), ".sheet_id")
INSTRUCTIONS_DIR_FILE = os.path.join(base_dir(), ".instructions_dir")
WRITER_NAME_FILE = os.path.join(base_dir(), ".writer_name")
DRIVE_FOLDER_FILE = os.path.join(base_dir(), ".drive_folder_id")

# credentials.json fallback (원고 제작기 것 재사용)
CRED_FILE = os.path.join(base_dir(), "credentials.json")
CRED_FALLBACK = os.path.join(
    os.path.dirname(base_dir()), "manuscript_generator", "credentials.json"
)

os.makedirs(OUTPUT_DIR, exist_ok=True)


def get_credentials_path():
    """credentials.json 경로 (환경변수 → 로컬 → fallback)"""
    env_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    if env_path and os.path.exists(env_path):
        return env_path
    if os.path.exists(CRED_FILE):
        return CRED_FILE
    if os.path.exists(CRED_FALLBACK):
        return CRED_FALLBACK
    return CRED_FILE


# ── API Key ──
def load_api_key():
    # 환경변수 우선 (Railway 배포)
    env_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if env_key:
        return env_key
    if os.path.exists(API_KEY_FILE):
        with open(API_KEY_FILE, 'r') as f:
            return f.read().strip()
    return ""

def save_api_key(key):
    with open(API_KEY_FILE, 'w') as f:
        f.write(key.strip())


# ── Sheet ID ──
DEFAULT_SHEET_ID = "1UOlH8gjytdxf1V33Gy69faGHgrwyKyRJ0bEmUsRP1BI"
DEFAULT_TAB_NAME = "원고 작성 리스트"

def load_sheet_id():
    env_id = os.environ.get("SHEET_ID", "").strip()
    if env_id:
        return env_id
    if os.path.exists(SHEET_CONFIG_FILE):
        with open(SHEET_CONFIG_FILE, 'r') as f:
            sid = f.read().strip()
            if sid:
                return sid
    return DEFAULT_SHEET_ID

def save_sheet_id(sid):
    with open(SHEET_CONFIG_FILE, 'w') as f:
        f.write(sid.strip())


# ── Drive 출력 폴더 ID ──
# 기본값: manuscript_generator 와 동일한 원고 출력 폴더 (이미 사용 중)
DEFAULT_DRIVE_FOLDER_ID = "11WrhiUe7vFed2Ep8_Z0vKA9BrMzTcV_I"

def load_drive_folder_id():
    env_id = os.environ.get("DRIVE_FOLDER_ID", "").strip()
    if env_id:
        return env_id
    if os.path.exists(DRIVE_FOLDER_FILE):
        with open(DRIVE_FOLDER_FILE, 'r') as f:
            fid = f.read().strip()
            if fid:
                return fid
    return DEFAULT_DRIVE_FOLDER_ID

def save_drive_folder_id(fid):
    with open(DRIVE_FOLDER_FILE, 'w') as f:
        f.write(fid.strip())


# ── 지침 폴더 ──
def load_instructions_dir():
    if os.path.exists(INSTRUCTIONS_DIR_FILE):
        with open(INSTRUCTIONS_DIR_FILE, 'r', encoding='utf-8') as f:
            path = f.read().strip()
            if os.path.isdir(path):
                return path
    if os.path.isdir(DEFAULT_INSTRUCTIONS_DIR):
        return DEFAULT_INSTRUCTIONS_DIR
    return ""

def save_instructions_dir(path):
    with open(INSTRUCTIONS_DIR_FILE, 'w', encoding='utf-8') as f:
        f.write(path.strip())


# ── 담당자 이름 ──
def load_writer_name():
    if os.path.exists(WRITER_NAME_FILE):
        with open(WRITER_NAME_FILE, 'r', encoding='utf-8') as f:
            return f.read().strip()
    return ""

def save_writer_name(name):
    with open(WRITER_NAME_FILE, 'w', encoding='utf-8') as f:
        f.write(name.strip())
