"""Google Sheets 통합 래퍼 — 단일 인증, 다중 시트 접근"""

import os

import gspread
from google.oauth2.service_account import Credentials

from shared.paths import CREDENTIALS_PATH

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


class SheetsClient:
    """gspread 클라이언트 싱글톤 래퍼"""

    def __init__(self, credentials_path=None):
        self._gc = None
        # 기본 경로: EXE/스크립트 옆 credentials.json
        if credentials_path is None:
            credentials_path = CREDENTIALS_PATH
        self.credentials_path = credentials_path

    def _ensure_auth(self):
        if self._gc is not None:
            return
        if not os.path.exists(self.credentials_path):
            raise FileNotFoundError(
                f"인증 파일이 없습니다: {self.credentials_path}"
            )
        creds = Credentials.from_service_account_file(
            self.credentials_path, scopes=SCOPES
        )
        self._gc = gspread.authorize(creds)

    def get_worksheet(self, sheet_id, tab_name):
        """시트ID + 탭명으로 Worksheet 객체 반환"""
        self._ensure_auth()
        spreadsheet = self._gc.open_by_key(sheet_id)
        return spreadsheet.worksheet(tab_name)

    def get_spreadsheet(self, sheet_id):
        """Spreadsheet 객체 반환"""
        self._ensure_auth()
        return self._gc.open_by_key(sheet_id)

    def test_connection(self, sheet_id, tab_name):
        """연결 테스트. 성공 시 (True, 시트제목), 실패 시 (False, 에러메시지)"""
        try:
            self._ensure_auth()
            ss = self._gc.open_by_key(sheet_id)
            ws = ss.worksheet(tab_name)
            return True, f"{ss.title} / {tab_name}"
        except Exception as e:
            return False, str(e)
