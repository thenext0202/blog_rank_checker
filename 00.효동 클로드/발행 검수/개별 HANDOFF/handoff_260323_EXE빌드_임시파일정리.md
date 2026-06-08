# 🔧 Handoff — EXE 빌드 + 임시파일 자동 정리 (2026-03-23)

---

## 📋 작업 요약

| 항목 | 내용 |
|------|------|
| 버전 | v1.6 → v1.7 |
| 파일 | `발행검수\main.py` |
| 목적 | 다른 사람이 Python 없이 사용할 수 있도록 EXE 빌드 + 임시 DOCX 파일 자동 정리 |

---

## 🔨 변경 사항

### 1. `BASE_DIR` / `CRED_FILE` 경로 분기 (line 29~39)

**Before:**
```python
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CRED_FILE = os.path.join(os.path.dirname(BASE_DIR), "manuscript_generator", "credentials.json")
```

**After:**
```python
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_cred_local = os.path.join(BASE_DIR, "credentials.json")
_cred_orig = os.path.join(os.path.dirname(BASE_DIR), "manuscript_generator", "credentials.json")
CRED_FILE = _cred_local if os.path.exists(_cred_local) else _cred_orig
```

- `sys.frozen` — PyInstaller로 빌드된 EXE에서만 `True`
- EXE 옆 `credentials.json`을 우선 탐색 → 없으면 기존 경로 fallback

### 2. `find_and_download()` 반환값 변경

**Before:** `return dl_path` / `return None`
**After:** `return (dl_path, tmp_dir)` / `return (None, None)`

- 임시 폴더 경로를 호출부에 전달하기 위해 튜플 반환

### 3. `import shutil` 추가 (line 8)

### 4. 임시파일 수집 + 정리 (검수 워크플로우)

```python
# 수집
tmp_dirs = []
path, tmp_dir = find_and_download(creds, fn)
if tmp_dir:
    tmp_dirs.append(tmp_dir)

# 정리 (검수 완료 또는 중단 시)
self._cleanup_tmp(tmp_dirs)
```

### 5. `_cleanup_tmp()` 메서드 추가

```python
def _cleanup_tmp(self, tmp_dirs):
    for d in tmp_dirs:
        try:
            shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass
```

---

## 📦 빌드 결과

```
발행검수\dist\
  ├─ 발행검수.exe       (47MB)
  └─ credentials.json   (서비스 계정 키)
```

빌드 명령어: `python -m PyInstaller --onefile --windowed --name "발행검수" main.py`

---

## ⚠️ 주의사항

- `find_and_download()`가 이제 **튜플**을 반환하므로, 이 함수를 호출하는 다른 코드가 있으면 언패킹 수정 필요
- 현재는 `main.py` 내부에서만 호출하므로 문제 없음
