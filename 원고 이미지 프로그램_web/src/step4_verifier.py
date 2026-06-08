"""
STEP 4 검증기 (v1.4)
- output/slot_metadata.json 이 STEP 4 가이드 v1.4의 검증 체크리스트를 만족하는지 점검.
- 필수 검사 15개 → PASS/FAIL 판단
- 참고 통계 3개 (16~18) → 출력만

CLI:
  python src/step4_verifier.py [slot_metadata] [meta] [product_csv] [herb_csv]

기본 경로:
  slot_metadata = output/slot_metadata.json
  meta          = slot_metadata의 manuscript 필드로부터 자동 결정
  product_csv   = data/product_list.csv
  herb_csv      = data/herb_keyword_map.csv
"""
import csv
import io
import json
import re
import sys
from pathlib import Path

# Windows 콘솔 한글 출력 안전
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


# ---------- 통제 어휘 ----------

CATEGORIES = {
    "정보성", "커뮤니티", "논문", "피부이미지", "타사제품", "항산화실험",
    "병원_피부", "병원_위장", "약", "위건강제품", "제품컷", "후기",
    "병원_산부인과", "혈당측정", "피지오틴", "일상", "병원_탈모", "병원_정형외과",
    "신체증상", "혈압측정", "짤", "병원", "동물", "음식", "운동", "건물",
    "선물", "전화", "실내", "인물", "야외",
}

POSITION_HINTS = {"opening", "middle", "closing", "any"}
SLOT_KEYS = {"slot", "scene", "category", "position_hint", "mood", "tags"}
MS_META_KEYS = {"product", "product_herb_keyword", "product_category", "cover_image"}

# 가이드 명시 통제 어휘 (CSV 값과 합쳐서 검사 8에 사용)
DOC_PRODUCT_CATEGORIES = {"건기식", "일반"}

# v1.4: product_category → cover_image 룰
COVER_IMAGE_RULE = {
    "건기식": "0_건기식",
    "일반": "0_일반",
}

RE_ABBR_FROM_FILENAME = re.compile(r"manuscript_marked_([A-Za-z0-9]+)\.md$")


# ---------- CSV 로딩 (헤더 호환) ----------

# 허브 CSV 헤더 후보 (사용자 시트 export 변형 흡수)
HERB_PRODUCT_KEYS = ("정식제품명", "제품명")
HERB_KEYWORD_KEYS = ("허브키워드",)
HERB_CATEGORY_KEYS = ("product_category", "제품 카테고리", "제품카테고리", "카테고리")


def parse_args(argv):
    sm = Path(argv[1]) if len(argv) > 1 else Path("output/slot_metadata.json")
    meta = Path(argv[2]) if len(argv) > 2 else None
    product_csv = Path(argv[3]) if len(argv) > 3 else Path("data/product_list.csv")
    herb_csv = Path(argv[4]) if len(argv) > 4 else Path("data/herb_keyword_map.csv")
    return sm, meta, product_csv, herb_csv


def load_meta_path(slot_metadata: dict, override) -> Path:
    if override is not None:
        return override
    ms = slot_metadata.get("manuscript", "")
    stem = Path(ms).stem
    return Path("output") / (stem + ".meta.json")


def _open_csv(path: Path):
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return path.read_text(encoding=enc).splitlines()
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"CSV 인코딩 판별 실패: {path}")


def _pick(row: dict, keys):
    for k in keys:
        v = row.get(k)
        if v is not None and str(v).strip() != "":
            return str(v).strip()
    return ""


def load_product_index(csv_path: Path):
    names, abbr_to_name = set(), {}
    if not csv_path.exists():
        return names, abbr_to_name
    reader = csv.DictReader(_open_csv(csv_path))
    for row in reader:
        n = (row.get("제품명") or "").strip()
        a = (row.get("약어") or "").strip()
        if n:
            names.add(n)
        if n and a:
            abbr_to_name[a.lower()] = n
    return names, abbr_to_name


def load_herb_map(csv_path: Path):
    """
    반환:
      herbs: 허브키워드 set
      herb_to_product: 허브키워드 → 정식제품명 dict
      herb_to_category: 허브키워드 → product_category dict
      csv_categories: CSV의 product_category 컬럼에 등장한 distinct 값 set
    """
    herbs, herb_to_product, herb_to_category = set(), {}, {}
    csv_categories = set()
    if not csv_path.exists():
        return herbs, herb_to_product, herb_to_category, csv_categories
    reader = csv.DictReader(_open_csv(csv_path))
    for row in reader:
        product = _pick(row, HERB_PRODUCT_KEYS)
        herb = _pick(row, HERB_KEYWORD_KEYS)
        cat = _pick(row, HERB_CATEGORY_KEYS)
        if herb:
            herbs.add(herb)
            if product:
                herb_to_product[herb] = product
            if cat:
                herb_to_category[herb] = cat
                csv_categories.add(cat)
    return herbs, herb_to_product, herb_to_category, csv_categories


