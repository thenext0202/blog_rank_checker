"""
매출 엑셀 -> 구글 스프레드시트 자동 업로더
- 폴더에서 오늘 넣은 '사용자정의채널_*.xlsx' 파일을 읽음
- 파일명에서 날짜를 추출하여 A열에 기입
- 엑셀 데이터를 B열부터 그대로 기입 (하나의 시트에 누적)
"""

import glob
import json
import os
import re
import sys
import tkinter as tk
from tkinter import filedialog

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

# -- 설정 --
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
CREDENTIALS_PATH = os.path.join(SCRIPT_DIR, "credentials.json")
SPREADSHEET_ID = "1jflcdbmBjQsY4hp8rNULXGGVqb64fGno4kudlTJoqM4"
SHEET_NAME = "테스트"
FILE_PATTERN = "사용자정의채널_*.xlsx"


def load_config():
    """설정 파일 로드 (없으면 빈 dict)"""
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(config):
    """설정 파일 저장"""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def get_excel_folder():
    """엑셀 폴더 경로 가져오기 (처음이면 폴더 선택 다이얼로그)"""
    config = load_config()
    folder = config.get("excel_folder")

    if folder and os.path.isdir(folder):
        print(f"[폴더] {folder}")
        return folder

    # 폴더 선택 다이얼로그
    print("[설정] 엑셀 파일이 있는 폴더를 선택해주세요...")
    root = tk.Tk()
    root.withdraw()
    folder = filedialog.askdirectory(title="엑셀 파일 폴더 선택")
    root.destroy()

    if not folder:
        print("[오류] 폴더를 선택하지 않았습니다.")
        sys.exit(1)

    config["excel_folder"] = folder
    save_config(config)
    print(f"[설정] 폴더 저장됨: {folder}")
    return folder


def find_today_files(excel_folder):
    """오늘 폴더에 넣은(수정된) 엑셀 파일들을 찾음"""
    from datetime import date
    today = date.today()
    files = glob.glob(os.path.join(excel_folder, FILE_PATTERN))
    if not files:
        print("[오류] 폴더에 '사용자정의채널_*.xlsx' 파일이 없습니다.")
        sys.exit(1)

    today_files = []
    for f in files:
        mtime = date.fromtimestamp(os.path.getmtime(f))
        if mtime == today:
            today_files.append(f)

    if not today_files:
        print("[오류] 오늘 넣은 파일이 없습니다.")
        print(f"       폴더: {excel_folder}")
        sys.exit(1)

    today_files.sort(key=lambda f: extract_date_from_filename(f))
    print(f"[파일] 오늘 넣은 파일 {len(today_files)}개 발견")
    for f in today_files:
        print(f"  - {os.path.basename(f)}")
    return today_files


def extract_date_from_filename(filepath):
    """파일명에서 날짜 문자열만 추출 (정렬용)"""
    basename = os.path.basename(filepath)
    match = re.search(r"(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})", basename)
    if match:
        return match.group(1)
    return ""


def extract_date(filepath):
    """파일명에서 날짜 추출 (사용자정의채널_2026-03-16_2026-03-16.xlsx -> 2026-03-16)"""
    basename = os.path.basename(filepath)
    match = re.search(r"(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})", basename)
    if not match:
        print(f"[오류] 파일명에서 날짜를 추출할 수 없습니다: {basename}")
        sys.exit(1)
    start_date, end_date = match.group(1), match.group(2)
    if start_date == end_date:
        print(f"[날짜] {start_date}")
        return start_date
    else:
        date_str = f"{start_date}~{end_date}"
        print(f"[기간] {date_str}")
        return date_str


def read_excel(filepath):
    """엑셀 파일을 읽어서 헤더와 데이터 반환"""
    df = pd.read_excel(filepath, engine="openpyxl")
    print(f"[데이터] {len(df)}행 x {len(df.columns)}열")
    return df


def connect_sheets():
    """구글 스프레드시트 연결"""
    if not os.path.exists(CREDENTIALS_PATH):
        print(f"[오류] credentials.json 파일이 없습니다.")
        print(f"       다음 위치에 넣어주세요: {SCRIPT_DIR}")
        sys.exit(1)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=scopes)
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(SPREADSHEET_ID)
    print(f"[연결] 스프레드시트: {spreadsheet.title}")
    return spreadsheet


