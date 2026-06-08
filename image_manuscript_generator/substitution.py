"""
substitution.py — 치환 모드 로직

처리 흐름:
  1. 원본 원고 파싱 (이미지 위치 분리, ㄴ서식 보존)
  2. 장면 추론 (Claude → 각 이미지 위치의 장면 설명)
  3. 이미지 자동 매칭 (추론된 장면 → 대상 제품 메타데이터)
  4. 치환 생성 (Claude → 치환된 원고)
"""
import re
import lib_common as lc
from image_metadata import ImageMetadataStore
from image_selector import ImageSlot


def parse_original_manuscript(text):
    """원본 원고를 이미지 번호 줄 기준으로 세그먼트 분리

    Returns:
        segments: [{"type": "text"/"image"/"blogger_req", "content": str, "img_num": int|None}, ...]
        image_count: 원고에 포함된 이미지 수
    """
    lines = text.split('\n')
    segments = []
    in_blogger_req = False
    blogger_lines = []
    image_count = 0

    for line in lines:
        stripped = line.strip()

        # ★블로거 요청사항★ 시작/끝 감지
        if '★블로거 요청사항★' in stripped or '★ 블로거 요청사항 ★' in stripped:
            if not in_blogger_req:
                in_blogger_req = True
                blogger_lines = [stripped]
                continue
            else:
                blogger_lines.append(stripped)
                in_blogger_req = False
                segments.append({
                    "type": "blogger_req",
                    "content": "\n".join(blogger_lines),
                    "img_num": None,
                })
                blogger_lines = []
                continue

        if in_blogger_req:
            blogger_lines.append(stripped)
            continue

        # 이미지 번호 줄 감지 (0, 1, 2, ... 또는 00, 01, 02, ...)
        if re.match(r'^(\d{1,2})$', stripped):
            img_num = int(stripped)
            segments.append({
                "type": "image",
                "content": stripped,
                "img_num": img_num,
            })
            image_count = max(image_count, img_num + 1)
        else:
            segments.append({
                "type": "text",
                "content": line,
                "img_num": None,
            })

    # 블로거 요청사항이 닫히지 않은 경우
    if blogger_lines:
        segments.append({
            "type": "blogger_req",
            "content": "\n".join(blogger_lines),
            "img_num": None,
        })

    return segments, image_count


def get_context_around_images(segments, char_count=50):
    """각 이미지 번호 앞뒤 텍스트 추출

    Returns:
        [{img_num: int, before: str, after: str}, ...]
    """
    contexts = []
    for i, seg in enumerate(segments):
        if seg['type'] != 'image':
            continue

        # 앞 텍스트: 이전 text 세그먼트들에서 마지막 char_count자
        before_parts = []
        for j in range(i - 1, -1, -1):
            if segments[j]['type'] == 'text':
                before_parts.insert(0, segments[j]['content'])
                if sum(len(p) for p in before_parts) >= char_count:
                    break
        before = " ".join(before_parts).strip()[-char_count:]

        # 뒤 텍스트: 다음 text 세그먼트들에서 처음 char_count자
        after_parts = []
        for j in range(i + 1, len(segments)):
            if segments[j]['type'] == 'text':
                after_parts.append(segments[j]['content'])
                if sum(len(p) for p in after_parts) >= char_count:
                    break
        after = " ".join(after_parts).strip()[:char_count]

        contexts.append({
            "img_num": seg['img_num'],
            "before": before,
            "after": after,
        })

    return contexts


def infer_scenes(api_key, contexts):
    """Claude로 각 이미지 위치의 장면 추론

    Args:
        api_key: Claude API Key
        contexts: [{img_num, before, after}, ...]

    Returns:
        [{img_num: int, scene: str, mood: str}, ...]
    """
    if not contexts:
        return []

    prompt_lines = [
        "아래는 블로그 원고에서 이미지가 삽입된 위치의 앞뒤 텍스트입니다.",
        "각 이미지 위치에 어울리는 장면을 한 줄로 설명하고, 분위기를 태그해 주세요.",
        "",
        "형식:",
        "이미지 N: 장면설명 | mood: 분위기",
        "",
    ]
    for ctx in contexts:
        prompt_lines.append(f"--- 이미지 {ctx['img_num']} ---")
        prompt_lines.append(f"앞: {ctx['before']}")
        prompt_lines.append(f"뒤: {ctx['after']}")
        prompt_lines.append("")

    prompt_lines.append("위 맥락을 분석하여, 각 이미지에 어울리는 장면과 분위기를 답변해 주세요.")

    result = lc.call_claude_api_sync(api_key, "\n".join(prompt_lines), max_tokens=1024)

    # 파싱
    inferred = []
    for line in result.strip().split('\n'):
        line = line.strip()
        m = re.match(r'이미지\s*(\d+)\s*:\s*(.+)', line)
        if not m:
            continue
        img_num = int(m.group(1))
        rest = m.group(2).strip()
        scene = rest
        mood = ""
        if '| mood:' in rest:
            scene, mood_part = rest.rsplit('| mood:', 1)
            scene = scene.strip()
            mood = mood_part.strip()
        inferred.append({"img_num": img_num, "scene": scene, "mood": mood})

    return inferred


