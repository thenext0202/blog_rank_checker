"""
metadata_generator.py — 이미지 메타데이터 자동 생성 스크립트

시트에서 scene이 비어있는 이미지를 찾아서
Gemini Flash Vision으로 분석 → scene/mood/tags를 시트에 기입.

사용법:
  python metadata_generator.py

특징:
  - scene이 비어있는 행만 처리 (기존 데이터 안 건드림)
  - 50장씩 배치 처리 후 시트에 기입 (중간에 끊겨도 이어서 가능)
  - 10개 병렬 처리 (유료 티어 기준)
  - 진행률 실시간 표시
  - 에러 발생한 행은 건너뛰고 계속 진행
"""

import os
import sys
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from lib_common import (
    base_dir, connect_sheet, connect_drive, drive_download_bytes,
    analyze_image_vision,
)

# ── 설정 ──
CONFIG_DIR = base_dir()
GEMINI_KEY_FILE = os.path.join(CONFIG_DIR, ".gemini_key")
IMAGE_SHEET_CONFIG = os.path.join(CONFIG_DIR, ".image_sheet_id")

BATCH_SIZE = 50       # 시트 기입 단위
MAX_RETRIES = 3       # 이미지당 재시도 횟수
MAX_WORKERS = 4       # 병렬 처리 수 (SSL 충돌 방지)
SHEET_TAB = "이미지 메타데이터"

# 컬럼 인덱스 (0-indexed, 시트는 1-indexed)
COL_SCENE = 5       # E열 (scene)
COL_MOOD = 6        # F열 (mood)
COL_TAGS = 8        # H열 (tags)

VISION_PROMPT = """이 이미지를 보고 아래 3가지를 한국어로 작성하세요.

- scene: 이미지에 보이는 장면을 한 문장으로 설명 (예: "약국에서 약사가 고객에게 약을 설명하는 모습")
- mood: 이미지의 분위기를 단어 1개로 (예: "밝은", "진지한", "따뜻한", "불안한", "일상적인", "전문적인")
- tags: 이미지의 핵심 키워드 5~7개, 쉼표 구분 (예: "약국, 약사, 상담, 건강, 의료, 전문가, 처방")

반드시 JSON으로만 응답하세요:
{"scene": "...", "mood": "...", "tags": "..."}"""


def load_key(filepath):
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read().strip()
    return ""


def get_empty_scene_rows(ws):
    """scene이 비어있는 행 목록 반환. [(행번호(1-indexed), row_data), ...]"""
    all_rows = ws.get_all_values()
    if len(all_rows) < 2:
        return [], all_rows

    empty_rows = []
    for i, row in enumerate(all_rows[1:], start=2):  # 2행부터 (1행은 헤더)
        # drive_file_id가 있고, scene이 비어있는 행
        drive_id = row[0].strip() if len(row) > 0 else ""
        scene = row[COL_SCENE - 1].strip() if len(row) >= COL_SCENE else ""
        if drive_id and not scene:
            empty_rows.append((i, row))

    return empty_rows, all_rows


def download_and_resize(drive_service, drive_file_id):
    """Drive에서 이미지 다운로드 + 리사이즈 → bytes 반환"""
    img_bytes = drive_download_bytes(drive_service, drive_file_id)

    # 비용 절약: 200px 리사이즈 (실패 시 원본 그대로 사용)
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(img_bytes))
        img.thumbnail((200, 200), Image.LANCZOS)
        if img.mode in ('RGBA', 'P', 'LA', 'PA'):
            img = img.convert('RGB')
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        img_bytes = buf.getvalue()
    except Exception:
        pass  # 리사이즈 실패 시 원본 그대로 사용
    return img_bytes


def analyze_image_bytes(gemini_key, img_bytes):
    """이미지 bytes → Gemini Vision 분석 → dict 반환"""
    result_text = analyze_image_vision(gemini_key, img_bytes, VISION_PROMPT)
    if not result_text:
        raise ValueError("Vision API 응답이 비어있음")

    # JSON 파싱 (```json ... ``` 제거)
    cleaned = result_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

    data = json.loads(cleaned)
    return {
        "scene": data.get("scene", ""),
        "mood": data.get("mood", ""),
        "tags": data.get("tags", ""),
    }


def process_gemini(gemini_key, row_num, filename, img_bytes):
    """병렬 처리용: Gemini API 호출만 (Drive 다운로드는 이미 완료)"""
    for attempt in range(MAX_RETRIES):
        try:
            data = analyze_image_bytes(gemini_key, img_bytes)
            return (row_num, data, None)
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 + attempt * 2)
            else:
                return (row_num, None, f"{filename}: {e}")


def update_sheet_batch(ws, updates):
    """배치로 시트에 scene/mood/tags 기입.

    updates: [(행번호, {"scene": ..., "mood": ..., "tags": ...}), ...]
    """
    if not updates:
        return

    # 각 셀 개별 업데이트 (범위 지정)
    cells = []
    for row_num, data in updates:
        # gspread Cell 객체로 변환
        import gspread
        cells.append(gspread.Cell(row=row_num, col=COL_SCENE, value=data["scene"]))
        cells.append(gspread.Cell(row=row_num, col=COL_MOOD, value=data["mood"]))
        cells.append(gspread.Cell(row=row_num, col=COL_TAGS, value=data["tags"]))

    ws.update_cells(cells, value_input_option='RAW')


