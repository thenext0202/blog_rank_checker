"""LLM 출력 파서 — Phase A~D 분리 + 제목/본문/심의결과 추출."""
import re


PHASE_PATTERN = re.compile(
    r"===\s*Phase\s*([A-F](?:-2)?)\s*[:：][^=]*?===",
    re.IGNORECASE,
)


def split_phases(text):
    """'=== Phase X ===' 구분자 기준으로 섹션 분리.

    반환: {"A": "...", "B": "...", "B-2": "...", "C": "...", "D": "...", "E": "..."}
    """
    matches = list(PHASE_PATTERN.finditer(text))
    if not matches:
        return {"raw": text}

    sections = {}
    for i, m in enumerate(matches):
        key = m.group(1).upper()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[key] = _clean_section(text[start:end])
    return sections


def _clean_section(chunk):
    """섹션 본문 양끝 정리.

    - 선행 `**` 잔여물 제거: LLM이 `**=== Phase E ===**` 로 헤더를 감싸면
      뒤쪽 `**`가 본문 시작에 흡수됨.
    - 후행 `---`/`===` 구분선 제거: Phase 블록 사이 구분선이 이전 섹션 끝에 붙음.
    """
    s = chunk.strip()
    # 선행 ** 만 있는 라인 제거
    s = re.sub(r"^\*{2,}\s*(?:\n|$)", "", s)
    # 후행 ---/=== 구분선 제거 (여러 줄 반복도 처리)
    s = re.sub(r"(?:\n+[-=─_]{3,}\s*)+$", "", s)
    return s.strip()


def extract_title_body(phase_c_text):
    """Phase C에서 제목/본문 추출.

    허용 형식: '제목: ...', '**제목:** ...', '제목：...' 등
    """
    if not phase_c_text:
        return "", ""

    title = ""
    body = phase_c_text.strip()

    # 선행 구분선(===, ---) 제거
    body = re.sub(r"^[=\-]{3,}\s*\n+", "", body)

    # 제목 라인 추출 (마크다운 강조 허용)
    t_pat = re.compile(
        r"^\s*\*{0,2}\s*제목\s*\*{0,2}\s*[:：]\s*\*{0,2}\s*(.+?)\s*\*{0,2}\s*$",
        re.MULTILINE,
    )
    t_match = t_pat.search(body)
    if t_match:
        # 제목에 남은 ** 제거
        title = re.sub(r"\*+", "", t_match.group(1)).strip()
        body = body[t_match.end():].strip()

    # 구분선 제거 후 '본문' 라벨 제거 ('**본문:**' 형태 포함)
    body = re.sub(r"^[=\-]{3,}\s*\n+", "", body)
    body = re.sub(
        r"^\s*\*{0,2}\s*본문\s*[:：]?\s*\*{0,2}\s*\n+",
        "", body,
    )

    return title, body.strip()


# ── ㄴ 서식 지시 병합 (같은 타겟 색상/볼드/밑줄 등을 한 줄로) ───────────────
_COLOR_NAMES_RE = re.compile(
    r"(빨간색|파란색|청록색|초록색|보라색|주황색|회색|하늘색|노란색|검정|검은색|흰색)"
)
_FMT_KEYWORDS_RE = re.compile(
    r"(볼드|bold|밑줄|underline|형광펜|두껍게|이탤릭|기울임|인용구|\d+\s*pt|글자\s*크기)",
    re.IGNORECASE,
)


def _is_full_line_bold(stripped):
    """라인 전체가 `**...**` 로 완전히 감싸진 경우 내부 텍스트 반환, 아니면 None.

    내부에 또 다른 `**` 가 있으면(부분 볼드) None 반환.
    """
    m = re.match(r"^\*\*(.+?)\*\*$", stripped)
    if not m:
        return None
    inner = m.group(1)
    if "**" in inner:
        return None
    return inner.strip()


def _is_bold_only_specs(specs):
    """specs 목록이 볼드 계열 토큰(볼드/bold/두껍게)만 담고 있으면 True."""
    if not specs:
        return False
    for s in specs:
        t = re.sub(r"\s+", "", s).lower()
        if t not in ("볼드", "bold", "두껍게"):
            return False
    return True


