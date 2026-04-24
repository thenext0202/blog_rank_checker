"""
image_transformer.py — 이미지 변형 엔진

원고 생성 후 이미지가 맥락과 맞는지 분석하고,
안 맞는 이미지를 Gemini Imagen API로 변형한다.

기능:
  1. analyze_image_fit() — 원고 맥락 vs 이미지 메타데이터 비교 (Claude)
  2. transform_image() — Gemini Imagen으로 참조 이미지 + 프롬프트 → 새 이미지
  3. parse_user_instructions() — 사용자 수동 지시 파싱
"""
import re
import base64
import io
import json


# ════════════════════════════════════════════════════
#  1. 원고 맥락 추출
# ════════════════════════════════════════════════════

def extract_image_contexts(manuscript_text, context_chars=150):
    """원고에서 각 이미지 번호 앞뒤 텍스트를 추출한다.

    Returns:
        list[dict]: [{index: int, before: str, after: str}, ...]
    """
    lines = manuscript_text.split('\n')
    image_num_re = re.compile(r'^\d{1,2}$')
    contexts = []

    # 전체 텍스트에서 각 이미지 번호의 위치 파악
    full_text = manuscript_text
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not image_num_re.match(stripped):
            continue
        img_index = int(stripped)

        # 이미지 번호 앞 텍스트 (ㄴ 서식, 이미지 번호 제외)
        before_lines = []
        for j in range(i - 1, max(i - 10, -1), -1):
            s = lines[j].strip()
            if not s or re.match(r'^ㄴ\s*', s) or image_num_re.match(s):
                continue
            before_lines.insert(0, s)
            if sum(len(l) for l in before_lines) >= context_chars:
                break
        before_text = ' '.join(before_lines)[-context_chars:]

        # 이미지 번호 뒤 텍스트
        after_lines = []
        for j in range(i + 1, min(i + 10, len(lines))):
            s = lines[j].strip()
            if not s or re.match(r'^ㄴ\s*', s) or image_num_re.match(s):
                continue
            after_lines.append(s)
            if sum(len(l) for l in after_lines) >= context_chars:
                break
        after_text = ' '.join(after_lines)[:context_chars]

        contexts.append({
            "index": img_index,
            "before": before_text,
            "after": after_text,
        })

    return contexts


# ════════════════════════════════════════════════════
#  2. 적합도 분석 (Claude)
# ════════════════════════════════════════════════════