def main():
    print("=" * 60)
    print("  이미지 메타데이터 자동 생성기")
    print("  Gemini Flash Vision → scene/mood/tags 자동 채우기")
    print(f"  병렬 처리: {MAX_WORKERS}개 동시")
    print("=" * 60)

    # API 키 확인
    gemini_key = load_key(GEMINI_KEY_FILE)
    if not gemini_key:
        print("\n[오류] Gemini API 키가 없습니다. .gemini_key 파일을 확인하세요.")
        return

    # 시트 연결
    sheet_id = load_key(IMAGE_SHEET_CONFIG)
    if not sheet_id:
        print("\n[오류] 이미지 시트 ID가 없습니다. .image_sheet_id 파일을 확인하세요.")
        return

    print("\n시트 연결 중...")
    spreadsheet, err = connect_sheet(sheet_id)
    if err:
        print(f"[오류] {err}")
        return

    ws = spreadsheet.worksheet(SHEET_TAB)

    # Drive 연결
    print("드라이브 연결 중...")
    drive_service, drive_err = connect_drive()
    if drive_err:
        print(f"[오류] {drive_err}")
        return

    # 빈 행 찾기
    print("비어있는 행 탐색 중...")
    empty_rows, _ = get_empty_scene_rows(ws)
    total = len(empty_rows)

    if total == 0:
        print("\n모든 행의 scene이 채워져 있습니다. 작업할 것이 없습니다.")
        return

    print(f"\nscene이 비어있는 행: {total}개")
    print(f"배치 크기: {BATCH_SIZE}장씩 ({MAX_WORKERS}개 병렬)")
    print(f"예상 시간: 약 {max(total // (MAX_WORKERS * 6), 1)}분 (유료 티어 기준)")
    print()

    confirm = input("진행하시겠습니까? (y/n): ").strip().lower()
    if confirm != 'y':
        print("취소됨.")
        return

    # 병렬 처리
    processed = 0
    errors = 0
    start_time = time.time()

    for batch_start in range(0, total, BATCH_SIZE):
        batch = empty_rows[batch_start:batch_start + BATCH_SIZE]
        batch_results = []  # [(행번호, data), ...]

        # 1단계: Drive 다운로드 (순차 — SSL 충돌 방지)
        downloaded = []  # [(row_num, filename, img_bytes), ...]
        for row_num, row_data in batch:
            drive_id = row_data[0].strip()
            filename = row_data[1] if len(row_data) > 1 else "?"
            try:
                img_bytes = download_and_resize(drive_service, drive_id)
                downloaded.append((row_num, filename, img_bytes))
            except Exception as e:
                # SSL 에러 시 Drive 재연결
                if "SSL" in str(e):
                    try:
                        drive_service, _ = connect_drive()
                        img_bytes = download_and_resize(drive_service, drive_id)
                        downloaded.append((row_num, filename, img_bytes))
                        continue
                    except Exception:
                        pass
                errors += 1
                print(f"  [다운로드 에러] 행 {row_num} ({filename}): {e}")

        # 2단계: Gemini API 호출 (병렬)
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(
                    process_gemini, gemini_key, row_num, filename, img_bytes
                ): row_num
                for row_num, filename, img_bytes in downloaded
            }

            for future in as_completed(futures):
                row_num, data, error = future.result()
                if data:
                    batch_results.append((row_num, data))
                    processed += 1
                else:
                    errors += 1
                    print(f"  [에러] 행 {row_num} ({error})")
                    # 실패한 행에 표시 → 다음 실행 때 재시도 안 함
                    batch_results.append((row_num, {"scene": "[태깅실패]", "mood": "", "tags": ""}))

        # 시트에 기입
        if batch_results:
            try:
                update_sheet_batch(ws, batch_results)
            except Exception as e:
                print(f"  [시트 기입 오류] {e}")
                time.sleep(3)
                try:
                    update_sheet_batch(ws, batch_results)
                except Exception:
                    print(f"  [재시도 실패] 이 배치 {len(batch_results)}건 손실")

        elapsed = time.time() - start_time
        done = batch_start + len(batch)
        speed = processed / max(elapsed, 1)
        remaining = (total - done) / max(speed, 0.1)
        print(
            f"  [{done}/{total}] "
            f"성공 {processed} / 에러 {errors} / "
            f"속도 {speed:.1f}장/초 / "
            f"남은 약 {int(remaining)}초"
        )

    # 완료
    elapsed = time.time() - start_time
    print()
    print("=" * 60)
    print(f"  완료!")
    print(f"  처리: {processed}건 성공, {errors}건 에러")
    print(f"  소요 시간: {int(elapsed)}초 ({int(elapsed // 60)}분 {int(elapsed % 60)}초)")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n[오류] {e}")
    input("\n아무 키나 누르면 종료...")
