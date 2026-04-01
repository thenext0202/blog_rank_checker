"""
심의안전 원고제작기 — 프롬프트 조립
기존 원고제작기의 build_prompt 구조 기반 + 심의안전 강조점 삽입
"""
from sheets_loader import load_sample_for_type


# ── 심의 안전 원칙 (공통지침 대체) ──
SAFETY_GUIDELINES = """

===== 심의 안전 원칙 (반드시 준수) =====

[심의 안전 원칙]
모든 원고는 식품 등의 표시·광고에 관한 법률 기준에 따라
심의 리스크를 최소화하면서 전환율을 극대화하는 방향으로 작성한다.
일반식품도 건강기능식품 기준으로 보수적으로 작성한다.

[절대 금지 표현]
- 질병명과 제품/성분명을 같은 문단에 두지 않는다
- "개선됐다, 좋아졌다, 낫는다, 효과가 있다" 결과 확정 표현 금지
- 인정된 기능성 문구 외 효능 주장 금지
- 질병 증상 → 원인 → 제품 순서의 직선 구조 금지
- 질병명과 건강기능식품 탐색을 도입부에서 직접 연결 금지
- CTA에 구매 압박 표현 금지
- 해시태그 금지
- 제품명 금지 (성분명/배합명으로만 표기)

[안전한 대체 표현]
- "[질병]에 좋은 제품" → "[성분] 찾을 때 기준으로 봤던 것"
- "속이 편해졌다" → "루틴에 넣기 편한 구성이었다"
- "[증상]에 추천" → "이 기준으로 고르는 분들이 비교해보는 제품"
- "구매하기" → "성분 구성 직접 확인하기"
- "[질병] 관련해서 건기식 찾아봤다" → "[신체부위] 건강 관련 건강기능식품 찾아봤다"

[심의 안전 자체 점검 — 원고 완성 후 반드시 확인]
□ 질병명과 제품/성분이 같은 문단에 없는가
□ 도입부에서 질병명과 건기식 탐색이 직접 연결되지 않는가
□ 결과 단정 표현이 없는가
□ 질병 증상 → 원인 → 제품 직선 구조가 없는가
□ 병원 진료 권고가 정보 파트 최상단에 있는가
□ CTA가 정보 확인 프레임인가
□ 키워드가 본문 기준 5회, 정보 파트 안에서만 사용됐는가
□ 해시태그가 없는가
□ 제품명이 없는가

위반 항목 발견 시 수정 후 출력한다."""


