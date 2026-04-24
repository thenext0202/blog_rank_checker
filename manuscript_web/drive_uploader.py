"""Google Drive 업로드 — .docx bytes → 폴더에 저장 후 공유 가능 링크 반환.

manuscript_generator/data_loader.py 패턴 재사용 + bytes 업로드로 확장.
"""
import io

from config import get_credentials_path, load_drive_folder_id

SCOPES = [
    "https://www.googleapis.com/auth/drive",
]


def _connect_drive():
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    creds = Credentials.from_service_account_file(
        get_credentials_path(), scopes=SCOPES
    )
    return build('drive', 'v3', credentials=creds, cache_discovery=False)


def upload_docx_bytes(docx_bytes, filename, folder_id=None, make_anyone_readable=True):
    """.docx bytes를 드라이브 폴더에 업로드.

    Returns:
        (file_id, web_view_link) 튜플. 실패 시 (None, None).
    """
    from googleapiclient.http import MediaIoBaseUpload
    if not docx_bytes:
        return None, None
    if not filename.lower().endswith('.docx'):
        filename += '.docx'

    folder = (folder_id or load_drive_folder_id() or '').strip()
    if not folder:
        return None, None

    try:
        service = _connect_drive()
        media = MediaIoBaseUpload(
            io.BytesIO(docx_bytes),
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            resumable=False,
        )
        created = service.files().create(
            body={'name': filename, 'parents': [folder]},
            media_body=media,
            fields='id, webViewLink',
            supportsAllDrives=True,
        ).execute()
        file_id = created.get('id')
        link = created.get('webViewLink') or f"https://drive.google.com/file/d/{file_id}/view"

        # 링크 있는 사람 보기 권한 부여 (시트에서 클릭 시 열리도록)
        if make_anyone_readable and file_id:
            try:
                service.permissions().create(
                    fileId=file_id,
                    body={'role': 'reader', 'type': 'anyone'},
                    supportsAllDrives=True,
                ).execute()
            except Exception as e:
                print(f"[drive_uploader] 권한 부여 실패(무시): {e}")

        return file_id, link
    except Exception as e:
        print(f"[drive_uploader] 업로드 실패: {e}")
        return None, None