def analyze_image_fit(api_key, manuscript_text, image_slots):
    """원고 맥락 vs 이미지 메타데이터를 비교하여 적합도를 판정한다.

    Args:
        api_key: Claude API key
        manuscript_text: 생성된 원고 전문
        image_slots: list[ImageSlot] (image_selector.py의 슬롯)

    Returns:
        list[dict]: [{
            slot_index: int,
            fit: bool,          # 적합 여부
            reason: str,        # 판정 이유
            suggestion: str,    # 변형 제안 (불일치 시)
        }, ...]
    """
    from lib_common import call_claude_api_sync

    contexts = extract_image_contexts(manuscript_text)
    if not contexts or not image_slots:
        return []

    # 분석 프롬프트 구성
    items = []
    for ctx in contexts:
        # 해당 슬롯 찾기
        slot = None
        for s in image_slots:
            if s.index == ctx["index"] and not s.is_empty:
                slot = s
                break
        if not slot:
            continue

        entry = slot.entry
        items.append({
            "image_index": ctx["index"],
            "before_text": ctx["before"],
            "after_text": ctx["after"],
            "image_scene": entry.get("scene", ""),
            "image_mood": entry.get("mood", ""),
            "image_tags": entry.get("tags", ""),
            "image_category": entry.get("category", ""),
            "image_filename": entry.get("filename", ""),
        })

    if not items:
        return []

    prompt = f"""당신은 블로그 원고와 이미지의 적합도를 판정하는 전문가입니다.

아래에 원고의 각 이미지 위치의 앞뒤 맥락과, 해당 위치에 배정된 이미지의 메타데이터가 있습니다.
각 이미지가 원고 맥락에 적합한지 판정하고, 불일치 시 어떤 이미지로 변형하면 좋을지 제안해주세요.

## 판정 기준
- 이미지의 장면(scene)이 원고 맥락과 관련있으면 적합
- 이미지 분위기(mood)가 원고 톤과 어울리면 가산점
- 제품컷은 제품 언급 근처에 있으면 적합
- 완전히 무관한 장면이면 불일치

## 이미지 목록
{json.dumps(items, ensure_ascii=False, indent=2)}

## 응답 형식 (JSON 배열만 출력)
[
  {{
    "image_index": 0,
    "fit": true,
    "reason": "후킹 이미지로 체중 관리 장면이 원고 도입부와 적합",
    "suggestion": ""
  }},
  {{
    "image_index": 3,
    "fit": false,
    "reason": "원고에서 탈모 관리를 다루는데 음식 이미지가 배치됨",
    "suggestion": "머리카락을 만지며 고민하는 여성의 모습으로 변형"
  }}
]
"""

    try:
        result = call_claude_api_sync(api_key, prompt, max_tokens=2048)
        # JSON 파싱
        json_match = re.search(r'\[.*\]', result, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except Exception:
        pass
    return []


# ════════════════════════════════════════════════════
#  3. 사용자 지시 파싱
# ════════════════════════════════════════════════════

def parse_user_instructions(user_text, image_slots):
    """사용자의 자유형 지시를 이미지별 작업으로 파싱한다.

    예: "3개월차 컷 다시 만들어. 클로즈업 컷 2장 추가"
    → [{action: "transform", target: "3개월차 컷", prompt: "..."}, ...]

    단순히 텍스트를 그대로 프롬프트에 전달하므로,
    복잡한 파싱 없이 사용자 의도를 최대한 보존한다.
    """
    # 사용자 지시는 그대로 프롬프트에 포함 (별도 파싱 불필요)
    return user_text.strip()


# ════════════════════════════════════════════════════
#  4. 이미지 변형/생성 (Gemini Imagen API)
# ════════════════════════════════════════════════════

def transform_image(gemini_api_key, reference_image_bytes, prompt,
                    size="1024x1024", quality="medium"):
    """Gemini Imagen으로 참조 이미지를 기반으로 새 이미지를 생성한다.

    참조 이미지의 스타일/맥락을 프롬프트에 반영하여 Imagen으로 생성.

    Args:
        gemini_api_key: Gemini API 키
        reference_image_bytes: 참조 이미지 (bytes) — 맥락 참고용
        prompt: 변형 지시 프롬프트
        size: 출력 크기 (미사용, Imagen 기본값 사용)
        quality: 미사용

    Returns:
        bytes: 생성된 이미지 (PNG)
    """
    # 참조 이미지를 Gemini Vision으로 분석해서 프롬프트 보강
    from lib_common import analyze_image_vision

    try:
        ref_desc = analyze_image_vision(
            gemini_api_key, reference_image_bytes,
            "이 이미지의 구도, 색감, 분위기를 한 문장으로 설명하세요. JSON 없이 텍스트만.",
        )
        enhanced_prompt = f"{prompt}\n\n참조 이미지 스타일: {ref_desc.strip()}"
    except Exception:
        enhanced_prompt = prompt

    return generate_image(gemini_api_key, enhanced_prompt)


def generate_image(gemini_api_key, prompt, size="1024x1024", quality="medium"):
    """Gemini Imagen으로 프롬프트 기반 이미지를 생성한다.

    Args:
        gemini_api_key: Gemini API 키
        prompt: 이미지 생성 프롬프트
        size: 미사용 (Imagen 기본값 사용)
        quality: 미사용

    Returns:
        bytes: 생성된 이미지 (PNG)
    """
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=gemini_api_key)

    response = client.models.generate_images(
        model="imagen-3.0-generate-002",
        prompt=prompt,
        config=types.GenerateImagesConfig(
            number_of_images=1,
            output_mime_type="image/png",
        ),
    )

    if response.generated_images:
        return response.generated_images[0].image.image_bytes

    raise ValueError("Gemini Imagen 응답에서 이미지를 추출할 수 없습니다.")


# ════════════════════════════════════════════════════
#  5. 변형 프롬프트 구성
# ════════════════════════════════════════════════════

def build_transform_prompt(context_before, context_after, image_metadata,
                           ai_suggestion="", user_instruction=""):
    """이미지 변형을 위한 Imagen 프롬프트를 구성한다.

    Args:
        context_before: 이미지 앞 원고 텍스트
        context_after: 이미지 뒤 원고 텍스트
        image_metadata: 현재 이미지 메타데이터 dict
        ai_suggestion: Claude의 자동 변형 제안
        user_instruction: 사용자의 수동 지시

    Returns:
        str: Imagen 프롬프트
    """
    parts = []

    parts.append("한국 건강/의학 블로그에 사용할 이미지를 만들어주세요.")
    parts.append("자연스럽고 사실적인 사진 스타일이어야 합니다.")
    parts.append("")

    if user_instruction:
        parts.append(f"## 사용자 요청")
        parts.append(user_instruction)
        parts.append("")

    if ai_suggestion:
        parts.append(f"## 변형 방향")
        parts.append(ai_suggestion)
        parts.append("")

    parts.append(f"## 원고 맥락")
    if context_before:
        parts.append(f"이미지 앞 텍스트: {context_before}")
    if context_after:
        parts.append(f"이미지 뒤 텍스트: {context_after}")

    if image_metadata:
        scene = image_metadata.get("scene", "")
        if scene:
            parts.append(f"\n## 참조 이미지 정보")
            parts.append(f"현재 장면: {scene}")

    parts.append("")
    parts.append("## 규칙")
    parts.append("- 한국인 모델 사용")
    parts.append("- 텍스트/워터마크 없이")
    parts.append("- 밝고 깨끗한 조명")
    parts.append("- 블로그에 어울리는 자연스러운 구도")

    return '\n'.join(parts)
