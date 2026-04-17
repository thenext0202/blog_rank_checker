"""원고 제작기 — 서식 파싱 (ㄴ 지시) + Word 출력 (.docx)"""
import re


# ╔══════════════════════════════════════════════════════════════╗
# ║  서식 파싱 (ㄴ 지시 → 서식 딕셔너리)                          ║
# ╚══════════════════════════════════════════════════════════════╝

def parse_annotation(annotation_text):
    """ㄴ 서식 지시 줄 → 서식 딕셔너리
    예: 'ㄴ 글자 크기 16, 글꼴 두껍게, 노란 형광펜'
    """
    from docx.enum.text import WD_COLOR_INDEX
    text = annotation_text.lstrip('ㄴ').strip()
    fmt = {
        'font_size': None,
        'bold': False,
        'italic': False,
        'underline': False,
        'colored_words': [],   # [(word, color_name), ...]
        'full_text_color': None,  # 전체 글자색 (옅은회색 등)
        'full_text_color_hex': None,  # 헥스 직접 지정: '0000FF' 등
        'highlight': None,     # WD_COLOR_INDEX 값
        'quote': None,
        'link': False,
        'multi_line': 1,
        'is_image_desc': False,
        'target_words': [],    # — "단어" / "단어" — 형태로 지정된 타겟 단어들
    }

    # 이미지 설명: ㄴ (혈압 측정하는 모습 사진)
    if text.startswith('(') and text.endswith(')'):
        fmt['is_image_desc'] = True
        return fmt

    # 인용구 N번
    m = re.search(r'인용구\s*(\d+)\s*번', text)
    if m:
        fmt['quote'] = int(m.group(1))

    # 글자 크기 (유효 크기만 허용) — '글자 크기 N' 또는 'Npt' 표기 수용
    VALID_FONT_SIZES = [11, 12, 13, 15, 16, 19, 24, 28]
    m = re.search(r'글자\s*크기\s*(\d+)', text)
    if not m:
        m = re.search(r'(\d+)\s*pt\b', text, re.IGNORECASE)
    if m:
        requested = int(m.group(1))
        fmt['font_size'] = min(VALID_FONT_SIZES, key=lambda x: abs(x - requested))

    # 볼드 — '글꼴 두껍게' / '두껍게' / '볼드' / 'bold'
    if re.search(r'글꼴\s*두껍게|두껍게|볼드|bold', text, re.IGNORECASE):
        fmt['bold'] = True

    # 밑줄 — '밑줄' / 'underline'
    if re.search(r'밑줄|underline', text, re.IGNORECASE):
        fmt['underline'] = True

    # 이탤릭 / 기울임
    if re.search(r'이탤릭|기울임|글꼴\s*기울임', text):
        fmt['italic'] = True

    # 글자색 전체 적용: "글자색 옅은 회색", "글자색 파란색" 등 (특정 단어가 아닌 전체)
    full_color_map = {
        '옅은 회색': '옅은회색', '많이 옅은 회색': '많이옅은회색',
        '회색': '회색', '진한 회색': '진한회색',
        '빨간색': '빨간색', '파란색': '파란색', '청록색': '청록색',
        '초록색': '초록색', '보라색': '보라색', '주황색': '주황색',
    }
    for pattern, color_key in full_color_map.items():
        if re.search(rf'글자\s*색\s*{re.escape(pattern)}', text):
            fmt['full_text_color'] = color_key
            break

    # 색상 키워드: '단어' 빨간색 형태 ('단어1', '단어2' 파란색 도 지원)
    color_names = ['빨간색', '파란색', '청록색', '초록색', '보라색', '주황색', '회색']
    for color_name in color_names:
        m = re.search(rf"((?:'[^']+'\s*,?\s*)+)\s*{color_name}", text)
        if m:
            words = re.findall(r"'([^']+)'", m.group(1))
            for w in words:
                fmt['colored_words'].append((w, color_name))

    # 헥스 직접 지정: '빨간색(FF0000)', '파란색(0000FF)', '파란색(1155CC)' 등
    m = re.search(
        r'(빨간색|파란색|청록색|초록색|보라색|주황색|회색|하늘색|노란색)'
        r'\s*\(\s*#?([0-9A-Fa-f]{6})\s*\)', text)
    if m:
        fmt['full_text_color_hex'] = m.group(2).upper()

    # 따옴표 없는 색상명 단독 표기 → 전체 글자색 (헥스/colored_words/full_text_color가 없을 때만)
    # 예: 'ㄴ 파란색, 볼드' → full_text_color = 파란색
    # 가드: 색상명 앞에 '형광펜' 수식 또는 색상명 앞 글자가 '색'이면 (진한 회색 등) 이미 처리됨
    if (not fmt['full_text_color_hex']
            and not fmt['colored_words']
            and not fmt['full_text_color']):
        for cn in ['빨간색', '파란색', '청록색', '초록색', '보라색', '주황색', '회색', '하늘색', '노란색']:
            # 앞뒤 경계: 앞에 따옴표/글자가 아니고, 뒤에 ( , 공백(다른 단어) 또는 줄끝
            m2 = re.search(rf"(?<![\'가-힣]){re.escape(cn)}(?=[\s,()]|$)", text)
            if m2:
                # '형광펜' 용법과 충돌 방지 — 색상명 바로 뒤가 형광펜이면 skip
                tail = text[m2.end():].strip()
                if tail.startswith('형광펜'):
                    continue
                fmt['full_text_color'] = cn
                break

    # 흰 글자 / 흰색 글자 / 흰 글씨 — 검정 형광펜 위 흰색 글자 지시
    if re.search(r'흰\s*(글자|색|글씨|색\s*글자)', text):
        fmt['full_text_color_hex'] = 'FFFFFF'

    # 형광펜 (노란/검정/파란/하늘/빨간/초록/청록)
    highlight_map = {
        '노란|노랑': WD_COLOR_INDEX.YELLOW,
        '검정|검은': WD_COLOR_INDEX.BLACK,
        '하늘': WD_COLOR_INDEX.TURQUOISE,   # 하늘색(cyan) → Word 표준 터콰이즈
        '파란|파랑': WD_COLOR_INDEX.BLUE,
        '빨간|빨강': WD_COLOR_INDEX.RED,
        '초록': WD_COLOR_INDEX.GREEN,
        '청록': WD_COLOR_INDEX.TEAL,
    }
    for hl_pattern, hl_val in highlight_map.items():
        if re.search(rf'(?:{hl_pattern})색?\s*형광펜', text):
            fmt['highlight'] = hl_val
            break

    # 링크 도구로 삽입/연결 (공백·표현 변형 허용)
    if re.search(r'링크\s*도구\s*로\s*(삽입|연결)', text):
        fmt['link'] = True

    # N줄 모두 (두/세/네/다섯)
    num_map = {'두': 2, '세': 3, '네': 4, '다섯': 5}
    m = re.search(r'(두|세|네|다섯)\s*줄\s*모두', text)
    if m:
        fmt['multi_line'] = num_map.get(m.group(1), 1)

    # 타겟 단어 추출 — 대시(—/–/-) 주변의 큰따옴표 단어
    # 예: 'ㄴ 하늘색 형광펜, 볼드 — "오메가3추천"' → target_words=['오메가3추천']
    # 예: 'ㄴ "블러디션 배합" — 검정 형광펜, 볼드' → target_words=['블러디션 배합']
    target_words_found = []
    for m in re.finditer(r'[—–\-]\s*"([^"]+)"', text):
        target_words_found.append(m.group(1))
    for m in re.finditer(r'"([^"]+)"\s*[—–\-]', text):
        target_words_found.append(m.group(1))
    # 중복 제거(순서 유지)
    seen = set()
    for w in target_words_found:
        if w not in seen:
            fmt['target_words'].append(w)
            seen.add(w)

    return fmt


