"""
STEP 2: 글자수 카운터 + 슬롯 결정 (v2)
- output/body_text.txt 의 본문 글자수를 utils.count_body_chars 로 측정
- 분량 표대로 본문 슬롯 수 매핑 (1,800 미만도 13장 + 경고)
- output/slot_decision.json 출력
"""
import io
import json
import sys
from pathlib import Path

from utils import count_body_chars

# Windows 콘솔 한글 출력 안전
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


# ---------- 슬롯 매핑 ----------

def decide_slot(char_count: int) -> tuple[int, str | None]:
    """
    본문 글자수 -> (slot_count, warning).
    - 1,800 미만: 13장 + 경고
    - 1,800 ~ 1,999: 13장
    - 2,000 ~ 2,199: 14장
    - 2,200 ~ 2,499: 15장
    - 2,500 이상: 17장 (상한, 16장 구간 없음)
    """
    if char_count < 1800:
        warning = (f"본문 글자수 {char_count:,}자. 1,800자 미만이라 "
                   f"13장 분할이 빡빡할 수 있음. 결과 확인 필요.")
        return 13, warning
    if char_count < 2000:
        return 13, None
    if char_count < 2200:
        return 14, None
    if char_count < 2500:
        return 15, None
    return 17, None


# ---------- 단위 테스트 (경계값) ----------

def run_unit_tests() -> bool:
    """경계값 6개를 검증하고 결과를 한 줄씩 출력. 모두 통과하면 True."""
    cases = [
        (1799, 13, True),   # 경고 있음
        (1800, 13, False),
        (1999, 13, False),
        (2000, 14, False),
        (2499, 15, False),
        (2500, 17, False),
    ]
    print("## 단위 테스트 (경계값)")
    all_ok = True
    for n, expected_slot, expect_warning in cases:
        slot, warn = decide_slot(n)
        ok = (slot == expected_slot) and (bool(warn) == expect_warning)
        marker = "" if ok else "  [FAIL]"
        if expect_warning:
            print(f"  {n} -> {slot} (warning){marker}")
        else:
            print(f"  {n} -> {slot}{marker}")
        if not ok:
            all_ok = False
    return all_ok


# ---------- 메인 ----------

def process_sample(body_path: Path, out_json: Path) -> dict:
    body_text = body_path.read_text(encoding="utf-8")
    char_count = count_body_chars(body_text)
    slot_count, warning = decide_slot(char_count)
    result = {
        "char_count": char_count,
        "slot_count": slot_count,
        "warning": warning,
    }
    out_json.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return result


def main():
    project_root = Path(".")
    samples = [
        ("샘플1 (260414 중성지방낮추는음식)",
         "samples/이효진_260414중성지방낮추는음식(1)_중성지방 낮추는 음식_정보형C_bc.docx"),
        ("샘플2 (260427 중성지방관리)",
         "samples/이효진_260427중성지방관리_생활형C_bc .docx"),
    ]

    # 단위 테스트 먼저
    tests_ok = run_unit_tests()
    print()

    # 샘플별로 STEP 1을 다시 돌려 body_text.txt 만들고 STEP 2 처리
    # (STEP 1을 import해서 사용 — 자체 추출 로직 신설 금지)
    from step1_body_extractor import extract_lines, classify

    print("## 두 샘플 결과")
    last_written = None
    results = []
    for label, docx_rel in samples:
        # STEP 1 산출물 재생성 (각 샘플 별로)
        docx_path = project_root / docx_rel
        lines = extract_lines(docx_path)
        classified = classify(lines)
        body_lines = [raw for raw, (kept, _) in zip(lines, classified) if kept]
        body_path = project_root / "output/body_text.txt"
        body_path.parent.mkdir(parents=True, exist_ok=True)
        body_path.write_text("\n".join(body_lines) + "\n", encoding="utf-8")

        out_json = project_root / "output/slot_decision.json"
        result = process_sample(body_path, out_json)
        last_written = label
        results.append((label, result))

        warn = result["warning"] or "없음"
        print(f"- {label}")
        print(f"    char_count: {result['char_count']}")
        print(f"    slot_count: {result['slot_count']}")
        print(f"    warning   : {warn}")

    print()
    print(f"## 산출물")
    print(f"- output/slot_decision.json (마지막 실행 = {last_written}로 덮임)")
    print(f"- 단위 테스트: {'전부 통과' if tests_ok else '실패 있음'}")
    return results


if __name__ == "__main__":
    main()
