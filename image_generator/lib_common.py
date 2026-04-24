"""
lib_common.py — image_metadata.py / image_selector.py가 사용하는 공용 함수 브릿지

manuscript_generator/main.py의 함수를 재노출하거나,
image_manuscript_generator/lib_common.py에만 있던 함수를 여기에 추가.
"""
import os
import sys
import threading

# ── 경로 ──
def base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

CRED_FILE = os.path.join(base_dir(), "credentials.json")

IMAGE_CACHE_DIR = os.path.join(base_dir(), "image_cache")
os.makedirs(IMAGE_CACHE_DIR, exist_ok=True)


# ── Google Sheets 연결 (main.py와 동일) ──
def connect_sheet(sheet_id, cred_file=None):
    cred_file = cred_file or CRED_FILE
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        return None, "gspread 미설치"
    if not os.path.exists(cred_file):
        return None, f"credentials.json 없음: {cred_file}"
    try:
        scope = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(cred_file, scopes=scope)
        gc = gspread.authorize(creds)
        return gc.open_by_key(sheet_id), None
    except Exception as e:
        return None, f"시트 연결 실패: {e}"


# ── Google Drive 연결 ──
def connect_drive(cred_file=None):
    cred_file = cred_file or CRED_FILE
    if not os.path.exists(cred_file):
        return None, f"credentials.json 없음: {cred_file}"
    try:
        from googleapiclient.discovery import build as _build_service
        from google.oauth2.service_account import Credentials
        scope = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(cred_file, scopes=scope)
        service = _build_service('drive', 'v3', credentials=creds)
        return service, None
    except Exception as e:
        return None, f"드라이브 연결 실패: {e}"


# ── Drive 파일 bytes 다운로드 ──
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


# ── 이미지 메타데이터 시트 로딩 ──
def load_image_metadata_from_sheet(spreadsheet):
    """이미지 메타데이터 탭 로딩 → [dict, ...] 반환"""
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


# ── Claude API 동기 호출 ──
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


# ── Claude API 비동기 호출 ──
def call_claude_api(api_key, prompt, on_complete, on_error, max_tokens=8192, model="claude-sonnet-4-20250514"):
    """Claude API를 스레드에서 호출."""
    def _run():
        try:
            result = call_claude_api_sync(api_key, prompt, max_tokens, model)
            on_complete(result)
        except Exception as e:
            on_error(str(e))
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


# ── Gemini 임베딩 API ──
def get_embeddings(api_key, texts, model="gemini-embedding-001"):
    """텍스트 리스트를 임베딩 벡터로 변환 (Gemini).

    Returns:
        list[list[float]]: 각 텍스트의 임베딩 벡터
    """
    from google import genai

    client = genai.Client(api_key=api_key)

    # Gemini 배치 제한: 100개씩 나눠서 호출
    all_embeddings = []
    batch_size = 100
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        result = client.models.embed_content(
            model=model,
            contents=batch,
        )
        for emb in result.embeddings:
            all_embeddings.append(emb.values)

    return all_embeddings


# ── Gemini Vision API (이미지 분석) ──
def analyze_image_vision(api_key, image_bytes, prompt, model="gemini-2.5-flash"):
    """이미지를 Gemini Vision에 보내서 텍스트 응답 받기.

    Args:
        api_key: Gemini API 키
        image_bytes: 이미지 바이너리 데이터
        prompt: 분석 요청 프롬프트
        model: 사용할 모델

    Returns:
        str: AI 응답 텍스트
    """
    from google import genai

    client = genai.Client(api_key=api_key)

    # 이미지 포맷 판별
    if image_bytes[:8].startswith(b'\x89PNG'):
        mime = "image/png"
    elif image_bytes[:2] == b'\xff\xd8':
        mime = "image/jpeg"
    elif image_bytes[:4] == b'RIFF':
        mime = "image/webp"
    else:
        mime = "image/jpeg"

    response = client.models.generate_content(
        model=model,
        contents=[
            prompt,
            genai.types.Part.from_bytes(data=image_bytes, mime_type=mime),
        ],
    )
    return response.text