def _is_merge_candidate_annotation(line):
    """ㄴ 라인이 '타겟 기준 병합' 대상인지 판정.

    병합 제외: 링크 도구 지시, 서식 키워드 없는 평문.
    """
    s = line.strip()
    if not s.startswith("ㄴ"):
        return False
    inner = s.lstrip("ㄴ").strip()
    if not inner:
        return False
    if re.search(r"링크\s*도구|도구로\s*(삽입|연결)", inner):
        return False
    return bool(_COLOR_NAMES_RE.search(inner) or _FMT_KEYWORDS_RE.search(inner))


def _parse_merge_annotation(line):
    """ㄴ 서식 라인 → (target, [specs])."""
    inner = line.lstrip("ㄴ").strip()
    # 타겟 단어 (첫 번째 인용부호 쌍) — 양끝 마크다운 별표 제거
    target = ""
    tm = re.search(r"""['"]([^'"]+)['"]""", inner)
    if tm:
        target = tm.group(1).strip().strip("*").strip()
    # 서식 토큰 — 인용부호·em-dash 제거 후 쉼표/슬래시로 split
    cleaned = re.sub(r"""['"][^'"]*['"]""", "", inner)
    cleaned = re.sub(r"[—–]+", " ", cleaned)
    specs = []
    for tok in re.split(r"[,/]+", cleaned):
        t = tok.strip(" -\t")
        if not t:
            continue
        if _COLOR_NAMES_RE.search(t) or _FMT_KEYWORDS_RE.search(t):
            specs.append(t)
    return target, specs


def _rebuild_annotation(target, specs):
    """(target, specs) → ㄴ 라인 문자열 — 중복 서식 제거."""
    seen = set()
    dedup = []
    for s in specs:
        k = re.sub(r"\s+", "", s).lower()
        if k in seen:
            continue
        seen.add(k)
        dedup.append(s)
    joined = ", ".join(dedup)
    if target:
        return f"ㄴ '{target}' {joined}" if joined else f"ㄴ '{target}'"
    return f"ㄴ {joined}" if joined else "ㄴ"


def _flush_buckets(order, buckets, result):
    for k in order:
        disp, specs = buckets[k]
        result.append(_rebuild_annotation(disp, specs))
    order.clear()
    buckets.clear()


def _merge_same_target_annotations(body):
    """본문 라인 아래 연속 ㄴ 서식 지시를 타겟 기준으로 묶어 한 줄로 병합.

    규칙:
    - 타겟이 본문 라인 전체와 동일하거나 타겟이 없으면 → `ㄴ {서식들}` (타겟 생략)
    - 타겟이 부분 단어면 같은 타겟끼리만 병합해 `ㄴ '단어' 서식들`
    - 인용구·링크 도구 지시는 병합 대상 제외 (원본 순서 유지)
    - 블로거 요청박스(★ 내부)는 건드리지 않음
    """
    if not body:
        return body
    lines = body.split("\n")
    out = []
    in_box = False
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        # 블로거 요청박스 진입/유지
        if "★" in stripped:
            in_box = True
            out.append(line)
            i += 1
            continue
        if in_box:
            out.append(line)
            if re.match(r"^[─—–\-]{5,}$", stripped):
                in_box = False
            i += 1
            continue
        # 본문 라인(ㄴ 아님 + 비어있지 않음)이면 뒤따르는 ㄴ 그룹 수집
        if stripped and not stripped.startswith("ㄴ"):
            out.append(line)
            j = i + 1
            group = []
            while j < len(lines) and lines[j].strip().startswith("ㄴ"):
                ann = lines[j]
                if _is_merge_candidate_annotation(ann):
                    tgt, specs = _parse_merge_annotation(ann)
                    group.append(("merge", ann, tgt, specs))
                else:
                    group.append(("keep", ann, None, None))
                j += 1
            if group:
                content_clean = re.sub(r"\*+", "", stripped).strip()
                # 본문 라인이 `**...**` 로 전체 감싸진 볼드인지 — 내부 텍스트 반환
                full_bold_inner = _is_full_line_bold(stripped)
                buckets = {}
                order = []
                for kind, orig, tgt, specs in group:
                    if kind == "keep":
                        _flush_buckets(order, buckets, out)
                        out.append(orig)
                        continue
                    # v2.1.5~: 본문이 `**..**` 볼드여도 사용자가 명시한 `ㄴ '..' 볼드` 주석은 유지.
                    # (이전엔 "중복"으로 판정해 드롭했으나, 사용자 명시 의도를 엔진이 임의 제거하면
                    # 라벨·ㄴ 주석이 사라져 사용자 혼란. 여러 문장 중 일부만 라벨 누락되는 버그 원인.)
                    # v2.1.4~: 타겟이 본문 라인 전체와 일치해도 타겟 유지.
                    is_full = not tgt
                    key = "" if is_full else tgt
                    if key not in buckets:
                        buckets[key] = ("" if is_full else tgt, [])
                        order.append(key)
                    buckets[key][1].extend(specs)
                _flush_buckets(order, buckets, out)
            i = j
            continue
        # 빈 줄·기타(예외적으로 단독 ㄴ로 시작하는 라인 등)
        out.append(line)
        i += 1
    return "\n".join(out)


