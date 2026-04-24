"""
catalog_images.py — 구글 드라이브 이미지 스캔 + Claude Vision 자동 태깅 → 시트 등록

사용법:
  python catalog_images.py --drive-folder-id <FOLDER_ID> --sheet-id <SHEET_ID> [--tag]

1단계: Drive 폴더를 재귀 탐색 → 이미지 파일 목록 수집
2단계 (--tag): Claude Vision으로 각 이미지를 분석 → scene/mood/position_hint/tags 자동 생성
→ 결과를 "이미지 메타데이터" 시트 탭에 기록
"""
import os
import sys
import argparse
import time

# 같은 폴더의 lib_common 임포트
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib_common as lc


IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}

VISION_PROMPT_TEMPLATE = """이 이미지는 건강/의학 블로그 원고 작성에 사용됩니다.

[맥락 정보]
- 폴더: {product}/{category}
- 파일명: {filename}

이 맥락을 참고하여 이미지를 분석하고, 아래 형식으로 답변하세요. 각 항목은 반드시 한 줄로 작성하세요.

scene: (이미지의 장면/내용을 20자 이내로 구체적으로 설명. 맥락을 반영하세요. 예: 글루타치온 타사 필름 제품, 합성 멜라토닌 부작용 논문)
mood: (따뜻한/불안한/밝은/일상적/객관적/활기찬 중 택 1)
position_hint: (hooking/opening/middle/closing/any 중 택 1. hooking=시선을 끄는 강렬한 이미지, opening=도입부 분위기, closing=마무리 분위기, middle=일반)
tags: (쉼표로 구분된 키워드 5~8개. 제품명/성분명/증상명 등 구체적 키워드를 포함하세요)

추가 규칙:
- 파일명에 제품명/성분명이 있으면 반드시 tags에 포함하세요.
- 논문/연구자료 이미지는 연구 주제를 scene에 구체적으로 기술하세요.
- 타사제품 폴더의 이미지는 해당 제품의 종류/브랜드를 scene에 명시하세요.
- 커뮤니티/후기 이미지는 어떤 내용의 글인지 scene에 반영하세요.
- scene은 한국어로 작성하세요."""


def infer_product_and_category(path, drive_folder):
    """폴더 경로에서 product, category 추정

    실제 Drive 폴더 구조:
      제품컷/{제품명}        → product=제품명, category=제품컷
      공통/{하위폴더}        → product=공통,  category=하위폴더명
      {제품명}/{하위폴더}    → product=제품명, category=하위폴더명
    """
    parts = path.split('/') if path else [drive_folder] if drive_folder else []
    if not parts:
        return "공통", "기타"

    PRODUCTS = {"글루코컷", "멜라토닌", "블러드싸이클", "상어연골환",
                "판토오틴", "퓨어톤부스트", "헬리컷", "활성엽산"}

    first = parts[0]
    second = parts[1] if len(parts) >= 2 else ""

    # 제품컷/{제품명}
    if first == "제품컷":
        product = second if second else "공통"
        return product, "제품컷"

    # 공통/{카테고리}
    if first == "공통":
        category = second if second else "기타"
        return "공통", category

    # {제품명}/{하위폴더}
    if first in PRODUCTS:
        category = second if second else "기타"
        return first, category

    return "공통", "기타"


def scan_drive_images(service, folder_id):
    """Drive 폴더를 재귀 탐색하여 이미지 파일 목록 반환"""
    print(f"Drive 폴더 스캔 중... (ID: {folder_id})")
    all_files = lc.drive_list_files_recursive(service, folder_id)

    images = []
    for f in all_files:
        ext = os.path.splitext(f['name'])[1].lower()
        if ext in IMAGE_EXTS:
            images.append(f)

    print(f"  → 이미지 {len(images)}개 발견")
    return images


def get_existing_ids(spreadsheet):
    """이미 시트에 등록된 drive_file_id 목록"""
    try:
        ws = spreadsheet.worksheet("이미지 메타데이터")
        rows = ws.get_all_values()
        return {row[0].strip() for row in rows[1:] if row and row[0].strip()}
    except Exception:
        return set()


def ensure_sheet_tab(spreadsheet):
    """이미지 메타데이터 탭이 없으면 생성"""
    try:
        spreadsheet.worksheet("이미지 메타데이터")
    except Exception:
        ws = spreadsheet.add_worksheet(title="이미지 메타데이터", rows=1000, cols=10)
        ws.update('A1:J1', [[
            "drive_file_id", "filename", "product", "category",
            "scene", "mood", "position_hint", "tags",
            "drive_folder", "thumbnail_url"
        ]])
        print("  → '이미지 메타데이터' 탭 생성 완료")


def register_images(spreadsheet, images):
    """이미지 목록을 시트에 등록 (신규만)"""
    existing = get_existing_ids(spreadsheet)
    new_images = [img for img in images if img['id'] not in existing]

    if not new_images:
        print("  → 신규 이미지 없음 (모두 등록 완료)")
        return []

    print(f"  → 신규 이미지 {len(new_images)}개 등록 중...")
    ws = spreadsheet.worksheet("이미지 메타데이터")

    rows_to_add = []
    for img in new_images:
        product, category = infer_product_and_category(img.get('path', ''), img.get('name', ''))
        thumb_url = f"https://drive.google.com/thumbnail?id={img['id']}&sz=w200"
        folder_name = img.get('path', '').split('/')[-1] if img.get('path') else ""

        rows_to_add.append([
            img['id'],           # A: drive_file_id
            img['name'],         # B: filename
            product,             # C: product
            category,            # D: category
            "",                  # E: scene (AI 태깅 또는 수동)
            "",                  # F: mood
            "any",               # G: position_hint
            "",                  # H: tags
            folder_name,         # I: drive_folder
            thumb_url,           # J: thumbnail_url
        ])

    # 시트 행 수 확장 (부족하면)
    next_row = len(ws.get_all_values()) + 1
    needed = next_row + len(rows_to_add) - 1
    if needed > ws.row_count:
        ws.add_rows(needed - ws.row_count + 500)  # 여유 500행 추가

    # 배치로 추가
    ws.update(f'A{next_row}:J{next_row + len(rows_to_add) - 1}', rows_to_add)
    print(f"  → {len(rows_to_add)}개 등록 완료 (행 {next_row}~{next_row + len(rows_to_add) - 1})")
    return new_images


