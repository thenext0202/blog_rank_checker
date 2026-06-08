"""
심의안전 원고제작기 — 프롬프트 조립
system prompt: 시트 B열 + 고정 규칙 (줄 끊기, 서식, 이미지 등)
user prompt: 변수값만 (키워드, 소구점, 참고자료, 추가지시)
"""
from sheets_loader import load_sample_for_type


# ── 폴백용 기본 system prompt (시트 로딩 실패 시) ──
DEFAULT_SYSTEM_PROMPT = """당신은 한국 건강 블로그 원고 작성자입니다.
식품 등의 표시·광고에 관한 법률 기준으로 심의 리스크 없이 전환율 높은 원고를 씁니다."""


def _get_fixed_rules(font_size, emphasis_fontsize, img_count="자동"):
    """매번 바뀌지 않는 고정 규칙 — system_prompt에 포함"""
    rules = []

    # 목차 규칙
    rules.append("===== 목차 규칙 =====")
    rules.append("목차(소제목)에는 제품명, 배합명, 허브키워드를 넣지 마세요. 광고처럼 보입니다.")
    rules.append("목차는 독자의 궁금증/감정/상황 중심으로 작성하세요.")

    # 줄 끊기 규칙
    rules.append("\n\n===== 줄 끊기 규칙 (매우 중요) =====")
    rules.append("네이버 블로그 스타일로 문장을 짧게 끊어서 작성합니다.")
    rules.append("한 줄은 공백 포함 20자 이내로 작성하고, 줄바꿈(엔터)으로 구분합니다.")
    rules.append("긴 문장은 의미 단위로 나눠서 여러 줄에 걸쳐 씁니다.")
    rules.append("")
    rules.append("■ 규칙 1: 의미 단위 사이에 빈 줄 삽입 (가독성 핵심)")
    rules.append("하나의 문장이 끝나고 새로운 문장이 시작될 때, 반드시 빈 줄(엔터 한 번 더)을 넣으세요.")
    rules.append("빈 줄 없이 줄만 바꾸면 텍스트가 다닥다닥 붙어서 가독성이 크게 떨어집니다.")
    rules.append("")
    rules.append("■ 규칙 2: 자연스러운 위치에서 줄 끊기")
    rules.append("조사(은/는/이/가/을/를/에/로/와/과)나 접속어 바로 앞에서 끊지 마세요.")
    rules.append("서술어가 혼자 다음 줄로 넘어가지 않도록 하세요.")

    # ㄴ 서식 지시 배치 규칙
    rules.append("\n\n===== ㄴ 서식 지시 배치 규칙 (매우 중요) =====")
    rules.append("ㄴ 서식 지시는 반드시 서식을 적용할 텍스트의 바로 아래 줄에 작성합니다.")
    rules.append("프로그램이 ㄴ 줄 위의 텍스트에 서식을 적용하므로, 반드시 텍스트를 먼저 쓰고 그 아래에 ㄴ 지시를 넣으세요.")
    rules.append("")
    rules.append("추가 규칙:")
    rules.append("- ㄴ 서식 지시는 반드시 독립된 줄에 단독으로 작성 (본문과 같은 줄에 섞지 않기)")
    rules.append("- 본문 텍스트를 ㄴ으로 시작하지 마세요 (ㄴ은 서식 지시 전용)")
    rules.append("- ㄴ 이미지 설명은 작성하지 마세요. 이미지 번호(00, 01...)만 넣으면 됩니다.")
    rules.append("- HTML 태그(<span>, <b>, <font> 등) 절대 금지. 색상/볼드 등 모든 서식은 반드시 ㄴ 지시로만 표현하세요.")

    # ㄴ 서식 정확한 문법 명세
    rules.append("\n\n===== ㄴ 서식 정확한 문법 (반드시 이 형식만 사용) =====")
    rules.append("프로그램 파서가 아래 형식만 인식합니다. 다른 형식은 서식이 깨집니다.")
    rules.append("")
    rules.append("■ 허용 색상명 (이것만 사용, 다른 표현 금지):")
    rules.append("  빨간색, 파란색, 청록색, 초록색, 보라색, 주황색, 회색, 옅은 회색, 많이 옅은 회색, 진한 회색")
    rules.append("")
    rules.append("■ 문법 종류:")
    rules.append("1) 단어별 색상: ㄴ '단어1' '단어2' 빨간색")
    rules.append("   → 반드시 작은따옴표(')로 감싸기. 큰따옴표(\") 금지")
    rules.append("2) 전체 글자색: ㄴ 글자 색 파란색")
    rules.append("   → '글자'와 '색' 사이에 반드시 띄어쓰기")
    rules.append("3) 형광펜: ㄴ 노란 형광펜")
    rules.append("   → 허용: 노란/파란/빨간/초록/청록 형광펜")
    rules.append("4) 글자 크기: ㄴ 글자 크기 19")
    rules.append("5) 볼드: ㄴ 글꼴 두껍게")
    rules.append("6) 인용구: ㄴ 인용구 3번")
    rules.append("7) 링크: ㄴ 링크도구로연결")
    rules.append("8) 멀티라인: ㄴ 두 줄 모두, 글자 색 파란색")
    rules.append("   → 허용: 두/세/네/다섯 줄 모두")
    rules.append("9) 복합 서식: 쉼표(,)로 연결")
    rules.append("   → ㄴ 글자 크기 19, 글꼴 두껍게, 노란 형광펜")
    rules.append("")
    rules.append("■ 절대 금지 패턴:")
    rules.append("- ㄴ /글자크기, ㄴ /글자색 같은 닫는 태그 → 존재하지 않는 문법")
    rules.append("- ㄴ 줄을 텍스트 위에 배치 → 반드시 텍스트 아래에")
    rules.append("- '글자색' 붙여쓰기 → '글자 색' 띄어쓰기")
    rules.append("- '연한회색', '연한 회색' → '옅은 회색'으로 써야 함")
    rules.append("- '아주 옅은 회색' → '많이 옅은 회색'으로 써야 함")
    rules.append("- '노란색 배경' → '노란 형광펜'으로 써야 함")
    rules.append("")
    rules.append("■ 올바른 예시 vs 잘못된 예시:")
    rules.append("")
    rules.append("[올바름] 속이 쓰리고 거북한 날이 많았어요.")
    rules.append("ㄴ '속이 쓰리고' 빨간색, 글꼴 두껍게")
    rules.append("")
    rules.append("[잘못됨] ㄴ 글자 크기 11, 글자색 연한회색")
    rules.append("속이 쓰리고 거북한 날이 많았어요.")
    rules.append("ㄴ /글자크기, /글자색")
    rules.append("→ 닫는 태그 금지, 글자색 붙여쓰기 금지, 연한회색 금지, ㄴ줄이 텍스트 위에 옴")
    rules.append("")
    rules.append("[올바름] 조금씩 루틴으로 자리 잡혔어요.")
    rules.append("ㄴ 글자 크기 19, 글자 색 파란색, 노란 형광펜")
    rules.append("")
    rules.append("[잘못됨] 조금씩 루틴으로 자리 잡혔어요.")
    rules.append("ㄴ 글자크기 19, 파란색, 노란색 배경")
    rules.append("→ '글자크기' 붙여쓰기 금지, 색상만 단독 사용 시 '글자 색' 필요, '노란색 배경' 금지")

    # 서식 활용 지침
    rules.append("\n\n===== 서식 활용 지침 (가장 중요 — 시각적으로 풍성하게) =====")
    rules.append("원고에 색상, 볼드, 형광펜, 글자 크기 변화를 적극적으로 활용하세요.")
    rules.append("서식이 없는 밋밋한 원고는 절대 안 됩니다.")
    rules.append("")
    rules.append("■ 색상 적용 방식 (3가지를 골고루 섞어서 사용):")
    rules.append("1) 멀티라인 전체 색상 (연속된 줄이 하나의 의미일 때)")
    rules.append("2) 한 줄 전체 색상")
    rules.append("3) 단어/구절 색상 (문장 속 특정 부분만 강조)")
    rules.append("4) 부정↔긍정 대비 색상 (빨강→파랑 연속)")
    rules.append("")
    rules.append("■ 색상별 활용 기준:")
    rules.append("- 빨간색: 부정적 상황, 증상, 경고, 위험 수치")
    rules.append("- 파란색: 긍정적 변화, 개선, 결심, 전환점")
    rules.append("- 보라색/청록색: 인용 대화, 감정 표현")
    rules.append("")
    rules.append("■ 색상을 넣지 않는 곳:")
    rules.append("- 일상적 연결 문장, 단순 상황 설명")
    rules.append("- 전체 본문의 30~40%만 색상. 나머지 60~70%는 색상 없는 일반 텍스트!")
    rules.append("")
    rules.append("■ 글씨 색 분량 기준:")
    rules.append("- 색상 ㄴ 지시를 원고 전체에서 12~18회 사용")
    rules.append("- 멀티라인 : 한 줄 : 단어 = 4 : 3 : 3 비율")
    rules.append("")
    rules.append("■ 형광펜 활용 (최소 5~7회)")
    rules.append(f"■ 강조 글자 크기 (소제목 제외, 최소 3~5회): 글자 크기 {emphasis_fontsize}")

    # 면책 문구 금지
    rules.append("\n\n===== 면책 문구 금지 =====")
    rules.append("'* 개인의 경험이며, 효과는 개인마다 다를 수 있습니다.' 같은 면책 문구는 절대 넣지 마세요.")

    # 이미지 배치 규칙
    rules.append("\n\n===== 이미지 배치 규칙 (매우 중요) =====")
    if img_count != "자동":
        rules.append(f"이미지를 총 {img_count}장 사용해주세요. (0번 대표 이미지 포함)")
    rules.append("이미지는 본문 전체에 걸쳐 균등하게 분배. 한 곳에 몰아 넣지 마세요.")
    rules.append("본문 내용이 끝난 후에는 절대 이미지를 넣지 마세요.")
    rules.append("이미지 사이에 본문 텍스트가 최소 5줄 이상 있어야 합니다.")

    # 제품 링크 전환 규칙
    rules.append("\n\n===== 제품 링크 전환 규칙 (광고 느낌 방지) =====")
    rules.append("제품 링크 전에 '왜 이 링크를 남기는지' 자연스러운 전환 멘트를 작성하세요.")
    rules.append("'+)' 또는 'ps.' 같은 추신 형태로 자연스럽게 시작")
    rules.append("전환 멘트는 2~4줄 정도로 짧게")

    # 글자크기 제한
    rules.append(f"\n[중요] 'ㄴ' 서식 지시에서 글자 크기는 반드시 11, 13, 15, 16, 19, 24, 28 중 하나만 사용하세요.")
    rules.append(f"[중요] 기본 글자 크기는 {font_size}입니다. 기본 크기와 같은 값을 지시하지 마세요.")

    return "\n".join(rules)


