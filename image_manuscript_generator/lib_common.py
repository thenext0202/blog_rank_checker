"""
lib_common.py — 기존 원고 제작기(manuscript_generator/main.py)에서 추출한 공용 함수
이미지 기반 원고 제작기 + 기존 원고 제작기 양쪽에서 사용

포함 기능:
  - 경로/설정 관리
  - Google Sheets / Drive 연결 및 동기화
  - 시트 데이터 로딩 (6탭 + 이미지 메타데이터)
  - 참고자료 / 샘플 로딩
  - Claude API 호출
  - ㄴ서식 파싱 + Word 출력
  - 프롬프트 조립 (build_prompt)
  - 페르소나 / 제목 프롬프트
  - 생성 이력 관리
"""
import os
import sys
import re
import json
import threading
import datetime

try:
    import gspread
    from google.oauth2.service_account import Credentials
    HAS_GSPREAD = True
except ImportError:
    HAS_GSPREAD = False


# ╔══════════════════════════════════════════════════════════════╗
# ║  1. 경로 / 설정                                              ║
# ╚══════════════════════════════════════════════════════════════╝

def base_dir():
    """실행 파일(EXE) 또는 스크립트 기준 디렉토리"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def make_paths(root=None):
    """프로그램 경로 dict 반환. root를 지정하면 해당 경로 기준."""
    root = root or base_dir()
    paths = {
        "root": root,
        "references": os.path.join(root, "references"),
        "samples": os.path.join(root, "samples"),
        "output": os.path.join(root, "output"),
        "image_cache": os.path.join(root, "image_cache"),
        "api_key_file": os.path.join(root, ".api_key"),
        "cred_file": os.path.join(root, "credentials.json"),
        "sheet_config_file": os.path.join(root, ".sheet_id"),
        "log_file": os.path.join(root, "generation_log.json"),
    }
    for d in ["references", "samples", "output", "image_cache"]:
        os.makedirs(paths[d], exist_ok=True)
    return paths


# ╔══════════════════════════════════════════════════════════════╗
# ║  2. 파일 읽기                                                ║
# ╚══════════════════════════════════════════════════════════════╝

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


# ╔══════════════════════════════════════════════════════════════╗
# ║  3. Google Sheets / Drive 연결                               ║
# ╚══════════════════════════════════════════════════════════════╝

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _get_creds(cred_file):
    """서비스 계정 인증 객체 반환"""
    return Credentials.from_service_account_file(cred_file, scopes=SCOPES)


def connect_sheet(sheet_id, cred_file):
    if not HAS_GSPREAD:
        return None, "gspread 미설치. pip install gspread google-auth"
    if not os.path.exists(cred_file):
        return None, f"credentials.json 없음: {cred_file}"
    try:
        creds = _get_creds(cred_file)
        gc = gspread.authorize(creds)
        return gc.open_by_key(sheet_id), None
    except Exception as e:
        return None, f"시트 연결 실패: {e}"


def connect_drive(cred_file):
    if not os.path.exists(cred_file):
        return None, f"credentials.json 없음: {cred_file}"
    try:
        from googleapiclient.discovery import build as _build_service
        creds = _get_creds(cred_file)
        service = _build_service('drive', 'v3', credentials=creds)
        return service, None
    except Exception as e:
        return None, f"드라이브 연결 실패: {e}"


# ╔══════════════════════════════════════════════════════════════╗
# ║  4. Google Drive 파일 관리                                    ║
# ╚══════════════════════════════════════════════════════════════╝

def drive_list_files(service, folder_id):
    """드라이브 폴더 내 파일/폴더 목록 반환."""
    items = []
    page_token = None
    while True:
        resp = service.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields='nextPageToken, files(id, name, mimeType, modifiedTime)',
            pageSize=200,
            pageToken=page_token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        items.extend(resp.get('files', []))
        page_token = resp.get('nextPageToken')
        if not page_token:
            break
    return items


def drive_list_files_recursive(service, folder_id, path_prefix=""):
    """드라이브 폴더를 재귀 탐색하여 모든 파일을 flat list로 반환.
    각 항목에 'path' 키 추가 (폴더 경로)."""
    items = drive_list_files(service, folder_id)
    result = []
    for item in items:
        item['path'] = path_prefix
        if item['mimeType'] == 'application/vnd.google-apps.folder':
            sub_path = f"{path_prefix}/{item['name']}" if path_prefix else item['name']
            result.extend(drive_list_files_recursive(service, item['id'], sub_path))
        else:
            result.append(item)
    return result


def drive_download(service, file_id, dest_path):
    """드라이브 파일을 로컬에 다운로드."""
    from googleapiclient.http import MediaIoBaseDownload
    import io as _io
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    fh = _io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with open(dest_path, 'wb') as f:
        f.write(fh.getvalue())


def drive_download_bytes(service, file_id):
    """드라이브 파일을 bytes로 반환 (로컬 저장 없이)."""
    from googleapiclient.http import MediaIoBaseDownload
    import io as _io
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    fh = _io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return fh.getvalue()


def sync_drive_folder(service, drive_folder_id, local_dir, callback=None):
    """드라이브 폴더 → 로컬 폴더 동기화."""
    items = drive_list_files(service, drive_folder_id)
    downloaded = 0
    skipped = 0
    for item in items:
        if item['mimeType'] == 'application/vnd.google-apps.folder':
            sub_dir = os.path.join(local_dir, item['name'])
            os.makedirs(sub_dir, exist_ok=True)
            d, s = sync_drive_folder(service, item['id'], sub_dir, callback)
            downloaded += d
            skipped += s
        else:
            dest = os.path.join(local_dir, item['name'])
            if os.path.exists(dest):
                from datetime import timezone
                local_mtime = datetime.datetime.fromtimestamp(
                    os.path.getmtime(dest), tz=timezone.utc)
                drive_mtime = datetime.datetime.fromisoformat(
                    item['modifiedTime'].replace('Z', '+00:00'))
                if local_mtime >= drive_mtime:
                    skipped += 1
                    continue
            if callback:
                callback(item['name'])
            drive_download(service, item['id'], dest)
            downloaded += 1
    return downloaded, skipped


def upload_to_drive(service, local_path, drive_folder_id):
    """로컬 파일을 드라이브 폴더에 업로드."""
    from googleapiclient.http import MediaFileUpload
    fname = os.path.basename(local_path)
    file_metadata = {'name': fname, 'parents': [drive_folder_id]}
    media = MediaFileUpload(local_path, resumable=True)
    service.files().create(
        body=file_metadata, media_body=media,
        fields='id', supportsAllDrives=True,
    ).execute()


# ╔══════════════════════════════════════════════════════════════╗
# ║  5. 시트 데이터 로딩                                          ║
# ╚══════════════════════════════════════════════════════════════╝

def load_all_from_sheet(spreadsheet):
    """기존 6탭 데이터 로딩 (프롬프트, 작가스타일, 공통지침, 제품소구점, 서식규칙, 참고논문)"""
    data = {
        "prompts": {}, "styles": {}, "guidelines": [],
        "products": {}, "product_links": {}, "product_codes": {},
        "format_instructions": "", "papers": {},
    }

    try:
        ws = spreadsheet.worksheet("프롬프트")
        for row in ws.get_all_values()[1:]:
            if len(row) >= 2 and row[0].strip():
                data["prompts"][row[0].strip()] = row[1].strip()
    except Exception:
        pass

    try:
        ws = spreadsheet.worksheet("작가스타일")
        for row in ws.get_all_values()[1:]:
            if len(row) >= 2 and row[0].strip():
                data["styles"][row[0].strip()] = row[1].strip()
    except Exception:
        pass

    try:
        ws = spreadsheet.worksheet("공통지침")
        for row in ws.get_all_values()[1:]:
            if len(row) >= 2 and row[1].strip():
                data["guidelines"].append(row[1].strip())
    except Exception:
        pass

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

    try:
        ws = spreadsheet.worksheet("서식규칙")
        for row in ws.get_all_values()[1:]:
            if len(row) >= 2 and row[0].strip() == "format_instructions":
                data["format_instructions"] = row[1].strip()
                break
    except Exception:
        pass

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

    return data


def load_image_metadata_from_sheet(spreadsheet):
    """이미지 메타데이터 탭 로딩 → [dict, ...] 반환
    컬럼: A:drive_file_id, B:filename, C:product, D:category,
          E:scene, F:mood, G:position_hint, H:tags, I:drive_folder, J:thumbnail_url
    """
    try:
        ws = spreadsheet.worksheet("이미지 메타데이터")
        rows = ws.get_all_values()
        if len(rows) < 2:
            return []
        result = []
        for row in rows[1:]:
            if len(row) < 2 or not row[0].strip():
                continue
            entry = {
                "drive_file_id": row[0].strip() if len(row) > 0 else "",
                "filename": row[1].strip() if len(row) > 1 else "",
                "product": row[2].strip() if len(row) > 2 else "공통",
                "category": row[3].strip() if len(row) > 3 else "",
                "scene": row[4].strip() if len(row) > 4 else "",
                "mood": row[5].strip() if len(row) > 5 else "",
                "position_hint": row[6].strip() if len(row) > 6 else "any",
                "tags": row[7].strip() if len(row) > 7 else "",
                "drive_folder": row[8].strip() if len(row) > 8 else "",
                "thumbnail_url": row[9].strip() if len(row) > 9 else "",
            }
            result.append(entry)
        return result
    except Exception:
        return []


# ╔══════════════════════════════════════════════════════════════╗
# ║  6. 참고자료 / 샘플 로딩                                      ║
# ╚══════════════════════════════════════════════════════════════╝

VALID_REF_EXTS = ('.txt', '.md', '.csv', '.docx', '.pdf')

PRODUCT_CODE_MAP = {
    "hc": "헬리컷", "bc": "블러드싸이클", "gc": "글루코컷",
    "sc": "상어연골환", "pt": "퓨어톤 부스트", "po": "판토오틴",
    "ml": "멜라토닌", "af": "액티플 활성엽산",
}

KNOWN_PROMPT_TYPES = [
    '1인칭 경험담', '시나리오형(수치)', '시나리오형(질병)',
    '공감 정보형', 'GEO 정보성', '독자 칼럼',
    '수치 충격형', '돌발 증상형', '증상 악화 진행형',
    '정보 탐색 큐레이션형', '제3자 관찰형',
    '후기형(ver3)', '후기형(ver2)', '원료기반형', '에어서치',
]


def _get_product_code(product_name, sheet_data=None):
    if sheet_data and sheet_data.get("product_codes", {}).get(product_name):
        return sheet_data["product_codes"][product_name]
    for code, name in PRODUCT_CODE_MAP.items():
        if name == product_name:
            return code
    return ""


def _load_refs_from_dir(dirpath, prefix=""):
    refs = {}
    if not os.path.exists(dirpath):
        return refs
    for fname in os.listdir(dirpath):
        fpath = os.path.join(dirpath, fname)
        if os.path.isfile(fpath) and os.path.splitext(fname)[1].lower() in VALID_REF_EXTS:
            display_name = f"[{prefix}] {fname}" if prefix else fname
            refs[display_name] = read_file_content(fpath)
    return refs


def load_refs_for_product(refs_dir, product_name=""):
    refs = {}
    common_dir = os.path.join(refs_dir, "공통")
    refs.update(_load_refs_from_dir(common_dir, "공통"))
    if product_name:
        product_dir = os.path.join(refs_dir, product_name)
        refs.update(_load_refs_from_dir(product_dir, product_name))
    return refs


def _parse_sample_filename(fname):
    name = os.path.splitext(fname)[0]
    if name.startswith('참고원고_'):
        type_part = name.replace('참고원고_', '').replace('_', ' ')
        for t in KNOWN_PROMPT_TYPES:
            if t == type_part:
                return t, ""
        return None, ""
    parts = name.split('_')
    prompt_type = None
    for t in KNOWN_PROMPT_TYPES:
        if t in parts:
            prompt_type = t
            break
    product_code = parts[-1].split('(')[0].strip() if parts else ""
    return prompt_type, product_code


def load_sample_for_type(samples_dir, prompt_type, product_name="", sheet_data=None):
    import random
    if not os.path.exists(samples_dir):
        return "", ""
    target_code = _get_product_code(product_name, sheet_data)
    same_product = []
    other_product = []
    for fname in os.listdir(samples_dir):
        if not (fname.endswith('.docx') or fname.endswith('.txt')):
            continue
        ftype, fcode = _parse_sample_filename(fname)
        if ftype == prompt_type:
            if target_code and fcode == target_code:
                same_product.append(fname)
            else:
                other_product.append(fname)
    pool = same_product if same_product else other_product
    if not pool:
        return "", ""
    selected = random.choice(pool)
    content = read_file_content(os.path.join(samples_dir, selected))
    if len(content) > 4000:
        content = content[:4000] + "\n... (이하 생략)"
    return selected, content


# ╔══════════════════════════════════════════════════════════════╗
# ║  7. API Key / Sheet ID / Log 관리                            ║
# ╚══════════════════════════════════════════════════════════════╝

def load_api_key(api_key_file):
    if os.path.exists(api_key_file):
        with open(api_key_file, 'r') as f:
            return f.read().strip()
    return ""


def save_api_key(api_key_file, key):
    with open(api_key_file, 'w') as f:
        f.write(key.strip())


def load_sheet_id(sheet_config_file):
    if os.path.exists(sheet_config_file):
        with open(sheet_config_file, 'r') as f:
            return f.read().strip()
    return ""


def save_sheet_id(sheet_config_file, sid):
    with open(sheet_config_file, 'w') as f:
        f.write(sid.strip())


def load_generation_log(log_file):
    if os.path.exists(log_file):
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_generation_log(log_file, log):
    with open(log_file, 'w', encoding='utf-8') as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def append_log_entry(log_file, product, prompt_type, persona, title, char_count, filepath, sample_used=""):
    log = load_generation_log(log_file)
    log.append({
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "product": product,
        "prompt_type": prompt_type,
        "persona": persona[:100] if persona else "",
        "title": title[:100] if title else "",
        "char_count": char_count,
        "saved_file": os.path.basename(filepath) if filepath else "",
        "sample_used": sample_used,
    })
    if len(log) > 200:
        log = log[-200:]
    save_generation_log(log_file, log)


# ╔══════════════════════════════════════════════════════════════╗
# ║  8. Claude API 호출                                          ║
# ╚══════════════════════════════════════════════════════════════╝

def call_claude_api(api_key, prompt, on_complete, on_error, max_tokens=8192, model="claude-sonnet-4-20250514"):
    """Claude API를 스레드에서 호출. on_complete(text), on_error(str)."""
    def _run():
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            message = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}]
            )
            on_complete(message.content[0].text)
        except Exception as e:
            on_error(str(e))
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


def call_claude_api_sync(api_key, prompt, max_tokens=8192, model="claude-sonnet-4-20250514"):
    """Claude API 동기 호출 → text 반환."""
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text


def call_claude_vision_sync(api_key, image_bytes, prompt, max_tokens=1024,
                            model="claude-sonnet-4-20250514", filename=""):
    """Claude Vision API 동기 호출 — 이미지(bytes) + 텍스트 프롬프트."""
    import anthropic
    import base64
    client = anthropic.Anthropic(api_key=api_key)
    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    # 파일 확장자로 media_type 결정
    ext = os.path.splitext(filename)[1].lower() if filename else ""
    media_map = {'.png': 'image/png', '.gif': 'image/gif', '.webp': 'image/webp', '.bmp': 'image/bmp'}
    media_type = media_map.get(ext, 'image/jpeg')

    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": b64},
                },
                {"type": "text", "text": prompt},
            ]
        }]
    )
    return message.content[0].text


# ╔══════════════════════════════════════════════════════════════╗
# ║  9. ㄴ서식 파싱                                               ║
# ╚══════════════════════════════════════════════════════════════╝

def parse_annotation(annotation_text):
    """ㄴ 서식 지시 줄 → 서식 딕셔너리"""
    from docx.enum.text import WD_COLOR_INDEX
    text = annotation_text.lstrip('ㄴ').strip()
    fmt = {
        'font_size': None, 'bold': False, 'italic': False,
        'colored_words': [], 'full_text_color': None,
        'highlight': None, 'quote': None, 'link': False,
        'multi_line': 1, 'is_image_desc': False,
    }
    if text.startswith('(') and text.endswith(')'):
        fmt['is_image_desc'] = True
        return fmt

    m = re.search(r'인용구\s*(\d+)\s*번', text)
    if m:
        fmt['quote'] = int(m.group(1))

    VALID_FONT_SIZES = [11, 13, 15, 16, 19, 24, 28]
    m = re.search(r'글자\s*크기\s*(\d+)', text)
    if m:
        requested = int(m.group(1))
        fmt['font_size'] = min(VALID_FONT_SIZES, key=lambda x: abs(x - requested))

    if re.search(r'글꼴\s*두껍게|두껍게', text):
        fmt['bold'] = True
    if re.search(r'이탤릭|기울임|글꼴\s*기울임', text):
        fmt['italic'] = True

    full_color_map = {
        '옅은 회색': '옅은회색', '많이 옅은 회색': '많이옅은회색',
        '회색': '회색', '진한 회색': '진한회색',
        '빨간색': '빨간색', '파란색': '파란색', '청록색': '청록색',
        '초록색': '초록색', '보라색': '보라색', '주황색': '주황색',
    }
    for pattern, color_key in full_color_map.items():
        if re.search(rf'글자\s*색\s*{re.escape(pattern)}', text):
            fmt['full_text_color'] = color_key
            break

    color_names = ['빨간색', '파란색', '청록색', '초록색', '보라색', '주황색', '회색']
    for color_name in color_names:
        m = re.search(rf"((?:'[^']+'\s*,?\s*)+)\s*{color_name}", text)
        if m:
            words = re.findall(r"'([^']+)'", m.group(1))
            for w in words:
                fmt['colored_words'].append((w, color_name))

    highlight_map = {
        '노란|노랑': WD_COLOR_INDEX.YELLOW,
        '검정|검은': WD_COLOR_INDEX.BLACK,
        '파란|파랑': WD_COLOR_INDEX.BLUE,
        '빨간|빨강': WD_COLOR_INDEX.RED,
        '초록': WD_COLOR_INDEX.GREEN,
        '청록': WD_COLOR_INDEX.TEAL,
    }
    for hl_pattern, hl_val in highlight_map.items():
        if re.search(rf'(?:{hl_pattern})색?\s*형광펜', text):
            fmt['highlight'] = hl_val
            break

    if '링크도구로연결' in text:
        fmt['link'] = True

    num_map = {'두': 2, '세': 3, '네': 4, '다섯': 5}
    m = re.search(r'(두|세|네|다섯)\s*줄\s*모두', text)
    if m:
        fmt['multi_line'] = num_map.get(m.group(1), 1)

    return fmt


def is_format_annotation(text):
    """ㄴ로 시작하는 줄이 서식 지시인지 판별."""
    stripped = text.lstrip('ㄴ').strip()
    if stripped.startswith('(') and stripped.endswith(')'):
        return True
    if re.search(r'글자\s*크기|글꼴\s*두껍게|두껍게|형광펜|인용구|이탤릭|기울임|링크도구|줄\s*모두|글자\s*색', stripped):
        return True
    if re.search(r"'[^']+'\s*(빨간색|파란색|청록색|초록색|보라색|주황색|회색)", stripped):
        return True
    return False


# ╔══════════════════════════════════════════════════════════════╗
# ║  10. Word 출력 (save_as_docx)                                ║
# ╚══════════════════════════════════════════════════════════════╝
# Word 출력은 기존 main.py에서 그대로 사용 (save_as_docx 함수)
# 여기서는 헬퍼 함수들만 제공하고, save_as_docx는 기존 main.py 참조
# → 추후 필요시 이 파일로 이동

def get_color_name_to_rgb():
    from docx.shared import RGBColor
    return {
        '빨간색': RGBColor(0xFF, 0x00, 0x00),
        '파란색': RGBColor(0x00, 0x70, 0xC0),
        '청록색': RGBColor(0x00, 0x80, 0x80),
        '초록색': RGBColor(0x00, 0x80, 0x00),
        '보라색': RGBColor(0x70, 0x30, 0xA0),
        '주황색': RGBColor(0xED, 0x7D, 0x31),
        '회색': RGBColor(0x80, 0x80, 0x80),
        '많이옅은회색': RGBColor(0xC0, 0xC0, 0xC0),
        '옅은회색': RGBColor(0xA0, 0xA0, 0xA0),
        '진한회색': RGBColor(0x50, 0x50, 0x50),
    }


# ╔══════════════════════════════════════════════════════════════╗
# ║  11. 프롬프트 템플릿 (페르소나 / 제목)                          ║
# ╚══════════════════════════════════════════════════════════════╝

PERSONA_PROMPT_TEMPLATE = """당신은 건강/의학 블로그 원고 전문가입니다.