def _is_self_reference_annotation(text):
    """ㄴ 주석 자신의 표시 스펙만 담긴 줄인지 판별.

    예: 'ㄴ 초록 형광펜' / 'ㄴ 초록 형광펜, 24pt, 볼드'
    — ㄴ 주석은 이미 초록 형광펜 24pt 볼드로 자동 표시되므로 이런 줄은 무시해야 함.
    '초록 형광펜'이 들어있고, 나머지가 크기·pt·볼드·구분자뿐이면 True.
    """
    s = text.lstrip('ㄴ').strip()
    if not re.search(r'초록\s*형광펜', s):
        return False
    cleaned = re.sub(r'초록\s*형광펜', '', s)
    cleaned = re.sub(r'\d+\s*pt', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'글자\s*크기\s*\d+', '', cleaned)
    # 볼드/두껍게/bold 키워드도 self-reference 판정 시 제거
    cleaned = re.sub(r'글꼴\s*두껍게|두껍게|볼드|bold', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'[,\s]', '', cleaned)
    return cleaned == ''


def _annotation_display_text(ann):
    """ㄴ 주석 줄을 Word 화면에 표시할 때 쓰는 정제 텍스트.
    - 색상명 뒤 (헥스코드) 제거: '빨간색(FF0000)' → '빨간색'
    - 링크 지시 포함되면 'ㄴ 링크 도구로 삽입' 단독으로 치환
    """
    if re.search(r'링크\s*도구\s*로\s*(삽입|연결)', ann):
        return 'ㄴ 링크 도구로 삽입'
    return re.sub(
        r'(빨간색|파란색|청록색|초록색|보라색|주황색|회색|하늘색|노란색)\s*\(\s*#?[0-9A-Fa-f]{6}\s*\)',
        r'\1', ann)