def _enforce_product_ingredient_format(body, product_name):
    """배합명·제품 성분의 첫 등장 라인에 단어별 타겟 ㄴ 주석 주입.

    - 배합명(예: "블러디션 배합") → ㄴ 검정 형광펜, 볼드 — "배합명"
    - 성분명(예: "홍국") → ㄴ 노란 형광펜, 볼드 — "성분명"
    - 첫 등장만 주입. 이후 등장은 자동 주석 추가 안 함.
    - 기존 ㄴ 블록에 이미 같은 (단어+색상) 조합이 있으면 중복 안 함.

    이전 버전은 "성분 2개 이상 쉼표 라인 전체"를 **..**로 래핑 + ㄴ 노란 형광펜, 볼드를
    달았다. 이 방식은 문장 전체에 색이 퍼지고, 부분 문자열 매칭으로 오탐 위험이 있었다.
    새 버전은 단어 단위 타겟 주석만 붙여 해당 단어에만 강조가 적용되게 한다.
    ★ 블로거 요청박스 내부는 건드리지 않는다.
    """
    if not body or not product_name:
        return body
    import config  # 순환 임포트 회피 위해 함수 내부 임포트

    # (단어, 색상) 타겟 수집
    targets = []
    blend_name = None
    for row in getattr(config, "PRODUCTS", []):
        if len(row) >= 2 and row[0] == product_name:
            blend_name = (row[1] or "").strip()
            break
    if blend_name:
        targets.append((blend_name, "검정"))
    for ing in (config.PRODUCT_INGREDIENTS.get(product_name) or []):
        w = (ing or "").strip()
        if len(w) >= 2:  # 한 글자 성분은 오탐 위험 → 제외
            targets.append((w, "노란"))
    if not targets:
        return body
    # 긴 단어 우선 (부분 문자열 포함 관계일 때 긴 쪽이 먼저 매칭)
    targets.sort(key=lambda t: -len(t[0]))

    lines = body.split("\n")
    seen = set()  # 이미 주입한 (word, color)
    out = []
    in_box = False
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # 블로거 요청박스 통과
        if "★" in stripped:
            in_box = True
            out.append(line)
            i += 1
            continue
        if in_box:
            out.append(line)
            if re.match(r"^[─—–\-]{5,}$", stripped):
                in_box = False
            i += 1
            continue

        # 본문 라인 아님
        if not stripped or stripped.startswith("ㄴ"):
            out.append(line)
            i += 1
            continue

        out.append(line)
        clean = re.sub(r"\*+", "", stripped)

        # 이 라인에서 첫 등장하는 타겟
        first_hits = []
        for word, color in targets:
            key = (word, color)
            if key in seen:
                continue
            # 단어 경계: 영문·숫자만 경계로 체크 (한글 조사 "홍국과/홍국에는" 허용)
            pat = rf"(?<![A-Za-z0-9]){re.escape(word)}(?![A-Za-z0-9])"
            if re.search(pat, clean):
                first_hits.append((word, color))
                seen.add(key)

        # 기존 연속 ㄴ 블록 출력 + 내용 수집
        j = i + 1
        existing_block = []
        while j < len(lines) and lines[j].strip().startswith("ㄴ"):
            out.append(lines[j])
            existing_block.append(lines[j].strip())
            j += 1

        # 타겟 주석 주입 (기존 블록에 동일 단어+색상 조합 있으면 생략)
        for word, color in first_hits:
            duplicated = False
            for ann in existing_block:
                if word in ann and f"{color} 형광펜" in ann:
                    duplicated = True
                    break
            if not duplicated:
                # 표준: 단일따옴표 형식 (ANNOTATION_STANDARD.md 참조)
                out.append(f"ㄴ '{word}' {color} 형광펜, 볼드")

        i = j

    return "\n".join(out)