아래 정보를 바탕으로 블로그 원고에 적합한 **블로거 페르소나 3개**를 제안해주세요.

[제품 정보]
- 제품: {product_name}
{product_guide}

[원고 유형]
{prompt_type}

[메인 키워드]
{keywords}

[작가 스타일]
{style_desc}

[문체]
{tone}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
■ 블로거 페르소나 3개 제안
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[페르소나 설계 규칙]
- 제품과 키워드에 맞는 실존감 있는 인물
- 각 페르소나는 아래 형식으로 작성:

[페르소나 A]
· 나이·성별·직업:
· 생활 습관 (건강 문제가 생긴 이유):
· 계기 (제품을 알게 된 배경):
· 성격/문체 톤: (예: 담담한 사무직 / 걱정 많은 주부 / 자기비판형 중년 남성)

[페르소나 B]
(동일 형식)

[페르소나 C]
(동일 형식)

위 형식을 정확히 따라 3개의 페르소나를 제안해주세요. 다른 설명은 필요 없습니다."""


PERSONA_PROMPT_3RD = """당신은 건강/의학 블로그 원고 전문가입니다.

아래 정보를 바탕으로 **제3자 관찰형** 원고에 적합한 **관찰 대상 페르소나 3개**를 제안해주세요.
이 페르소나는 블로그 글의 주인공이 아니라, 블로거(관찰자)가 곁에서 지켜보는 '대상 인물'입니다.