def build_prompt(sheet_data, product_name, prompt_type, style_name,
                 tone, font_size, alignment, quote_num, keywords, sub_keywords,
                 selected_refs, extra_instructions, include_toc,
                 product_link="",
                 char_count="3000~3300", img_count="자동",
                 color_positive="파란색", color_negative="빨간색",
                 highlight_emphasis="노란 형광펜", color_product="청록색",
                 highlight_product="노란 형광펜", title_repeat=True,
                 emphasis_fontsize="14",
                 safety_appeal_entry=None):
    """심의안전 원고용 프롬프트 조립
    safety_appeal_entry: {"group": "...", "combo": "A+C", "points": {"A": "...", "B": "...", "C": "..."}}
    """

    # 프롬프트 템플릿: 심의안전 탭에서만 로드
    prompt_template = sheet_data.get("safety_prompts", {}).get(prompt_type, "")

    style_desc = sheet_data["styles"].get(style_name, "")
    product_guide = sheet_data["products"].get(product_name, "")

    toc_instruction = ("- 목차를 포함합니다. 소제목 목록을 본문 초반에 넣어주세요." if include_toc
                       else "- 목차를 넣지 않습니다.")
    title_repeat_instruction = (
        "이미지 00 다음에 SEO 타이틀(제목)을 3줄 반복 작성하고, "
        "그 아래에 'ㄴ 세 줄 모두, 글자 크기 11, 아주 옅은 회색' 서식 지시를 넣습니다."
    ) if title_repeat else "SEO 타이틀(제목)을 3번 반복하지 않습니다."

    parts = []

    # 1) 프롬프트 템플릿
    if prompt_template:
        parts.append(prompt_template)

    # 1-1) 샘플 원고 (few-shot)
    sample_fname, sample_text = load_sample_for_type(prompt_type, product_name, sheet_data)
    if sample_text:
        parts.append("\n\n===== 참고 원고 예시 (톤/구조/서식 참고용) =====")
        parts.append("아래는 같은 유형으로 잘 작성된 실제 원고 예시입니다.")
        parts.append("이 원고의 톤, 문장 길이, 줄 끊기, 서식 지시(ㄴ), 이미지 배치, 전체 흐름을 참고하여 작성해주세요.")
        parts.append("단, 내용은 그대로 베끼지 말고 이번 키워드/제품/페르소나에 맞게 새로 작성합니다.")
        parts.append(f"\n--- 예시 원고 시작 ---\n{sample_text}\n--- 예시 원고 끝 ---")

    # 2) 작가 스타일
    if style_desc:
        parts.append(f"\n\n===== 작가 스타일 =====\n{style_desc}")

    # 3) 톤
    if tone == "반말":
        parts.append("\n\n===== 문체 =====")
        parts.append("반말(~거든, ~잖아, ~했더니, ~인 거야)로 작성해주세요.")
        parts.append("친구에게 말하듯 편안하고 자연스러운 톤으로 써주세요.")
    else:
        parts.append("\n\n===== 문체 =====")
        parts.append("존댓말(~입니다, ~했어요, ~더라고요, ~하셨나요)로 작성해주세요.")
        parts.append("정중하면서도 친근한 톤으로 써주세요.")

    # 4) 제품 정보
    if product_guide:
        parts.append(f"\n\n===== 제품 정보: {product_name} =====\n{product_guide}")

    # 4-S) 심의안전 중점 소구 (강조점 삽입)
    if safety_appeal_entry:
        combo = safety_appeal_entry.get("combo", "")
        points = safety_appeal_entry.get("points", {})
        group_name = safety_appeal_entry.get("group", "")
        active_keys = [k.strip() for k in combo.split("+") if k.strip()]
        parts.append(f"\n\n===== 심의안전 중점 소구 (키워드그룹: {group_name}) =====")
        parts.append(f"이 원고에서 특히 중점적으로 다뤄야 할 소구점입니다. (강조점 조합: {combo})")
        parts.append("아래 내용을 원고의 핵심 논리로 활용하되, 자연스러운 서사 안에서 녹여주세요.")
        for key in active_keys:
            content = points.get(key, "")
            if content:
                parts.append(f"\n■ 강조점 {key}:\n{content}")

    # 4-1) 목차 규칙
    parts.append("\n\n===== 목차 규칙 =====")
    parts.append("목차(소제목)에는 제품명, 배합명, 허브키워드를 넣지 마세요. 광고처럼 보입니다.")
    parts.append("목차는 독자의 궁금증/감정/상황 중심으로 작성하세요.")

    # 5) 심의 안전 원칙 (공통지침 대체)
    parts.append(SAFETY_GUIDELINES)

    # 6) 메인 키워드
    if keywords:
        parts.append(f"\n\n===== 메인 키워드 =====\n{keywords}")
        parts.append("위 키워드를 원고 제목과 본문에 자연스럽게 포함해주세요.")

    # 7) 연관 키워드
    if sub_keywords:
        parts.append(f"\n\n===== 연관 키워드 =====\n{sub_keywords}")
        parts.append("위 연관 키워드도 본문 중간중간에 자연스럽게 녹여주세요.")

    # 7-2) 글자수
    parts.append(f"\n\n===== 글자수 =====\n총 글자수 {char_count}자 범위로 작성해주세요.")

    # 7-2b) 줄 끊기 규칙
    parts.append("\n\n===== 줄 끊기 규칙 (매우 중요) =====")
    parts.append("네이버 블로그 스타일로 문장을 짧게 끊어서 작성합니다.")
    parts.append("한 줄은 공백 포함 20자 이내로 작성하고, 줄바꿈(엔터)으로 구분합니다.")
    parts.append("긴 문장은 의미 단위로 나눠서 여러 줄에 걸쳐 씁니다.")
    parts.append("")
    parts.append("■ 규칙 1: 의미 단위 사이에 빈 줄 삽입 (가독성 핵심)")
    parts.append("하나의 문장이 끝나고 새로운 문장이 시작될 때, 반드시 빈 줄(엔터 한 번 더)을 넣으세요.")
    parts.append("빈 줄 없이 줄만 바꾸면 텍스트가 다닥다닥 붙어서 가독성이 크게 떨어집니다.")
    parts.append("")
    parts.append("■ 규칙 2: 자연스러운 위치에서 줄 끊기")
    parts.append("조사(은/는/이/가/을/를/에/로/와/과)나 접속어 바로 앞에서 끊지 마세요.")
    parts.append("서술어가 혼자 다음 줄로 넘어가지 않도록 하세요.")

    # 7-2c) ㄴ 서식 지시 배치 규칙
    parts.append("\n\n===== ㄴ 서식 지시 배치 규칙 (매우 중요) =====")
    parts.append("ㄴ 서식 지시는 반드시 서식을 적용할 텍스트의 바로 아래 줄에 작성합니다.")
    parts.append("프로그램이 ㄴ 줄 위의 텍스트에 서식을 적용하므로, 반드시 텍스트를 먼저 쓰고 그 아래에 ㄴ 지시를 넣으세요.")
    parts.append("")
    parts.append("추가 규칙:")
    parts.append("- ㄴ 서식 지시는 반드시 독립된 줄에 단독으로 작성 (본문과 같은 줄에 섞지 않기)")
    parts.append("- 본문 텍스트를 ㄴ으로 시작하지 마세요 (ㄴ은 서식 지시 전용)")
    parts.append("- ㄴ 이미지 설명은 작성하지 마세요. 이미지 번호(00, 01...)만 넣으면 됩니다.")

    # 7-2d) 서식 활용 지침
    parts.append("\n\n===== 서식 활용 지침 (가장 중요 — 시각적으로 풍성하게) =====")
    parts.append("원고에 색상, 볼드, 형광펜, 글자 크기 변화를 적극적으로 활용하세요.")
    parts.append("서식이 없는 밋밋한 원고는 절대 안 됩니다.")
    parts.append("")
    parts.append("■ 색상 적용 방식 (3가지를 골고루 섞어서 사용):")
    parts.append("1) 멀티라인 전체 색상 (연속된 줄이 하나의 의미일 때)")
    parts.append("2) 한 줄 전체 색상")
    parts.append("3) 단어/구절 색상 (문장 속 특정 부분만 강조)")
    parts.append("4) 부정↔긍정 대비 색상 (빨강→파랑 연속)")
    parts.append("")
    parts.append("■ 색상별 활용 기준:")
    parts.append("- 빨간색: 부정적 상황, 증상, 경고, 위험 수치")
    parts.append("- 파란색: 긍정적 변화, 개선, 결심, 전환점")
    parts.append("- 보라색/청록색: 인용 대화, 감정 표현")
    parts.append("")
    parts.append("■ 색상을 넣지 않는 곳:")
    parts.append("- 일상적 연결 문장, 단순 상황 설명")
    parts.append("- 전체 본문의 30~40%만 색상. 나머지 60~70%는 색상 없는 일반 텍스트!")
    parts.append("")
    parts.append("■ 글씨 색 분량 기준:")
    parts.append("- 색상 ㄴ 지시를 원고 전체에서 12~18회 사용")
    parts.append("- 멀티라인 : 한 줄 : 단어 = 4 : 3 : 3 비율")
    parts.append("")
    parts.append("■ 형광펜 활용 (최소 5~7회)")
    parts.append(f"■ 강조 글자 크기 (소제목 제외, 최소 3~5회): 글자 크기 {emphasis_fontsize}")

    # 면책 문구 금지
    parts.append("\n\n===== 면책 문구 금지 =====")
    parts.append("'* 개인의 경험이며, 효과는 개인마다 다를 수 있습니다.' 같은 면책 문구는 절대 넣지 마세요.")

    # 이미지 배치 규칙
    parts.append("\n\n===== 이미지 배치 규칙 (매우 중요) =====")
    if img_count != "자동":
        parts.append(f"이미지를 총 {img_count}장 사용해주세요. (0번 대표 이미지 포함)")
    parts.append("이미지는 본문 전체에 걸쳐 균등하게 분배. 한 곳에 몰아 넣지 마세요.")
    parts.append("본문 내용이 끝난 후에는 절대 이미지를 넣지 마세요.")
    parts.append("이미지 사이에 본문 텍스트가 최소 5줄 이상 있어야 합니다.")

    # 제품 링크 전환 규칙
    parts.append("\n\n===== 제품 링크 전환 규칙 (광고 느낌 방지) =====")
    parts.append("제품 링크 전에 '왜 이 링크를 남기는지' 자연스러운 전환 멘트를 작성하세요.")
    parts.append("'+)' 또는 'ps.' 같은 추신 형태로 자연스럽게 시작")
    parts.append("전환 멘트는 2~4줄 정도로 짧게")

    # 참고자료
    papers = sheet_data.get("papers", {}).get(product_name, [])
    has_refs = bool(selected_refs) or bool(papers)
    if has_refs:
        parts.append("\n\n===== 참고자료 (반드시 활용) =====")
        parts.append("참고자료의 논문/연구를 최소 2건 이상 인용하세요.")
        parts.append("참고자료에 없는 논문을 지어내지 마세요.")
        parts.append("")
        parts.append("■ 인용 방식 (3가지 중 선택):")
        parts.append("1) 커뮤니티 발견형: '맘카페에서 봤는데...'")
        parts.append("2) 검색/탐색형: '논문까지 찾아봤는데...'")
        parts.append("3) 전문가 언급형: '의사 선생님이 말씀하시길...'")
        for fname, content in selected_refs.items():
            if len(content) > 8000:
                content = content[:8000] + "\n... (이하 생략)"
            parts.append(f"\n--- {fname} ---\n{content}")
        if papers:
            parts.append("\n--- 참고 논문 (스프레드시트) ---")
            for i, paper in enumerate(papers, 1):
                parts.append(f"\n[논문 {i}]\n{paper}")

    # 서식 규칙 (시트)
    fmt_template = sheet_data.get("format_instructions") or ""
    if fmt_template:
        link_text = product_link if product_link else "(제품 링크)"
        hl_emphasis = highlight_emphasis if highlight_emphasis != "없음" else "글꼴 두껍게"
        hl_product = highlight_product if highlight_product != "없음" else "글꼴 두껍게"
        try:
            parts.append(fmt_template.format(
                font_size=font_size, align_text=alignment,
                quote_num=quote_num, toc_instruction=toc_instruction,
                product_link=link_text,
                color_positive=color_positive, color_negative=color_negative,
                highlight_emphasis=hl_emphasis,
                color_product=color_product, highlight_product=hl_product,
                title_repeat=title_repeat_instruction,
                emphasis_fontsize=emphasis_fontsize,
            ))
        except KeyError as e:
            parts.append(f"\n\n[서식규칙 오류: 알 수 없는 플레이스홀더 {e}]")

    parts.append(f"\n[중요] 'ㄴ' 서식 지시에서 글자 크기는 반드시 11, 13, 15, 16, 19, 24, 28 중 하나만 사용하세요.")
    parts.append(f"[중요] 기본 글자 크기는 {font_size}입니다. 기본 크기와 같은 값을 지시하지 마세요.")

    # 추가 지시사항
    if extra_instructions:
        parts.append(f"\n\n===== 추가 지시사항 =====\n{extra_instructions}")

    # 최종: 심의 안전 자체 점검 재강조
    parts.append("\n\n===== 최종 심의 안전 점검 (원고 완성 후 반드시 확인) =====")
    parts.append("□ 질병명과 제품/성분이 같은 문단에 없는가")
    parts.append("□ 도입부에서 질병명과 건기식 탐색이 직접 연결되지 않는가")
    parts.append("□ 결과 단정 표현이 없는가")
    parts.append("□ 질병 증상 → 원인 → 제품 직선 구조가 없는가")
    parts.append("□ 병원 진료 권고가 정보 파트 최상단에 있는가")
    parts.append("□ CTA가 정보 확인 프레임인가")
    parts.append("□ 키워드가 본문 기준 5회, 정보 파트 안에서만 사용됐는가")
    parts.append("□ 해시태그가 없는가")
    parts.append("□ 제품명이 없는가")
    parts.append("위반 항목 발견 시 수정 후 출력한다.")

    return "\n".join(parts), sample_fname
