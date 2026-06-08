"""
image_selector.py — 이미지 선택 알고리즘

3단계 파이프라인:
  1. 필수 슬롯: 후킹(0번) + 제품컷(2~3장)
  2. AI 추천: Claude가 장면 추천 → 메타데이터 매칭
  3. 폴백: 공통 이미지 중 mood 매칭
"""
import re
import lib_common as lc
from image_metadata import ImageMetadataStore


class ImageSlot:
    """이미지 슬롯 (선택된 이미지 1장의 정보)"""

    def __init__(self, index, role="", entry=None, locked=False):
        self.index = index          # 슬롯 번호 (0, 1, 2, ...)
        self.role = role            # "hooking", "product_cut", "" (일반)
        self.entry = entry          # 메타데이터 dict (없으면 빈 슬롯)
        self.locked = locked        # 잠금 여부 (재선택 시 유지)

    @property
    def is_empty(self):
        return self.entry is None

    @property
    def description(self):
        """프롬프트에 넣을 설명 문자열"""
        if self.is_empty:
            return "(이미지 미선택)"
        role_tag = ""
        if self.role == "hooking":
            role_tag = "[후킹] "
        elif self.role == "product_cut":
            role_tag = "[제품컷] "
        scene = self.entry.get('scene', self.entry.get('filename', ''))
        mood = self.entry.get('mood', '')
        return f"{role_tag}{scene} (분위기: {mood})" if mood else f"{role_tag}{scene}"

    def to_dict(self):
        return {
            "index": self.index,
            "role": self.role,
            "entry": self.entry,
            "locked": self.locked,
        }


