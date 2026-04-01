"""
심의안전 원고제작기 — 설정/상수
"""
import os
import sys

VERSION = "1.0"

def base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

# 경로
REFERENCES_DIR = os.path.join(base_dir(), "references")
SAMPLES_DIR = os.path.join(base_dir(), "samples")
OUTPUT_DIR = os.path.join(base_dir(), "output")
API_KEY_FILE = os.path.join(base_dir(), ".api_key")
CRED_FILE = os.path.join(base_dir(), "credentials.json")
SHEET_CONFIG_FILE = os.path.join(base_dir(), ".sheet_id")
LOG_FILE = os.path.join(base_dir(), "generation_log.json")

for d in [REFERENCES_DIR, SAMPLES_DIR, OUTPUT_DIR]:
    os.makedirs(d, exist_ok=True)

# 유효 글자 크기
VALID_FONT_SIZES = [11, 13, 15, 16, 19, 24, 28]

# 제품 코드 매핑 (시트 D열 우선, 폴백용)
PRODUCT_CODE_MAP = {
    "hc": "헬리컷", "bc": "블러드싸이클", "gc": "글루코컷",
    "sc": "상어연골환", "pt": "퓨어톤 부스트", "po": "판토오틴",
    "ml": "멜라토닌", "af": "액티플 활성엽산",
}

# GUI 테마 (clam 기본 회색)
THEME = {
    "bg": "#dcdad5",
    "fg": "#000000",
    "accent": "#4a6984",
    "accent2": "#2e7d32",
    "warn": "#c62828",
    "surface": "#dcdad5",
    "surface2": "#dcdad5",
    "sash": "#dcdad5",
    "text_bg": "#ffffff",
    "panel_bg": "#2b2b2b",
    "panel_fg": "#e0e0e0",
    "panel_ok": "#81c784",
    "panel_warn": "#ffb74d",
    "panel_error": "#ef5350",
}
