"""
image_metadata.py — 이미지 메타데이터 로딩, 검색, 썸네일 캐싱

기능:
  - 시트에서 메타데이터 로딩 → 메모리 캐시
  - 조건 기반 필터링 (제품, 카테고리, mood, tags 등)
  - 텍스트 검색 (scene + tags 매칭)
  - 썸네일 다운로드 + 로컬 캐시 관리
"""
import os
import re
import threading
import lib_common as lc


class ImageMetadataStore:
    """이미지 메타데이터 저장소"""

    def __init__(self):
        self._data = []  # [dict, ...]
        self._lock = threading.Lock()

    def load_from_sheet(self, spreadsheet):
        """시트에서 메타데이터 로딩"""
        entries = lc.load_image_metadata_from_sheet(spreadsheet)
        with self._lock:
            self._data = entries
        return len(entries)

    @property
    def all(self):
        with self._lock:
            return list(self._data)

    def filter(self, product=None, category=None, mood=None, position_hint=None, exclude_ids=None):
        """조건 기반 필터링. 조건이 None이면 해당 조건 무시."""
        exclude_ids = exclude_ids or set()
        results = []
        with self._lock:
            for entry in self._data:
                if entry['drive_file_id'] in exclude_ids:
                    continue
                if product and product != "전체":
                    entry_products = {p.strip() for p in entry['product'].split(',')}
                    if product not in entry_products and '공통' not in entry_products:
                        continue
                if category and entry['category'] != category:
                    continue
                if mood and entry['mood'] != mood:
                    continue
                if position_hint and entry['position_hint'] != position_hint:
                    if entry['position_hint'] != 'any':
                        continue
                results.append(entry)
        return results

    def search(self, query, product=None, exclude_ids=None):
        """텍스트 검색 — scene + tags에서 키워드 매칭, 점수순 정렬"""
        exclude_ids = exclude_ids or set()
        query_words = set(re.split(r'[,\s]+', query.strip()))
        query_words.discard('')

        scored = []
        with self._lock:
            for entry in self._data:
                if entry['drive_file_id'] in exclude_ids:
                    continue
                if product and product != "전체":
                    entry_products = {p.strip() for p in entry['product'].split(',')}
                    if product not in entry_products and '공통' not in entry_products:
                        continue

                # 점수 계산: scene + tags에서 매칭 단어 수
                searchable = f"{entry['scene']} {entry['tags']} {entry['category']} {entry['mood']}"
                score = sum(1 for w in query_words if w in searchable)

                if score > 0:
                    scored.append((score, entry))

        scored.sort(key=lambda x: -x[0])
        return [entry for _, entry in scored]

    def get_by_id(self, drive_file_id):
        """drive_file_id로 단일 항목 조회"""
        with self._lock:
            for entry in self._data:
                if entry['drive_file_id'] == drive_file_id:
                    return entry
        return None

    def get_products(self):
        """사용 가능한 제품 목록"""
        products = set()
        with self._lock:
            for entry in self._data:
                if entry['product']:
                    products.add(entry['product'])
        return sorted(products)

    def get_categories(self):
        """사용 가능한 카테고리 목록"""
        categories = set()
        with self._lock:
            for entry in self._data:
                if entry['category']:
                    categories.add(entry['category'])
        return sorted(categories)

    def get_moods(self):
        """사용 가능한 분위기 목록"""
        moods = set()
        with self._lock:
            for entry in self._data:
                if entry['mood']:
                    moods.add(entry['mood'])
        return sorted(moods)


class ThumbnailCache:
    """이미지 썸네일 로컬 캐시 관리"""

    def __init__(self, cache_dir):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    def get_path(self, drive_file_id):
        """캐시된 썸네일 경로 반환. 없으면 None."""
        path = os.path.join(self.cache_dir, f"{drive_file_id}.jpg")
        if os.path.exists(path):
            return path
        return None

    def download(self, drive_service, drive_file_id, callback=None):
        """썸네일 다운로드 → 캐시 저장 → 경로 반환"""
        path = os.path.join(self.cache_dir, f"{drive_file_id}.jpg")
        if os.path.exists(path):
            return path
        try:
            img_bytes = lc.drive_download_bytes(drive_service, drive_file_id)
            # 리사이즈 (200px 너비)
            try:
                from PIL import Image
                import io
                img = Image.open(io.BytesIO(img_bytes))
                img.thumbnail((200, 200), Image.LANCZOS)
                img.save(path, "JPEG", quality=85)
            except ImportError:
                # Pillow 없으면 원본 그대로 저장
                with open(path, 'wb') as f:
                    f.write(img_bytes)
            if callback:
                callback(drive_file_id, path)
            return path
        except Exception as e:
            if callback:
                callback(drive_file_id, None)
            return None

    def download_batch(self, drive_service, file_ids, callback=None, max_workers=4):
        """여러 이미지 썸네일을 병렬 다운로드"""
        from concurrent.futures import ThreadPoolExecutor

        to_download = [fid for fid in file_ids if not self.get_path(fid)]
        if not to_download:
            return

        def _download_one(fid):
            return self.download(drive_service, fid, callback)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            executor.map(_download_one, to_download)

    def get_tk_image(self, drive_file_id, size=(80, 80)):
        """tkinter용 PhotoImage 반환. 캐시에 없으면 None."""
        path = self.get_path(drive_file_id)
        if not path:
            return None
        try:
            from PIL import Image, ImageTk
            img = Image.open(path)
            img.thumbnail(size, Image.LANCZOS)
            return ImageTk.PhotoImage(img)
        except Exception:
            return None