def build_prompt(sheet_data, product_name, prompt_type, style_name,
                 tone, font_size, alignment, quote_num, keywords, sub_keywords,
                 selected_refs, extra_instructions, include_toc,
                 product_link="",
                 char_count="3000~3300", img_count="자동",
                 color_positive="파란색", color_negative="빨간색",
                 highlight_emphasis="노란 형광펜", color_product="없음",
                 highlight_product="없음", title_repeat=True,
                 emphasis_fontsize="14",
                 safety_appeal_points=None):
    """심의안전 원고용 프롬프트 조립
    반환: (system_prompt, user_prompt, sample_fname)
    - system_prompt: 역할 + 고정 규칙 (시트 B열 + _get_fixed_rules)
    - user_prompt: 변수값만 (키워드, 소구점, 참고자료, 추가지시)
    """

    # ── 시트에서 system/user 템플릿 로드 ──
    prompt_data = sheet_data.get("safety_prompts", {}).get(prompt_type, {})

    if isinstance(prompt_data, dict):
        system_base = prompt_data.get("system", "") or DEFAULT_SYSTEM_PROMPT
        user_template = prompt_data.get("user_template", "")
    else:
        # 기존 형식(문자열) 호환
        system_base = DEFAULT_SYSTEM_PROMPT
        user_template = prompt_data

    # ── system_prompt 조립: 시트 B열 + 고정 규칙 ──
    fixed_rules = _get_fixed_rules(font_size, emphasis_fontsize, img_count)
    system_prompt = system_base + "\n\n" + fixed_rules

    # 서식 규칙 (시트 — 고정 성격이므로 system에 포함)
    fmt_template = sheet_data.get("format_instructions") or ""
    if fmt_template:
        link_text = product_link if product_link else "(제품 링크)"
        toc_instruction = ("- 목차를 포함합니다. 소제목 목록을 본문 초반에 넣어주세요." if include_toc
                           else "- 목차를 넣지 않습니다.")
        title_repeat_instruction = (
            "이미지 00 다음에 SEO 타이틀(제목)을 3줄 반복 작성하고, "
            "그 아래에 'ㄴ 세 줄 모두, 글자 크기 11, 아주 옅은 회색' 서식 지시를 넣습니다."
        ) if title_repeat else "SEO 타이틀(제목)을 3번 반복하지 않습니다."
        hl_emphasis = highlight_emphasis if highlight_emphasis != "없음" else "글꼴 두껍게"
        clr_product = color_product if color_product != "없음" else "글꼴 두껍게"
        hl_product = highlight_product if highlight_product != "없음" else "글꼴 두껍게"
        import re
        fmt_template = re.sub(r'(?m)^.*해시태그.*$\n?', '', fmt_template)
        try:
            system_prompt += "\n\n" + fmt_template.format(
                font_size=font_size, align_text=alignment,
                quote_num=quote_num, toc_instruction=toc_instruction,
                product_link=link_text,
                color_positive=color_positive, color_negative=color_negative,
                highlight_emphasis=hl_emphasis,
                color_product=clr_product, highlight_product=hl_product,
                title_repeat=title_repeat_instruction,
                emphasis_fontsize=emphasis_fontsize,
            )
        except KeyError as e:
            system_prompt += f"\n\n[서식규칙 오류: 알 수 없는 플레이스홀더 {e}]"

    # ── user_prompt 조립: 변수값만 ──
    parts = []

    # 소구점 텍스트 정규화 (문자열이면 그대로, 리스트면 join)
    points_text = ""
    if safety_appeal_points:
        if isinstance(safety_appeal_points, list):
            points_text = "\n".join(f"- {p}" for p in safety_appeal_points)
        else:
            points_text = str(safety_appeal_points)

    # 1) user prompt 템플릿 (시트 C열 — 변수 치환)
    if user_template:
        try:
            rendered = user_template.format(
                keyword=keywords or "",
                type=prompt_type or "",
                points=points_text,
                link=product_link or "",
            )
            parts.append(rendered)
        except KeyError:
            parts.append(user_template)
    else:
        # C열이 비어있으면 폴백 템플릿 사용
        fallback = (
            "아래 입력값으로 원고를 작성해주세요.\n\n"
            "키워드: {keyword}\n"
            "제품 유형: {type}\n"
            "제품 정보 및 소구점: {points}\n"
            "제품 링크: {link}"
        ).format(
            keyword=keywords or "",
            type=prompt_type or "",
            points=points_text,
            link=product_link or "",
        )
        parts.append(fallback)

    # 3) 글자수
    parts.append(f"\n\n===== 글자수 =====\n총 글자수 {char_count}자 범위로 작성해주세요.")

    # 4) 작가 스타일
    style_desc = sheet_data["styles"].get(style_name, "")
    if style_desc:
        parts.append(f"\n\n===== 작가 스타일 =====\n{style_desc}")

    # 5) 톤
    if tone == "반말":
        parts.append("\n\n===== 문체 =====")
        parts.append("반말(~거든, ~잖아, ~했더니, ~인 거야)로 작성해주세요.")
        parts.append("친구에게 말하듯 편안하고 자연스러운 톤으로 써주세요.")
    else:
        parts.append("\n\n===== 문체 =====")
        parts.append("존댓말(~입니다, ~했어요, ~더라고요, ~하셨나요)로 작성해주세요.")
        parts.append("정중하면서도 친근한 톤으로 써주세요.")

    # 6) 샘플 원고 (few-shot)
    sample_fname, sample_text = load_sample_for_type(prompt_type, product_name, sheet_data)
    if sample_text:
        parts.append("\n\n===== 참고 원고 예시 (톤/구조/서식 참고용) =====")
        parts.append("아래는 같은 유형으로 잘 작성된 실제 원고 예시입니다.")
        parts.append("이 원고의 톤, 문장 길이, 줄 끊기, 서식 지시(ㄴ), 이미지 배치, 전체 흐름을 참고하여 작성해주세요.")
        parts.append("단, 내용은 그대로 베끼지 말고 이번 키워드/제품/페르소나에 맞게 새로 작성합니다.")
        parts.append(f"\n--- 예시 원고 시작 ---\n{sample_text}\n--- 예시 원고 끝 ---")

    # 7) 참고자료 (제품마다 다름 → user)
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

    # 8) 추가 지시사항
    if extra_instructions:
        parts.append(f"\n\n===== 추가 지시사항 =====\n{extra_instructions}")

    user_prompt = "\n".join(parts)

    return system_prompt, user_prompt, sample_fname