class ImageSelector:
    """이미지 선택 엔진"""

    def __init__(self, metadata_store: ImageMetadataStore):
        self.store = metadata_store
        self.slots = []  # [ImageSlot, ...]

    def auto_select(self, product, keyword, prompt_type, image_count=15,
                    api_key=None, product_cut_count=2):
        """자동 선택 — 3단계 파이프라인

        Args:
            product: 제품명
            keyword: 메인 키워드
            prompt_type: 원고 유형
            image_count: 총 이미지 수
            api_key: Claude API Key (AI 추천용, 없으면 규칙 기반만)
            product_cut_count: 제품컷 장수 (2~3)
        """
        self.slots = [ImageSlot(i) for i in range(image_count)]
        used_ids = set()

        # ── 1단계: 필수 슬롯 ──
        # 0번: 후킹 이미지
        hooking_candidates = self.store.filter(
            product=product, position_hint="hooking", exclude_ids=used_ids
        )
        if not hooking_candidates:
            # 폴백: position_hint가 opening인 것
            hooking_candidates = self.store.filter(
                product=product, position_hint="opening", exclude_ids=used_ids
            )
        if hooking_candidates:
            # 키워드 매칭 점수로 정렬
            best = self._score_by_keyword(hooking_candidates, keyword)
            self.slots[0] = ImageSlot(0, role="hooking", entry=best)
            used_ids.add(best['drive_file_id'])

        # 제품컷 (중반~후반에 배치)
        product_cuts = self.store.filter(
            product=product, category="제품컷", exclude_ids=used_ids
        )
        cut_positions = self._get_product_cut_positions(image_count, product_cut_count)
        for i, pos in enumerate(cut_positions):
            if i < len(product_cuts):
                self.slots[pos] = ImageSlot(pos, role="product_cut", entry=product_cuts[i])
                used_ids.add(product_cuts[i]['drive_file_id'])

        # ── 2단계: AI 추천 + 메타데이터 매칭 ──
        empty_slots = [s for s in self.slots if s.is_empty]
        if empty_slots and api_key:
            try:
                scenes = self._ai_recommend_scenes(
                    api_key, product, keyword, prompt_type, len(empty_slots)
                )
                for slot, scene_info in zip(empty_slots, scenes):
                    match = self._match_scene(scene_info, product, used_ids)
                    if match:
                        slot.entry = match
                        used_ids.add(match['drive_file_id'])
            except Exception:
                pass  # AI 추천 실패 시 폴백으로

        # ── 3단계: 폴백 ──
        still_empty = [s for s in self.slots if s.is_empty]
        if still_empty:
            # 공통 이미지 중 아직 사용 안 한 것들
            fallback = self.store.filter(product=product, exclude_ids=used_ids)
            if not fallback:
                fallback = self.store.filter(product="공통", exclude_ids=used_ids)
            for slot in still_empty:
                if fallback:
                    entry = fallback.pop(0)
                    slot.entry = entry
                    used_ids.add(entry['drive_file_id'])

        return self.slots

    def _get_product_cut_positions(self, total, count):
        """제품컷 배치 위치 계산 — 중반~후반에 균등 배치"""
        if total <= 3:
            return list(range(1, min(count + 1, total)))
        # 중반 시작 = 전체의 40%, 후반 끝 = 전체의 90%
        start = max(1, int(total * 0.4))
        end = min(total - 1, int(total * 0.9))
        if count == 1:
            return [start]
        step = max(1, (end - start) // (count - 1)) if count > 1 else 0
        positions = [start + i * step for i in range(count)]
        return [p for p in positions if p < total]

    def _score_by_keyword(self, candidates, keyword):
        """키워드 매칭 점수가 높은 후보 반환"""
        kw_words = set(re.split(r'\s+', keyword))
        best = candidates[0]
        best_score = 0
        for entry in candidates:
            searchable = f"{entry.get('scene', '')} {entry.get('tags', '')}"
            score = sum(1 for w in kw_words if w in searchable)
            if score > best_score:
                best = entry
                best_score = score
        return best

    def _ai_recommend_scenes(self, api_key, product, keyword, prompt_type, count):
        """Claude에게 장면 추천 요청"""
        prompt = f"""블로그 원고에 들어갈 이미지 {count}장의 장면을 추천해 주세요.

제품: {product}
키워드: {keyword}
원고 유형: {prompt_type}

각 줄에 하나씩, 아래 형식으로 작성하세요:
slot_1: 장면설명 | mood: 분위기

예시:
slot_1: 불안한 표정으로 침대에서 뒤척이는 여성 | mood: 불안한
slot_2: 약국에서 약사와 상담하는 모습 | mood: 일상적

원고의 서사 흐름(도입→전개→전환→결말)을 고려하세요.
{count}개를 빠짐없이 작성해 주세요."""

        result = lc.call_claude_api_sync(api_key, prompt, max_tokens=1024)

        scenes = []
        for line in result.strip().split('\n'):
            line = line.strip()
            if not line or not line.startswith('slot_'):
                continue
            # "slot_1: 장면설명 | mood: 분위기" 파싱
            parts = line.split(':', 1)
            if len(parts) < 2:
                continue
            rest = parts[1].strip()
            scene = rest
            mood = ""
            if '| mood:' in rest:
                scene, mood_part = rest.rsplit('| mood:', 1)
                scene = scene.strip()
                mood = mood_part.strip()
            scenes.append({"scene": scene, "mood": mood})

        return scenes

    def _match_scene(self, scene_info, product, used_ids):
        """AI 추천 장면을 메타데이터에서 매칭"""
        query = scene_info.get("scene", "")
        mood = scene_info.get("mood", "")

        # 1차: 텍스트 검색
        results = self.store.search(query, product=product, exclude_ids=used_ids)

        if not results:
            return None

        # mood 매칭 가산점
        if mood:
            scored = []
            for entry in results:
                bonus = 2 if entry.get('mood', '') == mood else 0
                scored.append((bonus, entry))
            scored.sort(key=lambda x: -x[0])
            return scored[0][1]

        return results[0]

    # ── 수동 조작 메서드 ──

    def swap_image(self, slot_index, new_entry):
        """특정 슬롯의 이미지를 교체"""
        if 0 <= slot_index < len(self.slots):
            slot = self.slots[slot_index]
            slot.entry = new_entry

    def reorder(self, old_index, new_index):
        """이미지 순서 변경"""
        if 0 <= old_index < len(self.slots) and 0 <= new_index < len(self.slots):
            slot = self.slots.pop(old_index)
            self.slots.insert(new_index, slot)
            # 인덱스 재정렬
            for i, s in enumerate(self.slots):
                s.index = i

    def add_slot(self, entry=None, role=""):
        """슬롯 추가"""
        idx = len(self.slots)
        self.slots.append(ImageSlot(idx, role=role, entry=entry))

    def remove_slot(self, index):
        """슬롯 제거"""
        if 0 <= index < len(self.slots):
            self.slots.pop(index)
            for i, s in enumerate(self.slots):
                s.index = i

    def lock_slot(self, index, locked=True):
        """슬롯 잠금/해제"""
        if 0 <= index < len(self.slots):
            self.slots[index].locked = locked

    def get_unlocked_slots(self):
        """잠금 안 된 슬롯 목록"""
        return [s for s in self.slots if not s.locked]

    def re_select_unlocked(self, product, keyword, prompt_type, api_key=None):
        """잠금 안 된 슬롯만 재선택"""
        used_ids = {s.entry['drive_file_id'] for s in self.slots if s.entry and s.locked}

        for slot in self.slots:
            if slot.locked:
                continue
            slot.entry = None
            slot.role = ""

        # 빈 슬롯만 다시 채우기 (후킹/제품컷 규칙 없이 AI 추천만)
        empty = [s for s in self.slots if s.is_empty]
        if empty and api_key:
            try:
                scenes = self._ai_recommend_scenes(
                    api_key, product, keyword, prompt_type, len(empty)
                )
                for slot, scene_info in zip(empty, scenes):
                    match = self._match_scene(scene_info, product, used_ids)
                    if match:
                        slot.entry = match
                        used_ids.add(match['drive_file_id'])
            except Exception:
                pass

        # 폴백
        still_empty = [s for s in self.slots if s.is_empty]
        if still_empty:
            fallback = self.store.filter(product=product, exclude_ids=used_ids)
            for slot in still_empty:
                if fallback:
                    entry = fallback.pop(0)
                    slot.entry = entry
                    used_ids.add(entry['drive_file_id'])

    # ── 프롬프트 생성 ──

    def build_image_sequence_prompt(self):
        """섹션 7-4: 이미지 시퀀스 프롬프트 생성"""
        lines = [
            "\n\n===== 이미지 시퀀스 (이 순서대로 이미지가 배치됩니다) =====",
            "아래 이미지 목록을 참고하여, 각 이미지 전후의 텍스트가",
            "이미지의 장면과 자연스럽게 연결되도록 작성하세요.",
            "이미지 번호(0, 1, 2...)는 반드시 독립 줄에 넣으세요.",
            "",
        ]
        for slot in self.slots:
            lines.append(f"이미지 {slot.index}: {slot.description}")
        return "\n".join(lines)

    def build_image_text_guidelines(self):
        """섹션 7-5: 이미지-텍스트 연결 지침"""
        return """
===== 이미지-텍스트 연결 지침 =====
1. 이미지 앞 텍스트는 해당 이미지 장면으로의 전환을 자연스럽게 유도하세요.
   예: 이미지가 "약국 상담"이면 → "결국 약국에 가보기로 했다" 같은 행동 전환
2. 이미지 뒤 텍스트는 이미지 장면에서 이어지는 감정/생각/행동을 서술하세요.
3. 제품컷 이미지 앞뒤에서는 제품을 발견하거나 사용하는 에피소드를 전개하세요.
4. 후킹 이미지(이미지 0)는 독자의 시선을 끄는 첫 장면입니다.
5. 이미지 번호만 쓰세요. 이미지 설명 ㄴ(설명)은 작성하지 마세요."""