_EM_DASH_TARGET_RE = re.compile(r'\s*[—–\-]\s*"([^"]+)"\s*$')


def _em_dash_to_quote(body):
    """레거시 em-dash 타겟을 표준(단일따옴표) 형식으로 변환.

    `ㄴ 서식명 — "단어"` → `ㄴ '단어' 서식명`
    ANNOTATION_STANDARD.md 표준 통일(v2.1~) 이후 진입 시점에 한 번 실행.
    """
    if not body:
        return body
    lines = body.split("\n")
    for i, line in enumerate(lines):
        s = line.strip()
        if not s.startswith("ㄴ"):
            continue
        m = _EM_DASH_TARGET_RE.search(s)
        if not m:
            continue
        target = m.group(1).strip()
        rest = _EM_DASH_TARGET_RE.sub("", s).strip()
        rest = re.sub(r',\s*$', '', rest)  # tail 쉼표 제거
        inner = rest.lstrip("ㄴ").strip()
        # 이미 단일따옴표 타겟이 있다면 중복 방지
        if re.match(r"""^['"][^'"]+['"]\s+""", inner):
            lines[i] = f"ㄴ {inner}"
        else:
            lines[i] = f"ㄴ '{target}' {inner}"
    return "\n".join(lines)


def _inject_keyword_target(body, keyword):
    """하늘/노란/검정 형광펜 ㄴ 라인에 타겟이 빠져 있으면 keyword를 단일따옴표로 주입.

    표준(ANNOTATION_STANDARD.md): `ㄴ '단어' 서식명`
    - 이미 `'단어'` 타겟이 있으면 스킵
    - 타겟 없고 위 본문에 keyword 있으면 `ㄴ 'keyword' 서식명`으로 주입
    """
    if not body:
        return body
    kw = (keyword or "").strip()
    if not kw:
        return body
    lines = body.split("\n")
    hl_re = re.compile(r"(하늘|노란|검정|검은)\s*색?\s*형광펜")
    for i, line in enumerate(lines):
        s = line.strip()
        if not s.startswith("ㄴ"):
            continue
        inner = s.lstrip("ㄴ").strip()
        if not hl_re.search(inner):
            continue
        # 이미 단일따옴표 타겟이 있으면 스킵
        if re.match(r"""^['"][^'"]+['"]\s+""", inner):
            continue
        # 위 본문에 keyword 있을 때만 주입
        prev_idx = i - 1
        while prev_idx >= 0 and not lines[prev_idx].strip():
            prev_idx -= 1
        if prev_idx < 0:
            continue
        prev_clean = re.sub(r"\*+", "", lines[prev_idx]).strip()
        if kw not in prev_clean:
            continue
        lines[i] = f"ㄴ '{kw}' {inner}"
    return "\n".join(lines)


_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[가-힣a-z0-9])\.[ \t]+(?=[가-힣A-Z])")
_SENTENCE_SPLIT_ABBREV = (
    "Dr.", "Mr.", "Mrs.", "Ms.", "Prof.", "Ph.D.", "St.", "No.",
    "cm.", "kg.", "mm.", "km.", "ml.", "vs.",
)