def _is_format_annotation(text):
    """ㄴ로 시작하는 줄이 서식 지시인지 콘텐츠인지 판별.
    서식 키워드가 있으면 True, 없으면 False (일반 콘텐츠)."""
    stripped = text.lstrip('ㄴ').strip()
    if stripped.startswith('(') and stripped.endswith(')'):
        return True
    if re.search(r'글자\s*크기|글꼴\s*두껍게|두껍게|형광펜|인용구|이탤릭|기울임|링크\s*도구|줄\s*모두|글자\s*색', stripped):
        return True
    # 볼드/밑줄/pt 표기
    if re.search(r'볼드|bold|밑줄|underline|\d+\s*pt\b', stripped, re.IGNORECASE):
        return True
    # 'N단어' 형태 색상 (기존)
    if re.search(r"'[^']+'\s*(빨간색|파란색|청록색|초록색|보라색|주황색|회색)", stripped):
        return True
    # 색상명 + 헥스 괄호 / 색상명 + 쉼표·괄호·줄끝 (단독 색상 지시)
    if re.search(
            r'(빨간색|파란색|청록색|초록색|보라색|주황색|회색|하늘색|노란색)\s*(\(|,|$)',
            stripped):
        return True
    return False


# ╔══════════════════════════════════════════════════════════════╗
# ║  색상/스타일 헬퍼                                             ║
# ╚══════════════════════════════════════════════════════════════╝

def _get_color_name_to_rgb():
    from docx.shared import RGBColor
    return {
        '빨간색': RGBColor(0xFF, 0x00, 0x00),
        '파란색': RGBColor(0x00, 0x70, 0xC0),
        '하늘색': RGBColor(0x87, 0xCE, 0xEB),
        '노란색': RGBColor(0xFF, 0xC0, 0x00),
        '청록색': RGBColor(0x00, 0x80, 0x80),
        '초록색': RGBColor(0x00, 0x80, 0x00),
        '보라색': RGBColor(0x70, 0x30, 0xA0),
        '주황색': RGBColor(0xED, 0x7D, 0x31),
        '회색': RGBColor(0x80, 0x80, 0x80),
        '많이옅은회색': RGBColor(0xC0, 0xC0, 0xC0),
        '옅은회색': RGBColor(0xA0, 0xA0, 0xA0),
        '진한회색': RGBColor(0x50, 0x50, 0x50),
    }


