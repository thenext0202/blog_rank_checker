"""원고 작성기 — 설정/초기화 (경로, API키, 시트ID, 지침 폴더)"""
import os
import sys

VERSION = "1.0"


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
PRODUCTS_DIR_FILE = os.path.join(base_dir(), ".products_dir")

# 기본 제품 정보 폴더 경로 (정보 폴더 내 제품 정보)
DEFAULT_PRODUCTS_DIR = os.path.join(base_dir(), "정보", "제품 정보")

# credentials.json: 기존 원고 제작기 것을 참조
CRED_FILE = os.path.join(base_dir(), "credentials.json")
CRED_FALLBACK = os.path.join(
    os.path.dirname(base_dir()), "manuscript_generator", "credentials.json"
)

os.makedirs(OUTPUT_DIR, exist_ok=True)


def get_credentials_path():
    """credentials.json 경로 (로컬 우선 → 기존 제작기 fallback)"""
    if os.path.exists(CRED_FILE):
        return CRED_FILE
    if os.path.exists(CRED_FALLBACK):
        return CRED_FALLBACK
    return CRED_FILE  # 없으면 로컬 경로 반환 (에러 메시지용)


# ── API Key 저장/로드 ──
def load_api_key():
    if os.path.exists(API_KEY_FILE):
        with open(API_KEY_FILE, 'r') as f:
            return f.read().strip()
    return ""

def save_api_key(key):
    with open(API_KEY_FILE, 'w') as f:
        f.write(key.strip())


# ── Sheet ID 저장/로드 ──
def load_sheet_id():
    if os.path.exists(SHEET_CONFIG_FILE):
        with open(SHEET_CONFIG_FILE, 'r') as f:
            return f.read().strip()
    return ""

def save_sheet_id(sid):
    with open(SHEET_CONFIG_FILE, 'w') as f:
        f.write(sid.strip())


# ── 지침 폴더 경로 저장/로드 ──
def load_instructions_dir():
    if os.path.exists(INSTRUCTIONS_DIR_FILE):
        with open(INSTRUCTIONS_DIR_FILE, 'r', encoding='utf-8') as f:
            path = f.read().strip()
            if os.path.isdir(path):
                return path
    return ""

def save_instructions_dir(path):
    with open(INSTRUCTIONS_DIR_FILE, 'w', encoding='utf-8') as f:
        f.write(path.strip())


# ── 제품 정보 폴더 경로 저장/로드 ──
def load_products_dir():
    if os.path.exists(PRODUCTS_DIR_FILE):
        with open(PRODUCTS_DIR_FILE, 'r', encoding='utf-8') as f:
            path = f.read().strip()
            if os.path.isdir(path):
                return path
    # 기본 경로가 있으면 사용
    if os.path.isdir(DEFAULT_PRODUCTS_DIR):
        return DEFAULT_PRODUCTS_DIR
    return ""

def save_products_dir(path):
    with open(PRODUCTS_DIR_FILE, 'w', encoding='utf-8') as f:
        f.write(path.strip())