# ---------- 필수 검사 (14) ----------

def check_array_length(slots, slot_count):
    if len(slots) == slot_count:
        return True, f"slot_metadata 길이 {len(slots)} = slot_count {slot_count}"
    return False, f"slot_metadata 길이 {len(slots)} ≠ slot_count {slot_count}"


def check_slot_keys(slots):
    bad = []
    for s in slots:
        missing = SLOT_KEYS - set(s.keys())
        extra = set(s.keys()) - SLOT_KEYS
        if missing or extra:
            bad.append(f"slot={s.get('slot','?')} 누락={sorted(missing)} 잉여={sorted(extra)}")
    if not bad:
        return True, "모든 슬롯에 6개 키 정확히 존재"
    return False, "; ".join(bad)


def check_manuscript_metadata(ms_meta):
    if not isinstance(ms_meta, dict):
        return False, "manuscript_metadata가 객체 아님"
    missing = MS_META_KEYS - set(ms_meta.keys())
    if missing:
        return False, f"누락 키 {sorted(missing)}"
    return True, (
        f"product={ms_meta['product']!r}, "
        f"product_herb_keyword={ms_meta['product_herb_keyword']!r}, "
        f"product_category={ms_meta['product_category']!r}, "
        f"cover_image={ms_meta['cover_image']!r}"
    )


def check_categories(slots):
    bad = [(s.get("slot","?"), s.get("category")) for s in slots
           if s.get("category") not in CATEGORIES]
    if not bad:
        return True, f"모든 category 통제 어휘({len(CATEGORIES)}개) 안에 있음"
    return False, "; ".join(f"slot={sl} category={c!r}" for sl, c in bad)


def check_position_hints(slots):
    bad = [(s.get("slot","?"), s.get("position_hint")) for s in slots
           if s.get("position_hint") not in POSITION_HINTS]
    if not bad:
        return True, "모든 position_hint 통제 어휘 안"
    return False, "; ".join(f"slot={sl} position_hint={p!r}" for sl, p in bad)


def check_position_hint_consistency(slots, slot_count):
    bad = []
    for s in slots:
        slot_no = int(s.get("slot", "0"))
        ph = s.get("position_hint")
        if slot_no == 1:
            expected = "opening"
        elif slot_no == slot_count:
            expected = "closing"
        else:
            expected = "middle"
        if ph != expected and ph != "any":
            bad.append(f"slot={s.get('slot')} 기대={expected} 실제={ph}")
    if not bad:
        return True, "슬롯 번호 ↔ position_hint 일관됨"
    return False, "; ".join(bad)


def check_tags(slots):
    bad = []
    for s in slots:
        tags = s.get("tags")
        if not isinstance(tags, list) or len(tags) < 3:
            bad.append(f"slot={s.get('slot','?')} tags={tags!r}")
    if not bad:
        return True, "모든 tags 3개 이상"
    return False, "; ".join(bad)


def check_product_category(ms_meta, allowed):
    """
    가이드 통제 어휘 {건기식, 일반}와 CSV에서 발견된 값(예: '일반식품')의 합집합 안에 있는지.
    CSV 값이 가이드와 다른 표기를 쓰면 운영 현실로 인정하되, 검사 14에서 행 단위 매핑 무결성을 별도 점검.
    """
    pc = ms_meta.get("product_category") if isinstance(ms_meta, dict) else None
    if pc in allowed:
        return True, f"product_category={pc!r} (허용 {sorted(allowed)})"
    return False, f"product_category={pc!r} (허용 {sorted(allowed)})"


def check_slot_sequence(slots, slot_count):
    expected = [f"{n:03d}" for n in range(1, slot_count + 1)]
    actual = [s.get("slot") for s in slots]
    if actual == expected:
        return True, f"001 ~ {slot_count:03d} 순서대로 누락 없음"
    return False, f"기대 {expected} ≠ 실제 {actual}"