def tag_images_with_vision(api_key, service, spreadsheet, batch_size=10, delay=1.0,
                           model="claude-3-haiku-20240307"):
    """scene/mood/position_hint/tags가 비어 있는 이미지를 Claude Vision으로 태깅"""
    ws = spreadsheet.worksheet("이미지 메타데이터")
    rows = ws.get_all_values()
    if len(rows) < 2:
        print("  → 태깅할 이미지 없음")
        return

    # scene이 비어 있는 행 찾기
    to_tag = []
    for i, row in enumerate(rows[1:], start=2):  # 2행부터 (1행=헤더)
        if len(row) >= 5 and row[0].strip() and not row[4].strip():
            to_tag.append((i, row))

    if not to_tag:
        print("  → 태깅이 필요한 이미지 없음 (모두 완료)")
        return

    print(f"  → {len(to_tag)}개 이미지 AI 태깅 시작...")
    tagged = 0

    for idx, (row_num, row) in enumerate(to_tag):
        file_id = row[0].strip()
        filename = row[1].strip()
        product = row[2].strip() if len(row) > 2 else ""
        category = row[3].strip() if len(row) > 3 else ""

        try:
            # 이미지 다운로드 (bytes)
            img_bytes = lc.drive_download_bytes(service, file_id)

            # 맥락 포함 프롬프트 생성
            vision_prompt = VISION_PROMPT_TEMPLATE.format(
                product=product, category=category, filename=filename
            )

            # Claude Vision 호출
            result = lc.call_claude_vision_sync(api_key, img_bytes, vision_prompt, max_tokens=512, model=model, filename=filename)

            # 결과 파싱
            if not result:
                print(f"  [오류] {filename}: Vision API 응답이 비어있음 (스킵)")
                continue
            scene = mood = position_hint = tags = ""
            for line in result.strip().split('\n'):
                line = line.strip()
                if line.startswith('scene:'):
                    scene = line[6:].strip()
                elif line.startswith('mood:'):
                    mood = line[5:].strip()
                elif line.startswith('position_hint:'):
                    position_hint = line[14:].strip()
                elif line.startswith('tags:'):
                    tags = line[5:].strip()

            # 시트 업데이트 (E, F, G, H 열)
            ws.update(f'E{row_num}:H{row_num}', [[scene, mood, position_hint, tags]])
            tagged += 1
            print(f"  [{tagged}/{len(to_tag)}] {filename}: scene={scene}, mood={mood}")

        except Exception as e:
            print(f"  [오류] {filename}: {e}")
            # 실패한 이미지에 표시 → 다음 실행 때 재시도 안 함
            try:
                ws.update(f'E{row_num}', [["[태깅실패]"]])
            except Exception:
                pass

        # API 속도 제한 대비
        if (idx + 1) % batch_size == 0:
            print(f"  → {batch_size}개 처리 후 잠시 대기...")
            time.sleep(delay * 5)
        else:
            time.sleep(delay)

    print(f"  → AI 태깅 완료: {tagged}/{len(to_tag)}개 성공")


def main():
    parser = argparse.ArgumentParser(description="Drive 이미지 스캔 + AI 태깅 → 시트 등록")
    parser.add_argument("--drive-folder-id", required=True, help="Drive 이미지 라이브러리 폴더 ID")
    parser.add_argument("--sheet-id", required=True, help="Google Sheets ID")
    parser.add_argument("--tag", action="store_true", help="Claude Vision AI 자동 태깅 실행")
    parser.add_argument("--cred", default=None, help="credentials.json 경로 (기본: 프로그램 폴더)")
    parser.add_argument("--api-key", default=None, help="Claude API Key (태깅 시 필수)")
    parser.add_argument("--model", default="claude-3-haiku-20240307", help="Vision 모델 (기본: claude-3-haiku)")
    args = parser.parse_args()

    paths = lc.make_paths()
    cred_file = args.cred or paths["cred_file"]

    # 1. Drive 연결
    drive_service, err = lc.connect_drive(cred_file)
    if err:
        print(f"[오류] {err}")
        sys.exit(1)

    # 2. Sheets 연결
    spreadsheet, err = lc.connect_sheet(args.sheet_id, cred_file)
    if err:
        print(f"[오류] {err}")
        sys.exit(1)

    # 3. 시트 탭 확인/생성
    ensure_sheet_tab(spreadsheet)

    # 4. Drive 스캔
    images = scan_drive_images(drive_service, args.drive_folder_id)

    # 5. 시트 등록
    new_images = register_images(spreadsheet, images)

    # 6. AI 태깅 (옵션)
    if args.tag:
        api_key = args.api_key or lc.load_api_key(paths["api_key_file"])
        if not api_key:
            print("[오류] AI 태깅에 Claude API Key가 필요합니다. --api-key 또는 .api_key 파일")
            sys.exit(1)
        tag_images_with_vision(api_key, drive_service, spreadsheet, model=args.model)

    print("\n완료!")


if __name__ == "__main__":
    main()
