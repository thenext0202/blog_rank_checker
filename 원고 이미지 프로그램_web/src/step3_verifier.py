"""
STEP 3 검증기 (v1.3)
- output/manuscript_marked.md 가 STEP 3 지시문서의 검증 체크리스트를 만족하는지 점검.
- v1.3 변경점: 권유 블록 식별은 LLM(분할 작업) 책임으로 이관.
  검증기는 LLM이 출력한 메타 파일(.meta.json)에서 권유 블록 줄 범위만 읽음.
- 필수 검사 6개 → PASS/FAIL 판단
- 참고 통계 4개 → 출력만 (판단 안 함)

CLI:
  python src/step3_verifier.py [marked] [body_text] [slot_decision] [meta]
  python src/step3_verifier.py --slot-count N [marked] [body_text] [meta]

기본 경로:
  marked        = output/manuscript_marked.md
  body_text     = output/body_text.txt
  slot_decision = output/slot_decision.json
  meta          = <marked와 같은 폴더>/<marked stem>.meta.json
                  예: output/manuscript_marked_hc.md
                   →  output/manuscript_marked_hc.meta.json
"""
import io
import json
import re
import sys
from pathlib import Path

from utils import count_body_chars

# Windows 콘솔 한글 출력 안전
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


# 마커 형식: 3자리 숫자만 단독 줄
RE_MARKER = re.compile(r"^\d{3}$")


# ---------- 입력 파싱 ----------

def parse_args(argv):
    slot_count_override = None
    positional = []
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--slot-count":
            slot_count_override = int(argv[i + 1])
            i += 2
        else:
            positional.append(a)
            i += 1
    marked = Path(positional[0]) if len(positional) > 0 else Path("output/manuscript_marked.md")
    body = Path(positional[1]) if len(positional) > 1 else Path("output/body_text.txt")
    sd = Path(positional[2]) if len(positional) > 2 else Path("output/slot_decision.json")
    meta = Path(positional[3]) if len(positional) > 3 else (marked.parent / (marked.stem + ".meta.json"))
    return marked, body, sd, meta, slot_count_override


def load_slot_count(sd_path: Path, override) -> int:
    if override is not None:
        return override
    data = json.loads(sd_path.read_text(encoding="utf-8"))
    return int(data["slot_count"])


def load_promo_blocks(meta_path: Path) -> list[tuple[int, int]]:
    """
    LLM이 분할 작업과 함께 출력한 메타 파일에서 권유 블록 줄 범위를 읽음.
    메타 파일의 줄 번호는 1-based, 내부에선 0-based로 변환해서 반환.
    """
    if not meta_path.exists():
        raise FileNotFoundError(
            f"메타 파일이 없음: {meta_path}\n"
            "STEP 3 v1.3부터 LLM이 분할 결과물과 함께 메타 파일을 출력해야 함. "
            "권유 블록이 없는 원고면 recommendation_blocks를 빈 배열([])로 만들 것."
        )
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    blocks = data.get("recommendation_blocks", [])
    result = []
    for b in blocks:
        s = int(b["start_line"]) - 1
        e = int(b["end_line"]) - 1
        result.append((s, e))
    return result


# ---------- 마커 추출 ----------

def extract_markers(lines):
    return [(i, ln.strip()) for i, ln in enumerate(lines) if RE_MARKER.match(ln.strip())]


# ---------- 필수 검사 ----------

def check_marker_count(markers, slot_count):
    expected = slot_count + 1
    actual = len(markers)
    if actual == expected:
        return True, f"마커 {actual}개 = slot_count({slot_count}) + 1"
    return False, f"마커 {actual}개 (기대 {expected}개)"


def check_marker_sequence(markers, slot_count):
    expected = [f"{n:03d}" for n in range(0, slot_count + 1)]
    actual = [v for _, v in markers]
    if actual == expected:
        return True, f"000 ~ {slot_count:03d} 순서대로 누락 없이 등장"
    return False, f"기대 시퀀스 {expected} ≠ 실제 {actual}"