def check_herb_keyword_in_csv(ms_meta, herbs):
    if not isinstance(ms_meta, dict):
        return False, "manuscript_metadata 없음"
    h = (ms_meta.get("product_herb_keyword") or "").strip()
    if not h:
        return False, "product_herb_keyword 비어 있음"
    if h in herbs:
        return True, f"product_herb_keyword={h!r} → herb_keyword_map.csv 등록됨"
    return False, f"product_herb_keyword={h!r} → herb_keyword_map.csv 미등록 (사용자 검수 필요)"


def check_product_in_csv(ms_meta, names):
    if not isinstance(ms_meta, dict):
        return False, "manuscript_metadata 없음"
    p = (ms_meta.get("product") or "").strip()
    if not p:
        return False, "product 비어 있음"
    if p in names:
        return True, f"product={p!r} → product_list.csv 제품명 일치"
    return False, f"product={p!r} → product_list.csv 미등록"


def check_herb_product_mapping(ms_meta, herb_to_product):
    if not isinstance(ms_meta, dict):
        return False, "manuscript_metadata 없음"
    p = (ms_meta.get("product") or "").strip()
    h = (ms_meta.get("product_herb_keyword") or "").strip()
    if not p or not h:
        return False, "product 또는 product_herb_keyword 비어 있음"
    expected = herb_to_product.get(h)
    if expected is None:
        return False, f"허브키워드 {h!r}가 매핑 테이블에 없음"
    if expected == p:
        return True, f"매핑 무결성 OK ({h!r} → {p!r})"
    return False, f"매핑 불일치: 허브키워드 {h!r}는 {expected!r}로 매핑되는데 product는 {p!r}"


def check_filename_abbr_cross(ms_meta, manuscript, abbr_to_name):
    if not isinstance(ms_meta, dict):
        return False, "manuscript_metadata 없음"
    if not manuscript:
        return True, "manuscript 정보 없음 — 교차 검증 건너뜀"

    m = RE_ABBR_FROM_FILENAME.search(manuscript)
    if not m:
        return True, f"파일명 '{manuscript}'에서 약어 패턴 없음 — 교차 검증 건너뜀"

    raw = m.group(1).lower()
    abbr = re.sub(r"\d+$", "", raw)

    if abbr not in abbr_to_name:
        return True, f"파일명 약어 {raw!r} → product_list.csv에 매핑 없음 — 교차 검증 건너뜀"

    expected = abbr_to_name[abbr]
    p = (ms_meta.get("product") or "").strip()
    if expected == p:
        return True, f"파일명 약어 {raw!r} → {expected!r} = product"
    return False, f"파일명 약어 {raw!r} → {expected!r}이지만 product={p!r}"


def check_cover_image_rule(ms_meta):
    """
    v1.4 신규: cover_image가 product_category 룰과 일치.
    건기식 → 0_건기식, 일반 → 0_일반
    """
    if not isinstance(ms_meta, dict):
        return False, "manuscript_metadata 없음"
    pc = (ms_meta.get("product_category") or "").strip()
    ci = (ms_meta.get("cover_image") or "").strip()
    expected = COVER_IMAGE_RULE.get(pc)
    if expected is None:
        return False, f"product_category={pc!r}에 대한 cover_image 룰 없음 (허용: {sorted(COVER_IMAGE_RULE)})"
    if ci == expected:
        return True, f"룰 일치 ({pc!r} → {ci!r})"
    return False, f"룰 불일치: 기대 {expected!r} ≠ 실제 {ci!r}"


def check_product_category_csv_lookup(ms_meta, herb_to_category):
    """
    v1.3 신규: product_category가 herb_keyword_map.csv의 매칭 행 값과 일치하는지.
    LLM이 추정하지 않고 CSV에서 그대로 가져왔는지 확인.
    """
    if not isinstance(ms_meta, dict):
        return False, "manuscript_metadata 없음"
    h = (ms_meta.get("product_herb_keyword") or "").strip()
    pc = (ms_meta.get("product_category") or "").strip()
    if not h:
        return False, "product_herb_keyword 비어 있음"
    expected = herb_to_category.get(h)
    if expected is None:
        return False, f"허브키워드 {h!r}의 product_category가 CSV에 없음"
    if expected == pc:
        return True, f"CSV 조회값 일치 ({h!r} 행 → {pc!r})"
    return False, f"CSV 조회값 불일치: 기대 {expected!r} ≠ 실제 {pc!r}"


# ---------- 참고 통계 ----------

