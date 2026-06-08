#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
migrate_K_to_L.py — 일회성 마이그레이션

기존 K~Q(어제 순위 데이터)를 L~R로 옮기고 K열을 비웁니다.
새로 도입된 K열(영역) 컬럼과 충돌을 막기 위함.

실행:
  cd "C:\\Users\\iamhy\\Desktop\\프로그램 개발\\키워드 전광판"
  python migrate_K_to_L.py
"""

import sys
import io
import os
import json
import base64

import gspread
from google.oauth2.service_account import Credentials

# Windows cp949 인코딩 문제 해결
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# keyword_board.py 와 동일 설정 사용
SPREADSHEET_ID = "1jflcdbmBjQsY4hp8rNULXGGVqb64fGno4kudlTJoqM4"
SHEET_KEYWORD  = "키워드 전광판"
CRED_FILE      = "../manuscript_generator/credentials.json"


def main():
    print("=" * 55)
    print("  K~Q -> L~R 마이그레이션")
    print("=" * 55)

    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds_b64 = os.environ.get("GOOGLE_CREDENTIALS_BASE64")
    if creds_b64:
        info = json.loads(base64.b64decode(creds_b64))
        creds = Credentials.from_service_account_info(info, scopes=scope)
    else:
        creds = Credentials.from_service_account_file(CRED_FILE, scopes=scope)

    gc = gspread.authorize(creds)
    ss = gc.open_by_key(SPREADSHEET_ID)
    ws = ss.worksheet(SHEET_KEYWORD)

    # 시트 전체 행 수 확인
    all_values = ws.get_all_values()
    total_rows = len(all_values)
    print(f"\n[1] 시트 행 수: {total_rows}")

    # K~Q 영역 데이터 읽기
    range_old = f"K1:Q{total_rows}"
    old_data = ws.get(range_old)
    if not old_data:
        print("    K~Q에 데이터 없음 - 마이그레이션 불필요")
        return

    # 빈 행을 trim (뒤쪽 공백 제거)
    while old_data and not any(c.strip() for c in (old_data[-1] if old_data[-1] else [])):
        old_data.pop()

    rows_to_move = len(old_data)
    if rows_to_move == 0:
        print("    K~Q 데이터 모두 비어있음 - 마이그레이션 불필요")
        return

    print(f"[2] K~Q 데이터 {rows_to_move}행 읽음")

    # 미리보기 (앞 3행)
    print("\n[미리보기 - 앞 3행]")
    for i, row in enumerate(old_data[:3], 1):
        preview = [c[:15] + "..." if len(c) > 15 else c for c in row]
        print(f"  {i}: {preview}")

    # 사용자 확인
    answer = input(f"\n위 {rows_to_move}행을 L~R로 이동하고 K~Q를 비웁니다. 계속? (y/N): ").strip().lower()
    if answer != "y":
        print("취소됨")
        return

    # L~R로 복사
    range_new = f"L1:R{rows_to_move}"
    ws.update(values=old_data, range_name=range_new)
    print(f"[3] L~R 기입 완료 ({rows_to_move}행)")

    # K~Q 비우기
    ws.batch_clear([range_old])
    print(f"[4] K~Q 초기화 완료")

    print("\n마이그레이션 완료!")


if __name__ == "__main__":
    main()