def check_marker_isolation(lines, markers):
    n = len(lines)
    failures = []
    for idx, val in markers:
        if lines[idx].strip() != val:
            failures.append(f"마커 {val}: 줄에 다른 텍스트 섞임 ({lines[idx]!r})")
            continue
        if idx > 0 and lines[idx - 1].strip() != "":
            failures.append(f"마커 {val}: 위 줄이 빈 줄 아님 ({lines[idx-1]!r})")
        if idx < n - 1 and lines[idx + 1].strip() != "":
            failures.append(f"마커 {val}: 아래 줄이 빈 줄 아님 ({lines[idx+1]!r})")
    if not failures:
        return True, "모든 마커 단독 줄 + 앞뒤 빈 줄/파일 경계"
    return False, "; ".join(failures)


def check_char_count_preserved(lines, body_text):
    body_only = "\n".join(ln for ln in lines if not RE_MARKER.match(ln.strip()))
    n_marked = count_body_chars(body_only)
    n_body = count_body_chars(body_text)
    if n_marked == n_body:
        return True, f"본문 글자수 일치: {n_body}자"
    return False, f"본문 {n_body}자 ≠ 분할본 {n_marked}자 (차이 {n_marked - n_body:+d})"


def check_bold_count_preserved(marked_text, body_text):
    n_marked = marked_text.count("**")
    n_body = body_text.count("**")
    if n_marked == n_body:
        return True, f"강조 마크업(**) 개수 일치: {n_body}"
    return False, f"본문 ** {n_body}개 ≠ 분할본 ** {n_marked}개 (차이 {n_marked - n_body:+d})"


def check_no_markers_in_promo(markers, promo_blocks, total_lines):
    """
    권유 블록 영역(manuscript 기준 0-based 줄 범위)에 마커가 박혀 있지 않은지.
    promo_blocks는 이미 manuscript 기준 줄 범위라 별도 매핑 불필요.
    줄 범위 유효성도 같이 점검.
    """
    if not promo_blocks:
        return True, "권유 블록 0개 — 검사 대상 없음"
    marker_line_set = {idx for idx, _ in markers}
    failures = []
    for s, e in promo_blocks:
        if s < 0 or e >= total_lines or s > e:
            failures.append(
                f"권유 블록 줄 범위 오류: {s+1}~{e+1} "
                f"(manuscript 총 {total_lines}줄, 1-based 기준)"
            )
            continue
        for ml in marker_line_set:
            if s <= ml <= e:
                failures.append(
                    f"권유 블록 manuscript 줄 {s+1}~{e+1} 안에 마커 박혀 있음 (줄 {ml+1})"
                )
    if failures:
        return False, "; ".join(failures)
    return True, f"권유 블록 {len(promo_blocks)}개 모두 마커 없음"


# ---------- 참고 통계 ----------

def split_into_slots(lines, markers):
    slots = []
    n = len(lines)
    for k, (idx, val) in enumerate(markers):
        next_idx = markers[k + 1][0] if k + 1 < len(markers) else n
        slot_lines = lines[idx + 1:next_idx]
        while slot_lines and slot_lines[0].strip() == "":
            slot_lines.pop(0)
        while slot_lines and slot_lines[-1].strip() == "":
            slot_lines.pop()
        slots.append((val, slot_lines, idx, next_idx))
    return slots


def first_line_preview(slot_lines, n=40):
    for ln in slot_lines:
        s = ln.strip()
        if s == "":
            continue
        s = s.replace("**", "")
        return s[:n]
    return ""


def count_paragraphs(slot_lines):
    paragraphs = 0
    in_para = False
    for ln in slot_lines:
        if ln.strip() == "":
            in_para = False
        else:
            if not in_para:
                paragraphs += 1
                in_para = True
    return paragraphs


def promo_position_label(block_loc, markers):
    """권유 블록(manuscript 줄 범위, 0-based)이 어느 슬롯과 어느 슬롯 사이에 있는지."""
    bs, be = block_loc
    prev_marker = None
    next_marker = None
    for idx, val in markers:
        if idx < bs:
            prev_marker = val
        elif idx > be:
            next_marker = val
            break
    if prev_marker is None and next_marker is None:
        return "(마커 없음)"
    if prev_marker is None:
        return f"파일 시작 ~ 마커 {next_marker} 사이"
    if next_marker is None:
        return f"마커 {prev_marker} 이후 (마지막)"
    return f"마커 {prev_marker} ~ {next_marker} 사이"