def stats_scene_lengths(slots):
    print("  슬롯 | scene 길이 | scene 미리보기")
    print("  -----|-----------|----------------------------------------")
    for s in slots:
        sc = s.get("scene", "")
        print(f"  {s.get('slot','?')}  | {len(sc):>9} | {sc[:40]}")


def stats_tag_counts(slots):
    print("  슬롯 | tags 개수 | tags")
    print("  -----|----------|--------------------------------------")
    for s in slots:
        tags = s.get("tags", [])
        print(f"  {s.get('slot','?')}  | {len(tags):>8} | {tags}")


def stats_category_dist(slots):
    from collections import Counter
    c = Counter(s.get("category", "?") for s in slots)
    for cat, n in c.most_common():
        print(f"  {cat}: {n}회")


# ---------- 메인 ----------

def main():
    sm_path, meta_override, product_csv, herb_csv = parse_args(sys.argv)

    if not sm_path.exists():
        print(f"[ERROR] slot_metadata 파일 없음: {sm_path}")
        return 2

    sm = json.loads(sm_path.read_text(encoding="utf-8"))
    meta_path = load_meta_path(sm, meta_override)
    if not meta_path.exists():
        print(f"[ERROR] meta 파일 없음: {meta_path}")
        return 2

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    slot_count = int(meta["total_slots"])

    names, abbr_to_name = load_product_index(product_csv)
    herbs, herb_to_product, herb_to_category, csv_categories = load_herb_map(herb_csv)
    allowed_pc = DOC_PRODUCT_CATEGORIES | csv_categories

    slots = sm.get("slot_metadata", [])
    ms_meta = sm.get("manuscript_metadata", {})
    manuscript = sm.get("manuscript", "")

    print(f"# STEP 4 검증 보고 (v1.4)")
    print(f"- slot_metadata: {sm_path}")
    print(f"- meta:          {meta_path}")
    print(f"- product CSV:   {product_csv} ({'있음' if product_csv.exists() else '없음'}, 제품 {len(names)}개)")
    print(f"- herb CSV:      {herb_csv} ({'있음' if herb_csv.exists() else '없음'}, 허브키워드 {len(herbs)}개, 카테고리 값 {sorted(csv_categories)})")
    print(f"- 원고:          {manuscript}")
    print(f"- slot_count = {slot_count} (출처: meta.total_slots)")
    print()

    checks = [
        ("1) 배열 길이 = slot_count",            *check_array_length(slots, slot_count)),
        ("2) 슬롯 6개 키 모두 존재",              *check_slot_keys(slots)),
        ("3) manuscript_metadata 4개 키",        *check_manuscript_metadata(ms_meta)),
        ("4) category 통제 어휘 안",             *check_categories(slots)),
        ("5) position_hint 통제 어휘 안",         *check_position_hints(slots)),
        ("6) position_hint ↔ slot 번호 일관",    *check_position_hint_consistency(slots, slot_count)),
        ("7) tags 3개 이상",                      *check_tags(slots)),
        ("8) product_category 허용 어휘 안",      *check_product_category(ms_meta, allowed_pc)),
        ("9) slot 시퀀스 누락 없음",               *check_slot_sequence(slots, slot_count)),
        ("10) product_herb_keyword ∈ herb CSV",  *check_herb_keyword_in_csv(ms_meta, herbs)),
        ("11) product ∈ product CSV",            *check_product_in_csv(ms_meta, names)),
        ("12) 허브 → product 매핑 무결성",        *check_herb_product_mapping(ms_meta, herb_to_product)),
        ("13) 파일명 약어 ↔ product 교차 검증",   *check_filename_abbr_cross(ms_meta, manuscript, abbr_to_name)),
        ("14) product_category CSV 조회 일치",    *check_product_category_csv_lookup(ms_meta, herb_to_category)),
        ("15) cover_image 룰 일치",               *check_cover_image_rule(ms_meta)),
    ]

    print("## 필수 검사 (15)")
    all_pass = True
    for label, ok, detail in checks:
        tag = "[PASS]" if ok else "[FAIL]"
        print(f"  {tag} {label} — {detail}")
        if not ok:
            all_pass = False
    print()

    print("## 참고 통계 16 (슬롯별 scene 길이)")
    stats_scene_lengths(slots)
    print()
    print("## 참고 통계 17 (슬롯별 tags 개수)")
    stats_tag_counts(slots)
    print()
    print("## 참고 통계 18 (category 분포)")
    stats_category_dist(slots)
    print()

    print(f"## 종합: {'전부 통과' if all_pass else '실패 있음'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