[제품 정보]
- 제품: {product_name}
{product_guide}

[원고 유형]
{prompt_type}

[메인 키워드]
{keywords}

[작가 스타일]
{style_desc}

[문체]
{tone}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
■ 관찰 대상 페르소나 3개 제안
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[페르소나 설계 규칙]
- 제품과 키워드에 맞는 실존감 있는 인물
- 이 인물은 '관찰 대상'이며, 블로거가 이 사람의 변화를 곁에서 지켜봅니다

[페르소나 A]
· 관찰 대상: 나이·성별·직업 (블로거와의 관계: 예-엄마, 남편, 직장 동료)
· 생활 습관 (건강 문제가 생긴 이유):
· 계기 (제품을 알게 된 배경):
· 관찰자 시점: (예: 딸이 엄마의 변화를 지켜봄)

[페르소나 B]
(동일 형식)

[페르소나 C]
(동일 형식)

위 형식을 정확히 따라 3개의 페르소나를 제안해주세요. 다른 설명은 필요 없습니다."""


TITLE_PROMPT_TEMPLATE = """당신은 건강/의학 블로그 SEO 전문가입니다.

아래 정보를 바탕으로 블로그 원고에 적합한 **제목 3개**를 제안해주세요.

[제품 정보]
- 제품: {product_name}