# ---------- 메인 ----------

def main():
    marked_path, body_path, sd_path, meta_path, sc_override = parse_args(sys.argv)
    slot_count = load_slot_count(sd_path, sc_override)

    marked_text = marked_path.read_text(encoding="utf-8")
    body_text = body_path.read_text(encoding="utf-8")
    marked_lines = marked_text.splitlines()
    markers = extract_markers(marked_lines)

    # 권유 블록은 LLM이 만든 메타 파일에서 로드
    try:
        promo_blocks = load_promo_blocks(meta_path)
    except FileNotFoundError as ex:
        print(f"# STEP 3 검증 보고")
        print(f"- 분할본: {marked_path}")
        print(f"- 메타:   {meta_path}")
        print()
        print(f"[ERROR] {ex}")
        return 2

    print(f"# STEP 3 검증 보고")
    print(f"- 분할본: {marked_path}")
    print(f"- 원본:   {body_path}")
    print(f"- 메타:   {meta_path}")
    print(f"- slot_count = {slot_count} (출처: {'CLI' if sc_override is not None else sd_path})")
    print()

    checks_basic = [
        ("1) 마커 개수 = slot_count+1", *check_marker_count(markers, slot_count)),
        ("2) 마커 시퀀스 누락 없음",     *check_marker_sequence(markers, slot_count)),
        ("3) 마커 단독 줄 + 앞뒤 빈 줄", *check_marker_isolation(marked_lines, markers)),
        ("4) 본문 글자수 보존",          *check_char_count_preserved(marked_lines, body_text)),
        ("5) 강조 마크업 ** 개수 보존",  *check_bold_count_preserved(marked_text, body_text)),
        ("6) 권유 블록 안에 마커 없음",  *check_no_markers_in_promo(markers, promo_blocks, len(marked_lines))),
    ]

    print("## 필수 검사 (6)")
    all_pass = True
    for label, ok, detail in checks_basic:
        tag = "[PASS]" if ok else "[FAIL]"
        print(f"  {tag} {label} — {detail}")
        if not ok:
            all_pass = False
    print()

    # 참고 통계 7~9 (슬롯별)
    slots = split_into_slots(marked_lines, markers)
    print("## 참고 통계 7~9 (슬롯별 글자수 / 단락 수 / 첫 줄 미리보기)")
    print("  슬롯 | 글자수 | 단락 | 첫 줄 미리보기")
    print("  -----|--------|------|------------------------------------------")
    for val, slot_lines, _, _ in slots:
        chars = count_body_chars("\n".join(slot_lines))
        paras = count_paragraphs(slot_lines)
        preview = first_line_preview(slot_lines)
        print(f"  {val}  | {chars:>6} | {paras:>4} | {preview}")
    print()

    # 참고 통계 10 (권유 블록) — manuscript 기준 줄 번호로 표시
    print(f"## 참고 통계 10 (권유 블록) — LLM이 메타 파일에 명시")
    if not promo_blocks:
        print("  - 권유 블록 0개")
    else:
        print(f"  - 권유 블록 {len(promo_blocks)}개")
        for k, (s, e) in enumerate(promo_blocks, 1):
            block_text = "\n".join(marked_lines[s:e + 1])
            chars = count_body_chars(block_text)
            position = promo_position_label((s, e), markers)
            preview = ""
            for i in range(s, e + 1):
                txt = marked_lines[i].strip().replace("**", "")
                if txt:
                    preview = txt[:40]
                    break
            print(f"    [블록 {k}] manuscript 줄 {s+1}~{e+1}, "
                  f"{chars}자, 위치={position}, 첫 줄='{preview}'")
    print()

    print(f"## 종합: {'전부 통과' if all_pass else '실패 있음'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