def match_images_for_substitution(store: ImageMetadataStore, inferred_scenes,
                                  target_product, original_image_count):
    """추론된 장면을 대상 제품의 이미지에 매칭

    Returns:
        [ImageSlot, ...] — original_image_count 길이
    """
    slots = [ImageSlot(i) for i in range(original_image_count)]
    used_ids = set()

    # 0번 = 후킹
    if inferred_scenes:
        hooking_candidates = store.filter(
            product=target_product, position_hint="hooking", exclude_ids=used_ids
        )
        if hooking_candidates:
            slots[0] = ImageSlot(0, role="hooking", entry=hooking_candidates[0])
            used_ids.add(hooking_candidates[0]['drive_file_id'])

    # 제품컷 찾기 (원본에서 제품컷 위치 추정은 어려우므로, 중반에 배치)
    product_cuts = store.filter(
        product=target_product, category="제품컷", exclude_ids=used_ids
    )
    cut_positions = []
    total = original_image_count
    if total >= 5:
        cut_positions = [int(total * 0.5), int(total * 0.75)]
    elif total >= 3:
        cut_positions = [int(total * 0.5)]
    for i, pos in enumerate(cut_positions):
        if i < len(product_cuts) and pos < total:
            slots[pos] = ImageSlot(pos, role="product_cut", entry=product_cuts[i])
            used_ids.add(product_cuts[i]['drive_file_id'])

    # 나머지: 추론된 장면 매칭
    scene_map = {s['img_num']: s for s in inferred_scenes}
    for slot in slots:
        if not slot.is_empty:
            continue
        scene_info = scene_map.get(slot.index)
        if scene_info:
            results = store.search(
                scene_info['scene'], product=target_product, exclude_ids=used_ids
            )
            if results:
                # mood 매칭 가산
                mood = scene_info.get('mood', '')
                if mood:
                    scored = [(2 if e.get('mood') == mood else 0, e) for e in results]
                    scored.sort(key=lambda x: -x[0])
                    best = scored[0][1]
                else:
                    best = results[0]
                slot.entry = best
                used_ids.add(best['drive_file_id'])

    # 폴백
    for slot in slots:
        if slot.is_empty:
            fallback = store.filter(product=target_product, exclude_ids=used_ids)
            if not fallback:
                fallback = store.filter(product="공통", exclude_ids=used_ids)
            if fallback:
                slot.entry = fallback[0]
                used_ids.add(fallback[0]['drive_file_id'])

    return slots


def build_substitution_prompt(original_text, target_product, product_guide,
                              image_slots, target_keyword="", hashtags="",
                              product_link="", product_code=""):
    """치환 프롬프트 생성"""
    # 이미지 시퀀스
    image_lines = []
    for slot in image_slots:
        image_lines.append(f"이미지 {slot.index}: {slot.description}")

    prompt = f"""원본 원고를 아래 제품/이미지에 맞게 치환하세요.

===== 원본 원고 =====
{original_text}

===== 치환 대상 제품 =====
제품명: {target_product}
{product_guide}

===== 새 키워드 =====
{target_keyword or '(키워드 미지정)'}

===== 이미지 시퀀스 =====
{chr(10).join(image_lines)}

===== 치환 규칙 =====
1. 원본의 서사 구조(도입→전개→전환→결말)를 유지합니다.
2. 제품명, 성분명, 증상, 수치를 새 제품에 맞게 교체합니다.
3. 이미지 위치와 개수는 유지하되, 새 이미지 설명에 맞게 앞뒤 텍스트를 조정합니다.
4. ㄴ서식 지시와 서식 구조는 그대로 유지합니다.
5. 글자수는 원본의 ±10% 이내로 맞춥니다.
6. ★블로거 요청사항★은 새 제품의 링크/코드로 교체합니다.
   - 제품 링크: {product_link or '(링크 미지정)'}
   - 제품 코드: {product_code or '(코드 미지정)'}
7. 해시태그는 새 키워드 기반으로 교체합니다: {hashtags or '(해시태그 미지정)'}

===== 이미지-텍스트 연결 지침 =====
1. 이미지 앞 텍스트는 해당 이미지 장면으로의 전환을 자연스럽게 유도하세요.
2. 이미지 뒤 텍스트는 이미지 장면에서 이어지는 감정/생각/행동을 서술하세요.
3. 제품컷 이미지 앞뒤에서는 제품을 발견하거나 사용하는 에피소드를 전개하세요.
4. 이미지 번호만 쓰세요. 이미지 설명 ㄴ(설명)은 작성하지 마세요.

치환된 전체 원고를 출력하세요. 다른 설명은 필요 없습니다."""

    return prompt