def _split_colored_words_across_targets(targets, colored_words):
    """colored_words 텍스트가 여러 문단에 걸칠 때 문단별로 분리.
    Returns: dict[int, list[(word, color)]] or None (분리 불필요 시)
    """
    if not colored_words or len(targets) <= 1:
        return None
    spanning = [w for w, _ in colored_words if not any(w in t for _, t in targets)]
    if not spanning:
        return None

    all_texts = [t for _, t in targets]
    joined = ' '.join(all_texts)
    char_colors = [None] * len(joined)
    for word, color_name in colored_words:
        for m in re.finditer(re.escape(word), joined):
            for j in range(m.start(), m.end()):
                char_colors[j] = color_name
    result = {}
    pos = 0
    for idx, (_, para_text) in enumerate(targets):
        para_cw = []
        pc = char_colors[pos:pos + len(para_text)]
        i = 0
        while i < len(para_text):
            if pc[i] is not None:
                color = pc[i]
                j = i
                while j < len(para_text) and pc[j] == color:
                    j += 1
                para_cw.append((para_text[i:j], color))
                i = j
            else:
                i += 1
        result[idx] = para_cw
        pos += len(para_text) + 1  # +1 for space separator
    return result


# ╔══════════════════════════════════════════════════════════════╗
# ║  Word 출력 (.docx)                                           ║
# ╚══════════════════════════════════════════════════════════════╝

def _build_styled_segments(original_text, colored_words):
    """텍스트를 마크다운 볼드/이탤릭 + 색상 키워드 기준으로 세그먼트 분할"""
    md_re = re.compile(r'\*\*\*(.+?)\*\*\*|\*\*(.+?)\*\*|\*(.+?)\*')

    chunks = []  # (text, is_bold, is_italic)
    last = 0
    for m in md_re.finditer(original_text):
        if m.start() > last:
            chunks.append((original_text[last:m.start()], False, False))
        if m.group(1):       # ***bold italic***
            chunks.append((m.group(1), True, True))
        elif m.group(2):     # **bold**
            chunks.append((m.group(2), True, False))
        elif m.group(3):     # *italic*
            chunks.append((m.group(3), False, True))
        last = m.end()
    if last < len(original_text):
        chunks.append((original_text[last:], False, False))

    if not colored_words:
        return [(t, {'bold': b, 'italic': it, 'color': None})
                for t, b, it in chunks]

    visible_text = ''.join(c[0] for c in chunks)
    char_colors = [None] * len(visible_text)
    for word, color_name in colored_words:
        for m in re.finditer(re.escape(word), visible_text):
            for j in range(m.start(), m.end()):
                char_colors[j] = color_name

    segments = []
    pos = 0
    for chunk_text, is_bold, is_italic in chunks:
        i = 0
        while i < len(chunk_text):
            current_color = char_colors[pos + i]
            j = i
            while j < len(chunk_text) and char_colors[pos + j] == current_color:
                j += 1
            segments.append((chunk_text[i:j], {'bold': is_bold, 'italic': is_italic, 'color': current_color}))
            i = j
        pos += len(chunk_text)

    return segments


def _clear_paragraph_runs(para):
    """기존 run 제거 (pPr 유지)"""
    from docx.oxml.ns import qn
    p_elem = para._element
    for r in list(p_elem.findall(qn('w:r'))):
        p_elem.remove(r)


def _apply_quote_border(paragraph, quote_num):
    """인용구 스타일 — 왼쪽 컬러 테두리"""
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    color_map = {
        1: '4472C4', 2: '70AD47', 3: 'ED7D31',
        4: 'FFC000', 5: '5B9BD5', 6: '7030A0',
    }
    border_color = color_map.get(quote_num, '4472C4')
    pPr = paragraph._element.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    left = OxmlElement('w:left')
    left.set(qn('w:val'), 'single')
    left.set(qn('w:sz'), '18')
    left.set(qn('w:space'), '8')
    left.set(qn('w:color'), border_color)
    pBdr.append(left)
    pPr.append(pBdr)