def _split_sentences_after_period(body):
    """LLM이 `. 문장1. 문장2.` 를 한 줄에 낸 경우 `.\\n` 으로 자동 쪼갬.

    사용자 요구: 마침표 뒤에 이어지는 문장은 별도 줄에 있어야 함.
    예외:
    - 숫자 소수점(3.14) — 마침표 뒤가 숫자면 정규식에서 미매치
    - URL (https://…/ 뒤 공백 + 한글) — 앞 30자에 http:// 있으면 스킵
    - 약어 (Dr./Mr./Prof./cm. 등) — 약어 목록 체크
    - 블로거 요청박스(★) 내부 — 박스 단위로 건너뜀
    - ㄴ 지시문 / 빈 줄 — 건드리지 않음
    """
    if not body:
        return body
    lines = body.split("\n")
    out = []
    in_box = False
    for line in lines:
        stripped = line.strip()

        if "★" in stripped:
            in_box = True
            out.append(line)
            continue
        if in_box:
            out.append(line)
            if re.match(r"^[─—–\-]{5,}$", stripped):
                in_box = False
            continue

        if not stripped or stripped.startswith("ㄴ"):
            out.append(line)
            continue

        # 쪼개기 후보 위치 수집
        positions = []
        for m in _SENTENCE_SPLIT_PATTERN.finditer(line):
            dot_idx = m.start()
            # URL 체크
            left_window = line[max(0, dot_idx - 30):dot_idx]
            if re.search(r"https?://", left_window):
                continue
            # 약어 체크 — 마침표 앞 단어
            word_start = dot_idx
            while word_start > 0 and not line[word_start - 1].isspace():
                word_start -= 1
            prev_word = line[word_start:dot_idx + 1]
            if any(prev_word.endswith(a) for a in _SENTENCE_SPLIT_ABBREV):
                continue
            positions.append(dot_idx)

        # 뒤에서 앞으로 치환 (인덱스 보존): `. ` → `.\n`
        new_line = line
        for pos in reversed(positions):
            nxt = pos + 1
            while nxt < len(new_line) and new_line[nxt] in " \t":
                nxt += 1
            new_line = new_line[:pos + 1] + "\n" + new_line[nxt:]

        out.append(new_line)

    return "\n".join(out)


_CHECKLIST_CUTOFF_PATTERNS = [
    # 'Phase E 자체 점검:' (마크다운 볼드 ** 래핑 허용)
    re.compile(r"^\s*\*{0,2}\s*Phase\s*E\s*자체\s*점검", re.IGNORECASE),
    # 'E-3. 필수 점검:' / 'E-4. 일반 점검:'
    re.compile(r"^\s*\*{0,2}\s*E-[34]\s*[.．]", re.IGNORECASE),
    # '## E-3 …' 같은 헤딩 형태
    re.compile(r"^\s*#{1,6}\s*E-[34]\b", re.IGNORECASE),
    # Phase F 재출력 블록이 === 헤더 없이 Phase E 안으로 새어 들어온 경우 대비
    re.compile(r"^\s*\*{0,2}\s*Phase\s*F\s*(재출력|줄바꿈)", re.IGNORECASE),
    re.compile(r"^\s*\*{0,2}\s*Phase\s*E\s*재출력", re.IGNORECASE),
]


def _strip_phase_e_checklist(body):
    """Phase E 본문 끝에 AI가 자체 점검 결과(E-3/E-4 체크리스트)를 덧붙인 경우 잘라냄.

    모듈1 §E-3/E-4는 AI 내부 검증 절차 지시이나, LLM이 낮은 확률로 체크 결과를
    답변에 포함시켜 원고 끝에 `- [✓] 원고 대조 …` 같은 체크리스트가 노출됨.
    지침 금지만으로 100% 차단 안 되므로 첫 매치 라인부터 body 끝까지 일괄 제거.
    """
    if not body:
        return body
    lines = body.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        for pat in _CHECKLIST_CUTOFF_PATTERNS:
            if pat.match(stripped):
                return "\n".join(lines[:i]).rstrip()
    return body


def count_chars(text):
    """공백 포함 글자 수."""
    return len(text or "")


def summarize_phase_d(phase_d_text):
    """심의 결과 요약 — 통과/경고/불가 키워드로 단순 판정."""
    if not phase_d_text:
        return "검수결과 없음"
    t = phase_d_text
    # 간단 요약: 첫 500자 + 통과 여부 추측
    summary = t.strip()
    if len(summary) > 500:
        summary = summary[:500] + " …"
    return summary