[원고 유형]
{prompt_type}

[메인 키워드]
{keywords}

[연관 키워드]
{sub_keywords}

[블로거 페르소나]
{persona}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
■ 블로그 제목 3개 제안
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[제목 설계 규칙]
- 메인 키워드를 자연스럽게 포함
- 클릭을 유도하는 호기심 자극형 제목
- 네이버 블로그 SEO에 최적화
- 페르소나의 시점/상황이 반영된 제목
- 각 제목은 공백 포함 24자 이내로 작성
- 각 제목은 서로 다른 스타일로:

[제목 A]
(제목 텍스트)

[제목 B]
(제목 텍스트)

[제목 C]
(제목 텍스트)

위 형식을 정확히 따라 3개의 제목을 제안해주세요. 다른 설명은 필요 없습니다."""


def build_persona_prompt(sheet_data, product_name, prompt_type, style_name, tone, keywords):
    product_guide = sheet_data["products"].get(product_name, "")
    style_desc = sheet_data["styles"].get(style_name, "스타일 지정 없음")
    tone_text = "존댓말 (정중하면서도 친근한 톤)" if tone == "존댓말" else "반말 (친구에게 말하듯 편안한 톤)"
    template = PERSONA_PROMPT_3RD if "제3자" in prompt_type else PERSONA_PROMPT_TEMPLATE
    return template.format(
        product_name=product_name,
        product_guide=product_guide[:3000] if product_guide else "(제품 가이드 없음)",
        prompt_type=prompt_type,
        keywords=keywords or "(키워드 미입력)",
        style_desc=style_desc,
        tone=tone_text,
    )


def build_title_prompt(product_name, prompt_type, keywords, sub_keywords, persona_text):
    return TITLE_PROMPT_TEMPLATE.format(
        product_name=product_name,
        prompt_type=prompt_type,
        keywords=keywords or "(키워드 미입력)",
        sub_keywords=sub_keywords or "(연관 키워드 없음)",
        persona=persona_text or "(페르소나 미선택)",
    )


# ╔══════════════════════════════════════════════════════════════╗
# ║  12. GUI 테마                                                ║
# ╚══════════════════════════════════════════════════════════════╝

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
    "text_fg": "#000000",
    "inspect_bg": "#333333",
    "inspect_chars": "#66cc66",
    "inspect_kw": "#66ccff",
    "inspect_img": "#ffcc33",
}


def setup_styles():
    """ttk 스타일 설정"""
    from tkinter import ttk
    s = ttk.Style()
    s.theme_use('clam')
    s.configure('.', font=('맑은 고딕', 9))
    s.configure('TLabelframe.Label', font=('맑은 고딕', 10, 'bold'))
    s.configure('TNotebook.Tab', padding=[14, 5], font=('맑은 고딕', 10))
    s.configure('Generate.TButton', font=('맑은 고딕', 11, 'bold'), padding=9)
    s.configure('Refresh.TButton', font=('맑은 고딕', 9, 'bold'))
    s.configure('Sash', sashthickness=6, gripcount=0)