def _apply_formatting_to_para(para, original_text, fmt):
    """ㄴ 서식 딕셔너리를 해당 문단에 실제 적용.

    규칙: 원문에 `**..**` 볼드 마크다운이 하나라도 있으면 **색/형광펜/밑줄/볼드는 그 범위에만** 적용.
    없으면 단락 전체에 적용. 글자 크기와 인용구는 항상 단락 전체.
    target_words가 있으면 해당 단어에만 색/형광펜/볼드/밑줄 적용 (문단 전체 X).
    """
    from docx.shared import Pt, RGBColor
    BLUE_C = RGBColor(0x00, 0x70, 0xC0)

    is_quote = bool(fmt.get('quote'))
    target_words = fmt.get('target_words') or []

    # ── target_words 경로: 해당 단어에만 서식 적용 ──
    if target_words and not is_quote:
        # 이 para 안에 target_word가 하나도 없으면 건드리지 않음
        if not any(w in original_text for w in target_words):
            return
        _clear_paragraph_runs(para)

        char_is_target = [False] * len(original_text)
        for w in target_words:
            for m in re.finditer(re.escape(w), original_text):
                for j in range(m.start(), m.end()):
                    char_is_target[j] = True

        _color_map = _get_color_name_to_rgb()
        i = 0
        while i < len(original_text):
            cur = char_is_target[i]
            j = i
            while j < len(original_text) and char_is_target[j] == cur:
                j += 1
            seg_text = original_text[i:j]
            run = para.add_run(seg_text)
            if fmt.get('font_size'):
                run.font.size = Pt(fmt['font_size'])
            if cur:
                if fmt.get('bold'):
                    run.bold = True
                if fmt.get('italic'):
                    run.italic = True
                if fmt.get('underline'):
                    run.underline = True
                if fmt.get('full_text_color_hex'):
                    run.font.color.rgb = RGBColor.from_string(fmt['full_text_color_hex'])
                elif fmt.get('full_text_color') and fmt['full_text_color'] in _color_map:
                    run.font.color.rgb = _color_map[fmt['full_text_color']]
                if fmt.get('highlight'):
                    run.font.highlight_color = fmt['highlight']
            i = j
        return

    _clear_paragraph_runs(para)
    segments = _build_styled_segments(original_text, fmt.get('colored_words', []))
    has_md_bold_spans = bool(re.search(r'\*\*[^*]+\*\*', original_text))

    for seg_text, seg_props in segments:
        run = para.add_run(seg_text)
        # 크기는 단락 전체
        if fmt.get('font_size'):
            run.font.size = Pt(fmt['font_size'])

        # 볼드: 인용구·세그먼트 볼드·colored_words 범위는 그대로,
        # 그 외 fmt.bold는 ** 범위가 없을 때만 전체 적용.
        if is_quote:
            run.bold = True
        elif seg_props.get('bold'):
            run.bold = True
        elif fmt.get('bold') and seg_props.get('color'):
            run.bold = True
        elif fmt.get('bold') and not fmt.get('colored_words') and not has_md_bold_spans:
            run.bold = True

        if fmt.get('italic') or seg_props.get('italic'):
            run.italic = True

        # 시각 서식(색/형광펜/밑줄) 적용 범위 결정
        apply_visual = (not has_md_bold_spans) or seg_props.get('bold')

        if apply_visual and fmt.get('underline'):
            run.underline = True

        if not is_quote and apply_visual:
            _color_map = _get_color_name_to_rgb()
            color_name = seg_props.get('color')
            if color_name and color_name in _color_map:
                run.font.color.rgb = _color_map[color_name]
            elif fmt.get('full_text_color_hex'):
                # 헥스 직접 지정 — '빨간색(FF0000)', '파란색(1155CC)' 등
                run.font.color.rgb = RGBColor.from_string(fmt['full_text_color_hex'])
            elif fmt.get('full_text_color'):
                ftc = fmt['full_text_color']
                if ftc in _color_map:
                    run.font.color.rgb = _color_map[ftc]
            if fmt.get('highlight'):
                run.font.highlight_color = fmt['highlight']

    if fmt.get('link'):
        for run in para.runs:
            # 헥스가 명시돼 있으면 그대로 유지, 아니면 기본 파란색
            if not fmt.get('full_text_color_hex'):
                run.font.color.rgb = BLUE_C
            run.underline = True


def _add_text_runs(para, text):
    """마크다운 볼드/이탤릭 처리하여 run 추가"""
    md_re = re.compile(r'\*\*\*(.+?)\*\*\*|\*\*(.+?)\*\*|\*(.+?)\*')
    last = 0
    for m in md_re.finditer(text):
        if m.start() > last:
            para.add_run(text[last:m.start()])
        if m.group(1):
            run = para.add_run(m.group(1))
            run.bold = True
            run.italic = True
        elif m.group(2):
            run = para.add_run(m.group(2))
            run.bold = True
        elif m.group(3):
            run = para.add_run(m.group(3))
            run.italic = True
        last = m.end()
    if last < len(text):
        para.add_run(text[last:])


