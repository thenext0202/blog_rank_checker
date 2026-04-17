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
        sections[key] = text[start:end].strip()
    return sections


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


def parse(text):
    """전체 파싱 — GUI/시트에 바로 쓸 수 있는 dict 반환.

    body 우선순위: Phase E(서식 적용 완료본) > Phase C(순수 원고).
    Phase E가 있으면 블로그 업로드용 최종본으로 간주하여 body 전체를 그대로 사용.
    제목은 Phase C / Phase E 어느 쪽에서든 '제목:' 또는 '제목 :' 라인에서 추출.
    """
    phases = split_phases(text)
    phase_c = phases.get("C", "")
    phase_e = phases.get("E", "")

    if phase_e.strip():
        # Phase E는 ★블로거 요청사항★부터 시작 — 내부의 "제목 :" 라인을 추출하되 본문에서 제거하지 않음
        title = _extract_title_line(phase_e)
        body = phase_e.strip()
        # Phase C 원고 기준 글자 수 (심의/시트 판정용 — ★ 블록·ㄴ 지시 제외)
        _, c_body = extract_title_body(phase_c)
        char_count = count_chars(c_body) if c_body else count_chars(_strip_format_markers(body))
    else:
        title, body = extract_title_body(phase_c)
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
