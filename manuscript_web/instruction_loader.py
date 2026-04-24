"""지침 모음(7개 MD) 로더 — 전체 로드하여 시스템 프롬프트에 그대로 사용.

프롬프트 캐싱을 적용하므로 섹션 추출 없이 전체 로드해도 비용 부담 없음.
LLM이 입력 제품명을 보고 모듈4/6에서 해당 섹션을 찾아 활용.
"""
import os
from config import DEFAULT_INSTRUCTIONS_DIR, MODULE_FILES, load_instructions_dir


def _read(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"지침 파일 없음: {path}")
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def load_all_modules(instructions_dir=None):
    """7개 모듈을 dict로 반환.

    keys: orchestrator, blocks, persona, product_db, regulation, papers, formatting
    """
    base = instructions_dir or load_instructions_dir() or DEFAULT_INSTRUCTIONS_DIR
    modules = {}
    for key, filename in MODULE_FILES.items():
        path = os.path.join(base, filename)
        modules[key] = _read(path)
    return modules


def build_system_instruction(modules=None):
    """7개 모듈을 합쳐 시스템 프롬프트 문자열 생성 (캐싱용 고정 블록)."""
    m = modules or load_all_modules()
    parts = [
        "너는 네이티브 광고 블로그 글 작성 전문가다. 아래 7개 참조 문서를 모두 숙지하고,",
        "사용자가 입력한 키워드·제품명·제품 링크를 바탕으로 Phase A → B → B-2 → C → D를 한 번에 수행한다.",
        "",
        "="*60,
        "[모듈1] 오케스트레이터 — 실행 파이프라인",
        "="*60,
        m["orchestrator"],
        "",
        "="*60,
        "[참조 문서 1] 블록 구조 설명서 (모듈2)",
        "="*60,
        m["blocks"],
        "",
        "="*60,
        "[참조 문서 2] 페르소나 분석 (모듈3)",
        "="*60,
        m["persona"],
        "",
        "="*60,
        "[참조 문서 3] 제품별 기본정보 (모듈4)",
        "="*60,
        m["product_db"],
        "",
        "="*60,
        "[참조 문서 4] 심의 규칙 — 과대광고 방지 가이드 (모듈5)",
        "="*60,
        m["regulation"],
        "",
        "="*60,
        "[참조 문서 5] 제품별 성분 근거 논문 (모듈6)",
        "="*60,
        m["papers"],
        "",
        "="*60,
        "[참조 문서 6] 서식 적용 지침 (모듈7)",
        "="*60,
        m["formatting"],
    ]
    return "\n".join(parts)


if __name__ == "__main__":
    mods = load_all_modules()
    for k, v in mods.items():
        print(f"{k}: {len(v):,}자")
    total = build_system_instruction(mods)
    print(f"\n시스템 프롬프트 총 길이: {len(total):,}자")