def parse(text, product=None, keyword=None):
    """전체 파싱 — GUI/시트에 바로 쓸 수 있는 dict 반환.

    body 우선순위: Phase E(서식 적용 완료본) > Phase C(순수 원고).
    Phase E가 있으면 블로그 업로드용 최종본으로 간주하여 body 전체를 그대로 사용.
    제목은 Phase C / Phase E 어느 쪽에서든 '제목:' 또는 '제목 :' 라인에서 추출.
    product: 자사 제품명. 성분 나열 라인 자동 강조(볼드+노란 형광펜)에 사용.
    keyword: 메인 키워드. 하늘색 형광펜 지시에 타겟 단어가 빠졌을 때 자동 주입.
    """
    phases = split_phases(text)
    phase_c = phases.get("C", "")
    phase_e = phases.get("E", "")

    if phase_e.strip():
        # Phase E는 ★블로거 요청사항★부터 시작 — 내부의 "제목 :" 라인을 추출하되 본문에서 제거하지 않음
        title = _extract_title_line(phase_e)
        body = phase_e.strip()
        # LLM 자체 점검(E-3/E-4) 블록이 Phase E 말미에 섞여 나온 경우 먼저 잘라냄.
        body = _strip_phase_e_checklist(body)
        # 레거시 em-dash 타겟(`— "단어"`) → 표준 단일따옴표 형식으로 정규화 (v2.1~)
        body = _em_dash_to_quote(body)
        # 쪼개기는 주석 주입 전에 — 라인 경계가 먼저 확정돼야 타겟 주석이 올바른 줄에 붙음
        body = _split_sentences_after_period(body)
        body = _enforce_product_ingredient_format(body, product)
        # _merge_same_target_annotations 는 docx_formatter._build_document 에서 한 번만 실행 (v2.1~)
        body = _inject_keyword_target(body, keyword)
        # Phase C 원고 기준 글자 수 (심의/시트 판정용 — ★ 블록·ㄴ 지시 제외)
        _, c_body = extract_title_body(phase_c)
        char_count = count_chars(c_body) if c_body else count_chars(_strip_format_markers(body))
    else:
        title, body = extract_title_body(phase_c)
        body = _strip_phase_e_checklist(body)
        body = _em_dash_to_quote(body)
        body = _split_sentences_after_period(body)
        body = _enforce_product_ingredient_format(body, product)
        # _merge_same_target_annotations 는 docx_formatter._build_document 에서 한 번만 실행 (v2.1~)
        body = _inject_keyword_target(body, keyword)
        char_count = count_chars(body)

    return {
        "phases": phases,
        "title": title,
        "body": body,
        "char_count": char_count,
        "style": _extract_style(phases.get("B", "")),
        "blocks_summary": _extract_blocks_arrow(phases.get("B", "")),
        "review": summarize_phase_d(phases.get("D", "")),
        "raw": text,
    }


def _extract_title_line(phase_e_text):
    """Phase E 안에서 '제목 : ...' 라인을 찾아 제목만 반환 (원문은 그대로 유지)."""
    m = re.search(r"^\s*제목\s*[:：]\s*(.+?)\s*$", phase_e_text, re.MULTILINE)
    return m.group(1).strip() if m else ""


def _strip_format_markers(body):
    """글자 수 계산용 — ★ 블록, 구분선, ㄴ 편집 지시 라인을 제거한 순수 본문."""
    lines = []
    for line in body.splitlines():
        s = line.strip()
        if not s:
            lines.append(line)
            continue
        if s.startswith("★") or s.startswith("ㄴ"):
            continue
        if set(s) <= set("─-=_"):
            continue
        if s.startswith("제목") and (":" in s or "：" in s):
            continue
        lines.append(line)
    return "\n".join(lines)


def _extract_style(phase_b_text):
    """B-1 글 스타일 추출 (체험기형 / 체험기+비교형 / 전문 칼럼형 / 최대 신뢰형)."""
    if not phase_b_text:
        return ""
    m = re.search(r"(체험기\s*\+\s*비교형|체험기형|전문\s*칼럼형|최대\s*신뢰형)", phase_b_text)
    return m.group(1) if m else ""


def _extract_blocks_arrow(phase_b_text):
    """블록 화살표 요약 추출 (예: '블록1 → 블록5 → 블록22 …')."""
    if not phase_b_text:
        return ""
    # '→' 또는 '->' 포함한 줄을 찾음
    for line in phase_b_text.splitlines():
        if "→" in line or "->" in line:
            s = line.strip()
            if len(s) > 5:
                return s[:500]
    return ""
