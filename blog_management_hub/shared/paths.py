"""공통 경로 — EXE(PyInstaller frozen) / 스크립트 실행 모두 대응"""

import os
import sys


def get_base_dir():
    """데이터 파일(credentials, config, state)이 위치해야 하는 루트 폴더.
    - EXE 실행 시: exe 파일이 있는 폴더
    - 스크립트 실행 시: main.py가 있는 폴더 (blog_management_hub/)
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


BASE_DIR = get_base_dir()
CREDENTIALS_PATH = os.path.join(BASE_DIR, "credentials.json")
CHROME_PROFILE = os.path.join(BASE_DIR, "chrome_profile")