def _add_blogger_request_box(doc, lines):
    """★ 블로거 요청사항 → 빨간 테두리 + 노란 배경 테이블 박스"""
    from docx.shared import Pt, RGBColor
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    table = doc.add_table(rows=1, cols=1)
    table.style = 'Table Grid'
    cell = table.cell(0, 0)

    shading = OxmlElement('w:shd')
    shading.set(qn('w:fill'), 'FFF8E1')
    shading.set(qn('w:val'), 'clear')
    cell._element.get_or_add_tcPr().append(shading)

    tcBorders = OxmlElement('w:tcBorders')
    for side in ['top', 'left', 'bottom', 'right']:
        border = OxmlElement(f'w:{side}')
        border.set(qn('w:val'), 'single')
        border.set(qn('w:sz'), '12')
        border.set(qn('w:color'), 'FF0000')
        border.set(qn('w:space'), '0')
        tcBorders.append(border)
    cell._element.get_or_add_tcPr().append(tcBorders)

    first_para = cell.paragraphs[0]
    for i, line in enumerate(lines):
        para = cell.add_paragraph() if i > 0 else first_para
        run = para.add_run(line)
        run.bold = True
        run.font.color.rgb = RGBColor(0xCC, 0x00, 0x00)
        run.font.size = Pt(11)

    doc.add_paragraph('')


