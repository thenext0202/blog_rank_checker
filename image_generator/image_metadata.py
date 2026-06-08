"""
image_metadata.py — 이미지 메타데이터 로딩, 검색, 썸네일 캐싱

기능:
  - 시트에서 메타데이터 로딩 → 메모리 캐시
  - 조건 기반 필터링 (제품, 카테고리, mood, tags 등)
  - 텍스트 검색 (scene + tags 매칭) — 폴백용
  - 임베딩 기반 의미 검색 (코사인 유사도)
  - 썸네일 다운로드 + 로컬 캐시 관리
"""
import os
import re
import json
import threading
import numpy as np
import lib_common as lc


class ImageMetadataStore:
    """이미지 메타데이터 저장소"""

    # 임베딩 파일 저장 경로
    EMBEDDINGS_NPY = os.path.join(lc.base_dir(), "embeddings.npy")
    EMBEDDINGS_IDS = os.path.join(lc.base_dir(), "embeddings_ids.json")

    def __init__(self):
        self._data = []  # [dict, ...]
        self._lock = threading.Lock()
        # 임베딩 데이터
        self._embeddings = None      # numpy 배열 (N x 차원)
        self._embedding_ids = []     # drive_file_id 리스트 (인덱스 매핑용)

    def load_from_sheet(self, spreadsheet):
        """시트에서 메타데이터 로딩"""
        entries = lc.load_image_metadata_from_sheet(spreadsheet)
        # scene, tags 둘 다 없는 항목은 제외
        entries = [e for e in entries if e.get('scene', '').strip() or e.get('tags', '').strip()]
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

    # ════════════════════════════════════════════════════
    #  임베딩 기반 검색
    # ════════════════════════════════════════════════════

    @staticmethod
    def _build_embedding_text(entry):
        """이미지 메타데이터를 임베딩용 텍스트 하나로 합침.
        예: "오피스에서 음료 마시는 여성 일상 카페 밝은 생활"

        scene/tags가 비어있으면 filename + category + drive_folder를 폴백으로 사용.
        """
        parts = []
        if entry.get('scene', '').strip():
            parts.append(entry['scene'].strip())
        if entry.get('tags', '').strip():
            parts.append(entry['tags'].strip())
        if entry.get('mood', '').strip():
            parts.append(entry['mood'].strip())
        if entry.get('category', '').strip():
            parts.append(entry['category'].strip())

        # scene/tags 둘 다 비어있으면 폴백: filename + drive_folder
        if not entry.get('scene', '').strip() and not entry.get('tags', '').strip():
            if entry.get('filename', '').strip():
                # 확장자 제거한 파일명
                name = os.path.splitext(entry['filename'].strip())[0]
                parts.append(name)
            if entry.get('drive_folder', '').strip():
                parts.append(entry['drive_folder'].strip())

        return ' '.join(parts)

    def compute_and_save_embeddings(self, gemini_api_key, on_progress=None):
        """전체 이미지 메타데이터를 임베딩으로 변환해서 파일로 저장.

        Args:
            gemini_api_key: Gemini API 키
            on_progress: 진행률 콜백 함수 (현재건수, 전체건수) → UI 업데이트용

        Returns:
            int: 임베딩 생성된 이미지 수
        """
        with self._lock:
            data = list(self._data)

        if not data:
            return 0

        # 각 이미지의 설명 텍스트 준비
        texts = []
        ids = []
        for entry in data:
            text = self._build_embedding_text(entry)
            if text:
                texts.append(text)
                ids.append(entry['drive_file_id'])

        if not texts:
            return 0

        if on_progress:
            on_progress(0, len(texts))

        # Gemini 임베딩 API 호출 (배치)
        embeddings = lc.get_embeddings(gemini_api_key, texts)

        if on_progress:
            on_progress(len(texts), len(texts))

        # numpy 배열로 변환 후 저장
        emb_array = np.array(embeddings, dtype=np.float32)
        np.save(self.EMBEDDINGS_NPY, emb_array)
        with open(self.EMBEDDINGS_IDS, 'w', encoding='utf-8') as f:
            json.dump(ids, f, ensure_ascii=False)

        # 메모리에도 로딩
        self._embeddings = emb_array
        self._embedding_ids = ids

        return len(ids)

    # Gemini gemini-embedding-001 차원
    EXPECTED_DIM = 3072

    def load_embeddings(self):
        """저장된 임베딩 파일을 메모리에 로딩.

        차원이 다르면(OpenAI→Gemini 전환 등) 기존 파일 삭제 후 재생성 유도.

        Returns:
            bool: 로딩 성공 여부
        """
        if (os.path.exists(self.EMBEDDINGS_NPY)
                and os.path.exists(self.EMBEDDINGS_IDS)):
            emb = np.load(self.EMBEDDINGS_NPY)
            # 차원 불일치 → 기존 파일 삭제
            if emb.ndim == 2 and emb.shape[1] != self.EXPECTED_DIM:
                os.remove(self.EMBEDDINGS_NPY)
                os.remove(self.EMBEDDINGS_IDS)
                return False
            self._embeddings = emb
            with open(self.EMBEDDINGS_IDS, 'r', encoding='utf-8') as f:
                self._embedding_ids = json.load(f)
            return True
        return False

    @property
    def has_embeddings(self):
        """임베딩 데이터가 로딩되어 있는지 여부"""
        return self._embeddings is not None and len(self._embedding_ids) > 0

    def search_by_embedding(self, query_embedding, product=None, exclude_ids=None, top_k=10):
        """임베딩 코사인 유사도 기반 검색.

        Args:
            query_embedding: 검색 쿼리의 임베딩 벡터 (list[float])
            product: 제품 필터 (None이면 전체)
            exclude_ids: 제외할 drive_file_id 집합
            top_k: 반환할 상위 결과 수

        Returns:
            list[dict]: 유사도 높은 순으로 정렬된 이미지 메타데이터 리스트
        """
        if not self.has_embeddings:
            return []

        exclude_ids = exclude_ids or set()
        query_vec = np.array(query_embedding, dtype=np.float32)

        # 1차: 제품 태그 필터링 (해당 이미지의 인덱스만 추림)
        valid_indices = []
        id_to_idx = {fid: i for i, fid in enumerate(self._embedding_ids)}

        with self._lock:
            for entry in self._data:
                fid = entry['drive_file_id']
                if fid in exclude_ids:
                    continue
                if fid not in id_to_idx:
                    continue
                if product and product != "전체":
                    entry_products = {p.strip() for p in entry['product'].split(',')}
                    if product not in entry_products and '공통' not in entry_products:
                        continue
                valid_indices.append(id_to_idx[fid])

        if not valid_indices:
            return []

        # 2차: 코사인 유사도 계산
        valid_indices = np.array(valid_indices)
        candidate_embs = self._embeddings[valid_indices]  # (M x 차원)

        # 코사인 유사도 = (A · B) / (|A| * |B|)
        query_norm = query_vec / (np.linalg.norm(query_vec) + 1e-10)
        cand_norms = candidate_embs / (
            np.linalg.norm(candidate_embs, axis=1, keepdims=True) + 1e-10)
        similarities = cand_norms @ query_norm  # (M,)

        # 상위 top_k 추출
        top_count = min(top_k, len(similarities))
        top_local_indices = np.argsort(similarities)[::-1][:top_count]

        # 결과 조합
        results = []
        for local_idx in top_local_indices:
            global_idx = valid_indices[local_idx]
            fid = self._embedding_ids[global_idx]
            entry = self.get_by_id(fid)
            if entry:
                results.append(entry)

        return results


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

    def download(self, drive_service, drive_file_id, callback=None, retries=2):
        """썸네일 다운로드 → 캐시 저장 → 경로 반환. 실패 시 재시도."""
        path = os.path.join(self.cache_dir, f"{drive_file_id}.jpg")
        if os.path.exists(path):
            return path
        import time
        for attempt in range(retries + 1):
            try:
                img_bytes = lc.drive_download_bytes(drive_service, drive_file_id)
                try:
                    from PIL import Image
                    import io
                    img = Image.open(io.BytesIO(img_bytes))
                    img.thumbnail((200, 200), Image.LANCZOS)
                    img.save(path, "JPEG", quality=85)
                except ImportError:
                    with open(path, 'wb') as f:
                        f.write(img_bytes)
                if callback:
                    callback(drive_file_id, path)
                return path
            except Exception:
                if attempt < retries:
                    time.sleep(0.5)
                    continue
                if callback:
                    callback(drive_file_id, None)
                return None

    def download_batch(self, drive_service, file_ids, callback=None, max_workers=2):
        """여러 이미지 썸네일을 병렬 다운로드 (SSL 충돌 방지로 2스레드)"""
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