def get_or_create_sheet(spreadsheet):
    """시트 탭을 가져오거나 새로 생성"""
    try:
        ws = spreadsheet.worksheet(SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=SHEET_NAME, rows=1000, cols=20)
        print(f"[생성] 새 시트 탭: {SHEET_NAME}")
    return ws


def df_to_rows(date_str, df):
    """DataFrame을 구글 시트용 리스트로 변환"""
    rows = []
    for _, row in df.iterrows():
        values = [date_str]
        for val in row.values:
            if pd.isna(val):
                values.append("")
            elif isinstance(val, float) and val == int(val):
                values.append(int(val))
            else:
                values.append(val)
        rows.append(values)
    return rows


def upload_data(ws, date_str, df):
    """데이터를 구글 시트에 업로드 (같은 날짜가 있으면 안전하게 교체)"""
    # A열만 읽어서 날짜 기준으로 위치 파악 (다른 열 데이터에 영향 안 받음)
    a_col = ws.col_values(1)

    # 첫 업로드라면 헤더 추가
    if not a_col:
        headers = ["날짜"] + list(df.columns)
        ws.update("A1:R1", [headers], value_input_option="USER_ENTERED")
        a_col = ["날짜"]
        print("[헤더] 헤더 행 추가 완료")

    new_rows = df_to_rows(date_str, df)

    # 같은 날짜 데이터가 있는지 찾기 (행 번호는 1-based, 헤더=1행)
    old_start = None
    old_end = None
    for i, val in enumerate(a_col[1:], start=2):  # 2행부터 (헤더 제외)
        if val == date_str:
            if old_start is None:
                old_start = i
            old_end = i

    if old_start is not None:
        old_count = old_end - old_start + 1
        new_count = len(new_rows)
        diff = new_count - old_count

        print(f"[업데이트] {date_str} 기존 {old_count}행 -> 새 {new_count}행")

        if diff > 0:
            # 새 데이터가 더 많으면: 빈 행을 삽입해서 뒷 데이터를 밀어냄
            ws.insert_rows([[]] * diff, row=old_end + 1)
            print(f"  >> {diff}행 삽입 (뒷 데이터 보호)")
        elif diff < 0:
            # 새 데이터가 더 적으면: 남는 행을 삭제
            for _ in range(-diff):
                ws.delete_rows(old_start)
            print(f"  >> {-diff}행 삭제")

        # 기존 위치에 새 데이터 덮어쓰기
        cell_range = f"A{old_start}:R{old_start + new_count - 1}"
        ws.update(cell_range, new_rows, value_input_option="USER_ENTERED")
        print(f"[완료] {date_str} 데이터 {new_count}행 업데이트 완료!")
    else:
        # 새 날짜: A열 기준 마지막 행 다음에 추가
        next_row = len(a_col) + 1
        total = len(new_rows)
        batch_size = 100
        for i in range(0, total, batch_size):
            batch = new_rows[i : i + batch_size]
            start = next_row + i
            end = start + len(batch) - 1
            cell_range = f"A{start}:R{end}"
            ws.update(cell_range, batch, value_input_option="USER_ENTERED")
            uploaded = min(i + batch_size, total)
            print(f"  >> 업로드 중... {uploaded}/{total}행")
        print(f"[완료] {date_str} 데이터 {total}행 업로드 완료!")

    return True


def main():
    print("=" * 50)
    print("  매출 데이터 -> 구글 스프레드시트 업로더")
    print("=" * 50)
    print()

    # 1. 엑셀 폴더 확인 (처음이면 폴더 선택)
    excel_folder = get_excel_folder()

    # 2. 오늘 넣은 파일 찾기
    files = find_today_files(excel_folder)

    # 3. 구글 시트 연결
    spreadsheet = connect_sheets()
    ws = get_or_create_sheet(spreadsheet)

    # 4. 각 파일 처리
    for filepath in files:
        print()
        print(f"--- {os.path.basename(filepath)} ---")
        date_str = extract_date(filepath)
        df = read_excel(filepath)
        upload_data(ws, date_str, df)

    print()
    print(f"[링크] https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}")


if __name__ == "__main__":
    main()