# ── _build_document: 텍스트 → docx.Document 객체 (서식 적용) ──
def _build_document(text):
    from docx import Document
    from docx.shared import Pt, RGBColor, Cm, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    doc = Document()
    style = doc.styles['Normal']
    style.font.name = '맑은 고딕'
    style.font.size = Pt(11)

    annotation_re = re.compile(r'^ㄴ\s*')
    image_num_re = re.compile(r'^\d{1,2}$')

    GREEN = RGBColor(0x00, 0x80, 0x00)
    BLUE = RGBColor(0x00, 0x70, 0xC0)

    lines = text.split('\n')
    # 연속된 ㄴ 서식 라인 병합 — 같은 단락에 두 번 apply되면 _clear_paragraph_runs가
    # 첫 번째 서식을 날려버리므로 하나의 ㄴ 라인으로 합쳐서 한 번에 적용한다.
    _merged = []
    _i = 0
    while _i < len(lines):
        _cur = lines[_i]
        _s = _cur.strip()
        # ㄴ 주석 자기-참조 줄(ㄴ 초록 형광펜 등)은 완전 제거
        if _s.startswith('ㄴ') and _is_self_reference_annotation(_s):
            _i += 1
            continue
        if _s.startswith('ㄴ') and _is_format_annotation(_s):
            _combined = _s
            _j = _i + 1
            while _j < len(lines):
                _nxt = lines[_j].strip()
                if _nxt.startswith('ㄴ') and _is_self_reference_annotation(_nxt):
                    _j += 1  # 병합 대상에서 제외, 라인 자체도 drop
                    continue
                if _nxt.startswith('ㄴ') and _is_format_annotation(_nxt):
                    _combined = _combined + ', ' + _nxt.lstrip('ㄴ').strip()
                    _j += 1
                else:
                    break
            _merged.append(_combined)
            _i = _j
        else:
            _merged.append(_cur)
            _i += 1
    lines = _merged
    recent = []  # (paragraph, original_text) 버퍼
    pending_fmts = []  # 아래 텍스트에 적용할 대기 서식
    blogger_req_lines = []
    in_blogger_req = False

    for line in lines:
        stripped = line.strip()

        # ── ★ 블로거 요청사항 수집 ──
        if '★' in stripped:
            in_blogger_req = True
            blogger_req_lines.append(stripped)
            continue

        if in_blogger_req:
            # 구분선(─/—/-) 5개 이상에서 박스 종료 (박스 밖에 구분선 텍스트 출력 X)
            if re.match(r'^[─—–\-]{5,}$', stripped):
                _add_blogger_request_box(doc, blogger_req_lines)
                blogger_req_lines = []
                in_blogger_req = False
                recent.append((doc.paragraphs[-1] if doc.paragraphs else None, ''))
                continue
            # ㄴ 서식 지시 줄은 박스 전체 서식용 표시이므로 drop (박스 내 노출 X)
            if stripped.startswith('ㄴ'):
                continue
            # 박스 내부의 빈 줄은 무시 (박스 닫지 않음)
            if not stripped:
                continue
            blogger_req_lines.append(stripped)
            continue

        # ── 빈 줄 ──
        if not stripped:
            p = doc.add_paragraph('')
            recent.append((p, ''))
            continue

        # ── 본문 중간에 ㄴ 서식이 섞인 경우 ──
        mid_ann = re.match(r'^(.+?)\s+ㄴ\s+(.+)$', stripped)
        if mid_ann and _is_format_annotation('ㄴ ' + mid_ann.group(2)):
            content_part = mid_ann.group(1).strip()
            ann_part = 'ㄴ ' + mid_ann.group(2).strip()
            p = doc.add_paragraph()
            _add_text_runs(p, content_part)
            recent.append((p, content_part))
            mid_fmt = parse_annotation(ann_part)
            if mid_fmt.get('colored_words'):
                if all(w in content_part for w, _ in mid_fmt['colored_words']):
                    _apply_formatting_to_para(p, content_part, mid_fmt)
                else:
                    pending_fmts.append((mid_fmt, []))
            elif not mid_fmt['is_image_desc']:
                _apply_formatting_to_para(p, content_part, mid_fmt)
            ap = doc.add_paragraph()
            ann_display = _annotation_display_text(ann_part)
            run = ap.add_run(ann_display)
            run.bold = True
            run.font.color.rgb = GREEN
            run.font.size = Pt(24)
            run.font.highlight_color = WD_COLOR_INDEX.BRIGHT_GREEN
            recent.append((ap, ann_display))
            continue

        # ── ㄴ 서식 지시 줄 (서식 키워드가 있는 것만) ──
        if annotation_re.match(stripped) and _is_format_annotation(stripped):
            fmt = parse_annotation(stripped)

            if fmt['is_image_desc']:
                continue

            content_paras = [(p, t) for p, t in recent
                             if t.strip() and not (re.match(r'^ㄴ\s*', t.strip()) and _is_format_annotation(t.strip()))]
            target_count = fmt['multi_line']

            # Approach B — 의미 블록 스캔:
            # ㄴ 위로 빈 줄/직전 ㄴ 서식 라인까지 거슬러 올라가 한 블록을 모은다.
            # 블록 안에 `**..**` 단락이 하나라도 있으면 **볼드가 있는 단락만** 타겟(볼드 없는 일반 문장은 스킵).
            # 없으면 블록 마지막 한 단락만 타겟.
            # 이 로직은 사용자가 '두 줄 모두' 등 multi_line을 명시하지 않고 colored_words도 없을 때만 동작.
            if target_count == 1 and not fmt.get('colored_words') and not fmt.get('target_words'):
                block = []
                for p_r, t_r in reversed(recent):
                    t_s = t_r.strip() if t_r else ''
                    if not t_s:
                        break
                    if re.match(r'^ㄴ\s*', t_s) and _is_format_annotation(t_s):
                        break
                    block.append((p_r, t_r))
                block.reverse()

                if block:
                    bold_paras = [(p, t) for p, t in block
                                  if re.search(r'\*\*[^*]+\*\*', t.strip())]
                    if bold_paras:
                        targets = bold_paras
                    else:
                        # 블록 안에 **..** 볼드 범위가 없으면 블록 전체에 적용
                        targets = block
                else:
                    targets = []
            else:
                targets = content_paras[-target_count:] if content_paras else []

            applied = False
            # colored_words / target_words 모두 "단어 기반" 타겟팅이라 fallback 로직 공유
            search_words = (
                [w for w, _ in fmt.get('colored_words', [])]
                + list(fmt.get('target_words', []))
            )
            if search_words:
                if targets:
                    all_target_text = ' '.join(t for _, t in targets)
                    missing = any(w not in all_target_text for w in search_words)
                    if missing and len(content_paras) > target_count:
                        found = False
                        for ext in range(target_count + 1, min(target_count + 8, len(content_paras) + 1)):
                            targets = content_paras[-ext:]
                            all_target_text = ' '.join(t for _, t in targets)
                            if all(w in all_target_text for w in search_words):
                                found = True
                                break
                        if found:
                            applied = True
                        else:
                            pending_fmts.append((fmt, []))
                    elif not missing:
                        applied = True
                    else:
                        pending_fmts.append((fmt, []))
                else:
                    pending_fmts.append((fmt, []))
            else:
                applied = True

            if applied:
                per_para_cw = _split_colored_words_across_targets(targets, fmt.get('colored_words', []))
                for idx, (para, para_text) in enumerate(targets):
                    if per_para_cw and idx in per_para_cw:
                        para_fmt = dict(fmt)
                        para_fmt['colored_words'] = per_para_cw[idx]
                        _apply_formatting_to_para(para, para_text, para_fmt)
                    else:
                        _apply_formatting_to_para(para, para_text, fmt)

            # ㄴ 줄 자체 → 초록색 주석 (헥스괄호 제거, 링크는 단독 치환)
            display = _annotation_display_text(stripped)
            p = doc.add_paragraph()
            run = p.add_run(display)
            run.bold = True
            run.font.color.rgb = GREEN
            run.font.size = Pt(24)
            run.font.highlight_color = WD_COLOR_INDEX.BRIGHT_GREEN
            recent.append((p, display))
            continue

        # ── 이미지 번호 (00→0, 01→1, 02→2...) ──
        if image_num_re.match(stripped):
            display_num = str(int(stripped))
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run(display_num)
            run.bold = True
            run.font.size = Pt(14)
            run.font.color.rgb = BLUE
            recent.append((p, display_num))
            continue

        # ── 마크다운 헤딩 ──
        if stripped.startswith('### '):
            p = doc.add_heading(stripped.lstrip('# ').strip(), level=3)
            recent.append((p, stripped))
            continue
        if stripped.startswith('## '):
            p = doc.add_heading(stripped.lstrip('# ').strip(), level=2)
            recent.append((p, stripped))
            continue
        if stripped.startswith('# '):
            p = doc.add_heading(stripped.lstrip('# ').strip(), level=1)
            recent.append((p, stripped))
            continue

        # ── 일반 텍스트 ──
        p = doc.add_paragraph()
        _add_text_runs(p, stripped)
        recent.append((p, stripped))

        # ── 대기 중인 서식 적용 (ㄴ이 텍스트 위에 있었던 경우) ──
        if pending_fmts:
            new_pending = []
            for pfmt, collected in pending_fmts:
                collected.append((p, stripped))
                p_search_words = (
                    [w for w, _ in pfmt.get('colored_words', [])]
                    + list(pfmt.get('target_words', []))
                )
                if p_search_words:
                    all_text = ' '.join(t for _, t in collected)
                    if all(w in all_text for w in p_search_words):
                        per_para_cw = _split_colored_words_across_targets(collected, pfmt.get('colored_words', []))
                        for cidx, (cp, ct) in enumerate(collected):
                            if per_para_cw and cidx in per_para_cw:
                                p_fmt = dict(pfmt)
                                p_fmt['colored_words'] = per_para_cw[cidx]
                                _apply_formatting_to_para(cp, ct, p_fmt)
                            else:
                                _apply_formatting_to_para(cp, ct, pfmt)
                    elif len(collected) < 8:
                        new_pending.append((pfmt, collected))
                else:
                    _apply_formatting_to_para(p, stripped, pfmt)
            pending_fmts = new_pending

        if len(recent) > 15:
            recent = recent[-15:]

    # 남은 블로거 요청사항 처리
    if blogger_req_lines:
        _add_blogger_request_box(doc, blogger_req_lines)

    return doc


# ── 외부 인터페이스 ──
def save_as_docx(text, filepath):
    """텍스트 → 서식 적용된 .docx 파일 저장."""
    _build_document(text).save(filepath)


def build_docx_bytes_from_text(text):
    """텍스트 → 서식 적용된 .docx bytes (메모리 반환)."""
    from io import BytesIO
    buf = BytesIO()
    _build_document(text).save(buf)
    return buf.getvalue()
