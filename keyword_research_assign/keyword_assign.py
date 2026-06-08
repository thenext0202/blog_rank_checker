#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
board_assign.py - 키워드 전광판 기반 원고 배정 프로그램

워크플로우:
1. 원고 작성 건수 탭에서 작가별 건수 확인
2. 오늘 최대 배정 건수 입력 (전체 작가 공통, 단 기존 건수가 적으면 그대로)
3. 사전 확정 작가-키워드 입력
4. 오늘 배정할 제품 선택
5. 키워드 전광판에서 우선순위 기반 배정
   (1차) 기존 전환금액 큰 것 + 순위 밖
   (2차) 기존 전환금액 큰 것 + 경과일 10일 이상
   (3차) 순위 밖
6. 원고 배정 탭에 결과 기록
"""

import os
import sys
import io
import json
import re
import base64
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from collections import defaultdict

import gspread
from google.oauth2.service_account import Credentials

# Windows cp949 인코딩 문제 해결
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
if sys.stdin.encoding != "utf-8":
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8")

# ━━━━━━━━━━━━━━━━━━━━ 설정 ━━━━━━━━━━━━━━━━━━━━
SPREADSHEET_ID = "1xJAogt0alaQ8A5OctxltPaF3kg_0PFSF5Z0ePxMw3tY"
CRED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "credentials.json")

TAB_BOARD = "키워드 전광판"
TAB_QUOTA = "원고 작성 건수"
TAB_ASSIGN = "원고 배정"
TAB_CONVERSION = "전환 키워드"


# ━━━━━━━━━━━━━━━━━━━━ 시트 연결 ━━━━━━━━━━━━━━━━━━━━
def connect_spreadsheet():
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds_b64 = os.environ.get("GOOGLE_CREDENTIALS_BASE64")
    if creds_b64:
        info = json.loads(base64.b64decode(creds_b64))
        creds = Credentials.from_service_account_info(info, scopes=scope)
    else:
        creds = Credentials.from_service_account_file(CRED_FILE, scopes=scope)
    gc = gspread.authorize(creds)
    return gc.open_by_key(SPREADSHEET_ID)


# ━━━━━━━━━━━━━━━━━━━━ 유틸리티 ━━━━━━━━━━━━━━━━━━━━
def cell(row, col_idx):
    """행 데이터에서 안전하게 값 가져오기"""
    return row[col_idx].strip() if len(row) > col_idx else ""


def parse_amount(s):
    """금액 문자열 → 숫자 (₩, 쉼표 제거)"""
    if not s:
        return 0
    try:
        return int(re.sub(r"[^\d]", "", str(s)))
    except ValueError:
        return 0


def parse_days(s):
    """경과일 문자열 → 숫자"""
    if not s:
        return 0
    try:
        return int(re.sub(r"[^\d]", "", str(s)))
    except ValueError:
        return 0


# ━━━━━━━━━━━━━━━━━━━━ 네이버 검색 (스마트블록/인기글) ━━━━━━━━━━━━━━━━━━━━
GENERIC_SECTIONS = {
    "브랜드 콘텐츠", "이미지", "뉴스", "동영상", "지식iN", "쇼핑",
    "지도", "장소", "사전", "웹사이트", "카페", "학술정보",
    "어학사전", "도서", "뮤직", "영화", "TV", "플레이스",
}

NAVER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def check_naver_keyword(keyword):
    """네이버 통합검색에서 스마트블록 여부 + 인기글 여부 확인

    스마트블록: subjectTitle에 검색 키워드가 포함된 블록
               (단, '인기글', 'FAQ', 일반 섹션 제외)
               예: "오메가3 효능", "오메가3 비타민D"
    인기글: subjectTitle에 '인기글'이 포함된 블록
            예: "'오메가3' 인기글", "건강·의학 인기글"

    Returns:
        (smart_block: str, popular: str)
        smart_block: "O" / "X" / "?"
        popular: "O" / "X" / "?"
    """
    smart_block = "?"
    popular = "?"
    brand = "?"

    try:
        q = urllib.parse.quote(keyword)
        url = f"https://search.naver.com/search.naver?where=nexearch&query={q}"
        req = urllib.request.Request(url)
        req.add_header("User-Agent", NAVER_UA)
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8")

        subject_titles = re.findall(r'"subjectTitle":"([^"]+)"', html)

        # 키워드 정규화 (공백 제거 후 비교용)
        kw_norm = keyword.replace(" ", "").lower()

        smart_blocks = []
        has_popular = False

        for t in subject_titles:
            # 일반 섹션 제외
            if t in GENERIC_SECTIONS:
                continue
            # 인기글 체크
            if "인기글" in t:
                has_popular = True
                continue
            # FAQ 제외
            if "FAQ" in t:
                continue
            # 키워드 포함된 블록 = 스마트블록
            t_norm = t.replace(" ", "").lower()
            if kw_norm in t_norm or any(
                part in t_norm for part in kw_norm.split() if len(part) >= 2
            ):
                smart_blocks.append(t)

        if smart_blocks:
            smart_block = ", ".join(smart_blocks)
        else:
            smart_block = "X"
        popular = "O" if has_popular else "X"
        brand = "O" if any("브랜드" in t for t in subject_titles) else "X"

    except Exception as e:
        print(f"    [네이버 검색 오류] {keyword}: {e}")

    return smart_block, popular, brand


def check_all_keywords(results):
    """배정 결과의 모든 키워드에 대해 스마트블록/인기글 체크"""
    import time

    total = len(results)
    print(f"\n    {total}개 키워드 네이버 검색 중...")

    for i, r in enumerate(results):
        keyword = r["keyword"]
        smart, pop, brand = check_naver_keyword(keyword)
        r["smart_block"] = smart
        r["popular"] = pop
        r["brand"] = brand

        status = f"스블:{smart or 'X':<20} 인기글:{pop} 브랜드:{brand}"
        print(f"    [{i + 1}/{total}] {keyword:<22} {status}")

        if i < total - 1:
            time.sleep(0.3)  # 요청 간 딜레이


# ━━━━━━━━━━━━━━━━━━━━ 작가별 제품 효율 분석 ━━━━━━━━━━━━━━━━━━━━
def get_writer_product_efficiency(spreadsheet):
    """전환 키워드 탭에서 작가별 제품 효율(총 전환금액, 건수) 분석

    Returns:
        writer_efficiency: {작가명: {제품명: {"amount": 총금액, "count": 건수}}}
        writer_best_products: {작가명: [제품1, 제품2, ...]}  # 금액 내림차순
    """
    ws = spreadsheet.worksheet(TAB_CONVERSION)
    rows = ws.get_all_values()

    if len(rows) < 3:
        return {}, {}

    # Row 0: 제품명 (5열마다), Row 1: 헤더, Row 2+: 데이터
    products_row = rows[0]
    products = []
    for i in range(0, len(products_row), 5):
        p = products_row[i].strip()
        if p:
            products.append((p, i))  # (제품명, 시작열)

    # 작가별 제품별 집계
    writer_efficiency = defaultdict(lambda: defaultdict(lambda: {"amount": 0, "count": 0}))

    for row in rows[2:]:
        for product, start_col in products:
            writer = cell(row, start_col + 2)    # 작가 열
            amount_str = cell(row, start_col + 3)  # 금액 열
            if not writer:
                continue
            amount = parse_amount(amount_str)
            writer_efficiency[writer][product]["amount"] += amount
            writer_efficiency[writer][product]["count"] += 1

    # 작가별 잘하는 제품 순서 (금액 내림차순)
    writer_best_products = {}
    for writer, products_dict in writer_efficiency.items():
        sorted_products = sorted(
            products_dict.items(),
            key=lambda x: x[1]["amount"],
            reverse=True,
        )
        writer_best_products[writer] = [p for p, _ in sorted_products]

    return dict(writer_efficiency), writer_best_products


# ━━━━━━━━━━━━━━━━━━━━ 1. 원고 작성 건수 읽기 ━━━━━━━━━━━━━━━━━━━━
def get_today_quotas(spreadsheet):
    """원고 작성 건수 탭에서 오늘 날짜에 해당하는 작가별 건수 가져오기"""
    ws = spreadsheet.worksheet(TAB_QUOTA)
    rows = ws.get_all_values()

    today = datetime.now()
    today_str = f"{today.month}/{today.day}"  # e.g. "3/17"

    writers = {}
    found_block = False

    for i, row in enumerate(rows):
        if row[0].strip() == "작가명" and today_str in row:
            col_idx = row.index(today_str)
            found_block = True
            for j in range(i + 1, len(rows)):
                r = rows[j]
                name = r[0].strip()
                if name in ("총합", "작가명", "") or not name:
                    break
                try:
                    quota = int(r[col_idx]) if len(r) > col_idx and r[col_idx] else 0
                except ValueError:
                    quota = 0
                writers[name] = quota

    if not found_block:
        print(f"\n[오류] 원고 작성 건수 탭에서 오늘 날짜({today_str})를 찾을 수 없습니다.")
        print("  헤더에 있는 날짜들:")
        for row in rows:
            if row[0].strip() == "작가명":
                print(f"  {row[1:10]}")
        sys.exit(1)

    return writers


# ━━━━━━━━━━━━━━━━━━━━ 2. 최대 배정 건수 적용 ━━━━━━━━━━━━━━━━━━━━
def apply_max_quota(writers, max_count):
    """최대 배정 건수 적용. 기존 건수가 max_count보다 적으면 그대로 유지."""
    result = {}
    for writer, quota in writers.items():
        if quota <= 0:
            continue
        result[writer] = min(quota, max_count)
    return result


# ━━━━━━━━━━━━━━━━━━━━ 3. 사전 확정 키워드 입력 ━━━━━━━━━━━━━━━━━━━━
def get_pre_assignments(active_writers):
    """사전 확정 작가-키워드 입력받기"""
    print(f"\n{'=' * 60}")
    print(f"  사전 확정할 작가-키워드가 있나요?")
    print(f"  형식: 작가명, 제품, 키워드")
    print(f"  예시: 남경아, 블러드싸이클, 고혈압140")
    print(f"  (한 줄에 하나씩, 빈 줄 입력하면 종료)")
    print(f"{'=' * 60}")

    pre_assignments = []
    writer_names = set(active_writers.keys())

    while True:
        line = input("  → ").strip()
        if not line:
            break

        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            print("    형식 오류. '작가명, 제품, 키워드' 형식으로 입력하세요.")
            continue

        writer, product, keyword = parts[0], parts[1], parts[2]

        if writer not in writer_names:
            print(f"    '{writer}'는 오늘 배정 작가가 아닙니다.")
            print(f"    작가 목록: {', '.join(sorted(writer_names))}")
            continue

        pre_assignments.append({
            "writer": writer,
            "product": product,
            "keyword": keyword,
        })
        print(f"    + {writer} ← {product} / {keyword}")

    if pre_assignments:
        print(f"\n  확정 키워드 {len(pre_assignments)}건 등록")
    else:
        print(f"\n  확정 키워드 없음")

    return pre_assignments


# ━━━━━━━━━━━━━━━━━━━━ 최근 배정 이력 (중복 방지) ━━━━━━━━━━━━━━━━━━━━
def get_recent_assignments(spreadsheet):
    """원고 배정 탭에서 최근 배정 키워드 조회

    Returns:
        recent_5d: set  - 최근 5일 이내 배정된 키워드 (공백제거 소문자)
        recent_4d: set  - 최근 4일 이내 배정된 키워드 (공백제거 소문자)
    """
    ws = spreadsheet.worksheet(TAB_ASSIGN)
    rows = ws.get_all_values()

    today = datetime.now().date()
    cutoff_5d = today - timedelta(days=5)
    cutoff_4d = today - timedelta(days=4)

    recent_5d = set()
    recent_4d = set()

    for row in rows[1:]:  # skip header
        if not row[0]:
            continue
        try:
            row_date = datetime.strptime(row[0].strip(), "%Y-%m-%d").date()
        except ValueError:
            continue

        keyword = row[3].strip() if len(row) > 3 else ""
        if not keyword:
            continue

        norm = keyword.replace(" ", "").lower()

        if row_date >= cutoff_5d:
            recent_5d.add(norm)
        if row_date >= cutoff_4d:
            recent_4d.add(norm)

    return recent_5d, recent_4d


# ━━━━━━━━━━━━━━━━━━━━ 4. 배정 제품 선택 ━━━━━━━━━━━━━━━━━━━━
def select_products(board_keywords):
    """키워드 전광판의 제품 목록에서 오늘 배정할 제품 선택"""
    product_counts = defaultdict(int)
    for kw in board_keywords:
        product_counts[kw["product"]] += 1

    products = sorted(product_counts.keys())

    print(f"\n{'=' * 60}")
    print(f"  오늘 배정할 제품을 선택하세요")
    print(f"{'=' * 60}")
    for i, product in enumerate(products, 1):
        print(f"  {i}. {product:<15} ({product_counts[product]}개 키워드)")

    print(f"\n  번호 입력 (쉼표 구분, 예: 1,3,5 / 엔터=전체)")
    pick_input = input(f"  → ").strip()

    if not pick_input:
        selected = products
    else:
        try:
            idxs = [int(x.strip()) - 1 for x in pick_input.split(",")]
            selected = [products[i] for i in idxs if 0 <= i < len(products)]
        except ValueError:
            print("  잘못된 입력. 전체 제품으로 진행합니다.")
            selected = products

    if not selected:
        selected = products

    print(f"  → 선택: {', '.join(selected)}")
    return selected


# ━━━━━━━━━━━━━━━━━━━━ 5. 키워드 전광판 로드 ━━━━━━━━━━━━━━━━━━━━
def load_board_keywords(spreadsheet):
    """키워드 전광판 탭에서 키워드 목록 로드"""
    ws = spreadsheet.worksheet(TAB_BOARD)
    rows = ws.get_all_values()

    # Row 0: 날짜 헤더, Row 1: 컬럼 헤더, Row 2+: 데이터
    keywords = []
    for row in rows[2:]:  # 데이터는 3행부터
        product = cell(row, 0)
        keyword = cell(row, 1)
        if not product or not keyword:
            continue

        amount = parse_amount(cell(row, 2))      # C: 기존 전환금액
        rank = cell(row, 3)                        # D: 순위
        days_elapsed = parse_days(cell(row, 8))    # I: 연속일(경과일)
        conversion = parse_amount(cell(row, 9))    # J: 전환금액(현재 링크)

        is_out_of_rank = (rank == "순위 밖")

        keywords.append({
            "product": product,
            "keyword": keyword,
            "amount": amount,
            "rank": rank,
            "days_elapsed": days_elapsed,
            "is_out_of_rank": is_out_of_rank,
            "conversion": conversion,
        })

    return keywords


# ━━━━━━━━━━━━━━━━━━━━ 6. 우선순위 배정 로직 ━━━━━━━━━━━━━━━━━━━━
def prioritize_keywords(board_keywords, selected_products):
    """키워드를 5단계 우선순위로 분류"""
    # 선택된 제품만 필터
    filtered = [kw for kw in board_keywords if kw["product"] in selected_products]

    priority_1 = []  # 기존전환금액 50만+ & 순위밖
    priority_2 = []  # 기존전환금액 50만+ & 경과10일+ & 전환금액 0
    priority_3 = []  # 전환금액 있음 & 순위밖
    priority_4 = []  # 기존전환금액 있음 & 경과10일+
    priority_5 = []  # 순위밖

    for kw in filtered:
        amt = kw["amount"]            # C: 기존 전환금액
        conv = kw["conversion"]       # J: 전환금액
        days = kw["days_elapsed"]     # I: 경과일
        out = kw["is_out_of_rank"]    # 순위 밖

        if amt >= 500_000 and out:
            priority_1.append(kw)
        elif amt >= 500_000 and days >= 10 and conv == 0:
            priority_2.append(kw)
        elif conv > 0 and out:
            priority_3.append(kw)
        elif amt > 0 and days >= 10:
            priority_4.append(kw)
        elif out:
            priority_5.append(kw)

    # 모두 기존 전환금액(C) 내림차순 정렬
    for lst in [priority_1, priority_2, priority_3, priority_4, priority_5]:
        lst.sort(key=lambda x: x["amount"], reverse=True)

    return priority_1, priority_2, priority_3, priority_4, priority_5


def pick_best_writer(product, remaining, writer_efficiency, writer_product_count):
    """해당 제품에 가장 적합한 작가 선택

    선택 기준 (우선순위):
    1. 해당 제품 전환금액이 높은 작가
    2. 이미 같은 제품을 많이 받은 작가는 후순위 (분산)
    3. 동점이면 남은 건수가 많은 작가
    """
    active = {w: r for w, r in remaining.items() if r > 0}
    if not active:
        return None

    def score(writer):
        eff = writer_efficiency.get(writer, {}).get(product, {"amount": 0})
        already = writer_product_count.get(writer, {}).get(product, 0)
        # 이미 같은 제품을 받았으면 패널티 (-1000억 per count)
        penalty = already * 100_000_000_000
        return (eff["amount"] - penalty, active[writer])

    return max(active, key=score)


def assign_to_writers(writers_quota, priority_lists, pre_assignments,
                      writer_efficiency, recent_5d, recent_4d):
    """작가별로 키워드 배정 (제품 효율 기반 매칭 + 5일 중복 방지)

    Args:
        writers_quota: {작가명: 배정건수}
        priority_lists: (1차, 2차, 3차) 우선순위 키워드 리스트
        pre_assignments: 사전 확정 리스트
        writer_efficiency: {작가명: {제품명: {"amount": 총금액, "count": 건수}}}
        recent_5d: set - 최근 5일 이내 배정 키워드 (norm)
        recent_4d: set - 최근 4일 이내 배정 키워드 (norm)

    Returns:
        배정 결과 리스트 [{writer, product, keyword, reason, amount}, ...]
    """
    results = []
    used_keywords = set()

    # 작가별 남은 건수 추적
    remaining = dict(writers_quota)
    # 작가별 이번 배정에서 받은 제품 카운트 (분산용)
    writer_product_count = defaultdict(lambda: defaultdict(int))

    def norm_kw(kw):
        return kw.replace(" ", "").lower()

    # ── 사전 확정 키워드 먼저 배정 ──
    for pa in pre_assignments:
        writer = pa["writer"]
        if remaining.get(writer, 0) <= 0:
            print(f"    [건너뜀] {writer} 배정 건수 초과 → {pa['keyword']}")
            continue
        results.append({
            "writer": writer,
            "product": pa["product"],
            "keyword": pa["keyword"],
            "reason": "사전 확정",
            "amount": 0,
        })
        remaining[writer] -= 1
        writer_product_count[writer][pa["product"]] += 1
        used_keywords.add(pa["keyword"])

    # ── 1차 배정: 5일 중복 제외하고 우선순위별 배정 ──
    priority_labels = [
        "1차(기존전환50만+순위밖)",
        "2차(기존전환50만+경과10일+전환없음)",
        "3차(전환있음+순위밖)",
        "4차(기존전환+경과10일)",
        "5차(순위밖)",
    ]
    skipped_by_dedup = []  # 5일 중복으로 건너뛴 것 (4일 초과만 모아둠)

    for priority_idx, (kw_list, label) in enumerate(
        zip(priority_lists, priority_labels)
    ):
        if sum(remaining.values()) <= 0:
            break

        for kw in kw_list:
            if kw["keyword"] in used_keywords:
                continue
            if sum(remaining.values()) <= 0:
                break

            nk = norm_kw(kw["keyword"])

            # 5일 이내 중복 → 건너뜀 (단, 4일 초과인 것은 후보로 보관)
            if nk in recent_5d:
                if nk not in recent_4d:
                    skipped_by_dedup.append((kw, label))
                continue

            writer = pick_best_writer(
                kw["product"], remaining, writer_efficiency,
                writer_product_count,
            )
            if not writer:
                break

            results.append({
                "writer": writer,
                "product": kw["product"],
                "keyword": kw["keyword"],
                "reason": label,
                "amount": kw["amount"],
            })
            remaining[writer] -= 1
            writer_product_count[writer][kw["product"]] += 1
            used_keywords.add(kw["keyword"])

    # ── 2차 배정: 건수 부족하면 4일 전 배정분에서 채움 ──
    total_unfilled = sum(remaining.values())
    if total_unfilled > 0 and skipped_by_dedup:
        print(f"\n    키워드 부족 → 4일 전 배정분 {len(skipped_by_dedup)}건에서 추가 배정")
        # 전환금액 내림차순 정렬
        skipped_by_dedup.sort(key=lambda x: x[0]["amount"], reverse=True)

        for kw, label in skipped_by_dedup:
            if kw["keyword"] in used_keywords:
                continue
            if sum(remaining.values()) <= 0:
                break

            writer = pick_best_writer(
                kw["product"], remaining, writer_efficiency,
                writer_product_count,
            )
            if not writer:
                break

            results.append({
                "writer": writer,
                "product": kw["product"],
                "keyword": kw["keyword"],
                "reason": f"{label}(4일전 재배정)",
                "amount": kw["amount"],
            })
            remaining[writer] -= 1
            writer_product_count[writer][kw["product"]] += 1
            used_keywords.add(kw["keyword"])

    return results, remaining


# ━━━━━━━━━━━━━━━━━━━━ 7. 원고 배정 탭 기록 ━━━━━━━━━━━━━━━━━━━━
def write_assignments(spreadsheet, results):
    """원고 배정 탭에 배정 결과 기록"""
    ws = spreadsheet.worksheet(TAB_ASSIGN)
    existing = ws.get_all_values()

    today_str = datetime.now().strftime("%Y-%m-%d")
    start_row = len(existing) + 1

    # 작가명 오름차순 정렬
    sorted_results = sorted(results, key=lambda r: r["writer"])

    rows_to_write = []
    for r in sorted_results:
        rows_to_write.append([
            today_str,
            r["writer"],
            r["product"],
            r["keyword"],
            r["reason"],
            r.get("smart_block", ""),
            r.get("popular", ""),
            r.get("brand", ""),
        ])

    if rows_to_write:
        end_row = start_row + len(rows_to_write) - 1
        ws.update(
            range_name=f"A{start_row}:H{end_row}",
            values=rows_to_write,
        )

    return len(rows_to_write)


# ━━━━━━━━━━━━━━━━━━━━ 미리보기 + 수정 + 확인 ━━━━━━━━━━━━━━━━━━━━
def print_results(results, writers_quota):
    """배정 결과를 전체 번호와 함께 출력"""
    print(f"\n{'=' * 75}")
    print(f"  배정 결과 미리보기")
    print(f"{'=' * 75}")

    # 작가별 그룹핑
    by_writer = defaultdict(list)
    for idx, r in enumerate(results):
        by_writer[r["writer"]].append((idx, r))

    has_naver = any("smart_block" in r for r in results)

    for writer in sorted(by_writer.keys()):
        items = by_writer[writer]
        quota = writers_quota.get(writer, 0)
        print(f"\n  ┌─ [{writer}] {len(items)}/{quota}건 ──────────")
        for idx, r in items:
            amt = f"{r['amount']:,}원" if r["amount"] > 0 else "-"
            line = (f"  │ {idx + 1:>2}. {r['product']:<12} {r['keyword']:<25} "
                    f"전환금액 {amt:>12}  [{r['reason']}]")
            if has_naver:
                sb = r.get("smart_block", "?")
                pp = r.get("popular", "?")
                bd = r.get("brand", "?")
                line += f"  스블:{sb} 인기:{pp} 브랜드:{bd}"
            print(line)
        print(f"  └{'─' * 70}")

    total = len(results)
    total_quota = sum(writers_quota.values())
    print(f"\n  총 {total}/{total_quota}건 배정")

    reason_counts = defaultdict(int)
    for r in results:
        reason_counts[r["reason"]] += 1
    for reason, count in sorted(reason_counts.items()):
        print(f"    {reason}: {count}건")


def find_next_keyword(results, priority_lists, writer, writer_efficiency):
    """현재 배정된 키워드를 제외하고, 해당 작가에게 맞는 다음 키워드 자동 선택"""
    used = {r["keyword"] for r in results}
    priority_labels = [
        "1차(기존전환50만+순위밖)",
        "2차(기존전환50만+경과10일+전환없음)",
        "3차(전환있음+순위밖)",
        "4차(기존전환+경과10일)",
        "5차(순위밖)",
    ]

    # 작가의 제품별 효율 (내림차순)
    w_eff = writer_efficiency.get(writer, {})

    for kw_list, label in zip(priority_lists, priority_labels):
        for kw in kw_list:
            if kw["keyword"] in used:
                continue
            return kw, label

    return None, None


def edit_result(results, idx, writers_quota, priority_lists, writer_efficiency):
    """특정 번호를 다음 우선순위 키워드로 자동 교체"""
    r = results[idx]
    old_kw = r["keyword"]

    new_kw, new_label = find_next_keyword(
        results, priority_lists, r["writer"], writer_efficiency
    )
    if new_kw:
        r["product"] = new_kw["product"]
        r["keyword"] = new_kw["keyword"]
        r["amount"] = new_kw["amount"]
        r["reason"] = new_label
        amt = f"{new_kw['amount']:,}원" if new_kw['amount'] > 0 else "-"
        print(f"\n    {old_kw}")
        print(f"      → {new_kw['product']} | {new_kw['keyword']} (전환금액 {amt}) [{new_label}]")
    else:
        print(f"\n    교체할 키워드가 더 이상 없습니다.")


def preview_and_confirm(results, writers_quota, priority_lists, writer_efficiency):
    """배정 결과 미리보기 → 수정 → 확인 루프"""
    while True:
        print_results(results, writers_quota)

        print(f"\n  수정할 번호가 있나요? (번호 입력 / y=확정 / n=전체취소)")
        choice = input(f"  → ").strip().lower()

        if choice == "y":
            return True
        elif choice == "n":
            return False
        else:
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(results):
                    edit_result(results, idx, writers_quota,
                                priority_lists, writer_efficiency)
                else:
                    print(f"    1~{len(results)} 사이 번호를 입력하세요.")
            except ValueError:
                print(f"    번호, y, n 중 입력하세요.")


# ━━━━━━━━━━━━━━━━━━━━ 메인 ━━━━━━━━━━━━━━━━━━━━
def main():
    today = datetime.now()
    today_str = today.strftime("%Y-%m-%d")

    print("=" * 60)
    print("  키워드 전광판 기반 원고 배정 프로그램")
    print(f"  날짜: {today_str}")
    print("=" * 60)

    # 시트 연결
    print("\n[1] Google Sheets 연결 중...")
    spreadsheet = connect_spreadsheet()

    # ── STEP 1: 작가별 제품 효율 분석 ──
    print("\n[2] 전환 키워드 탭에서 작가별 제품 효율 분석 중...")
    writer_efficiency, writer_best_products = get_writer_product_efficiency(spreadsheet)

    if writer_best_products:
        print(f"\n  작가별 강점 제품 (전환금액 기준):")
        for writer in sorted(writer_best_products.keys()):
            eff = writer_efficiency[writer]
            top3 = writer_best_products[writer][:3]
            parts = []
            for p in top3:
                amt = eff[p]["amount"]
                cnt = eff[p]["count"]
                parts.append(f"{p}({amt:,}원/{cnt}건)")
            print(f"    {writer}: {', '.join(parts)}")

    # ── STEP 2: 작가별 작성 건수 확인 ──
    print("\n[3] 원고 작성 건수 확인 중...")
    writers = get_today_quotas(spreadsheet)

    print(f"\n  오늘({today.month}/{today.day}) 작가별 작성 건수:")
    print(f"  {'작가명':<10} {'건수':>5}")
    print(f"  {'-' * 20}")
    for writer, quota in sorted(writers.items()):
        if quota > 0:
            print(f"  {writer:<10} {quota:>5}건")
    total = sum(writers.values())
    print(f"  {'-' * 20}")
    print(f"  {'합계':<10} {total:>5}건")

    # 건수 0인 작가 제외
    active_writers = {w: q for w, q in writers.items() if q > 0}
    if not active_writers:
        print("\n  오늘 배정할 작가가 없습니다.")
        return

    # ── STEP 3: 배정 건수 입력 ──
    print(f"\n[4] 작가별로 배정 건수를 다르게 설정하시겠습니까?")
    diff_input = input(f"  → (y/n, 엔터=n): ").strip().lower()

    if diff_input in ("y", "yes"):
        # 작가별 개별 건수 입력
        writers_quota = {}
        print(f"\n  각 작가별 배정 건수를 입력하세요 (엔터=시트 건수 그대로)")
        for writer in sorted(active_writers.keys()):
            orig = active_writers[writer]
            w_input = input(f"    {writer} (시트: {orig}건) → ").strip()
            if w_input:
                try:
                    writers_quota[writer] = max(int(w_input), 0)
                except ValueError:
                    print(f"      숫자 오류. 시트 건수({orig}건) 유지.")
                    writers_quota[writer] = orig
            else:
                writers_quota[writer] = orig
        # 0건 작가 제외
        writers_quota = {w: q for w, q in writers_quota.items() if q > 0}
    else:
        # 기존 방식: 전체 공통 최대 건수
        print(f"\n  오늘 최대 배정 건수를 입력하세요")
        print(f"    (모든 작가에게 동일 적용, 기존 건수가 적으면 그대로 유지)")
        max_input = input(f"  → 최대 건수: ").strip()
        try:
            max_count = int(max_input)
        except ValueError:
            print("  숫자 입력 오류. 기본값 3으로 진행합니다.")
            max_count = 3
        writers_quota = apply_max_quota(active_writers, max_count)

    print(f"\n  배정 건수:")
    for writer, quota in sorted(writers_quota.items()):
        orig = active_writers[writer]
        marker = "" if orig != quota else ""
        if orig != quota:
            marker = f" (시트 {orig}건 → {quota}건)"
        print(f"    {writer}: {quota}건{marker}")

    # ── STEP 4: 사전 확정 키워드 ──
    pre_assignments = get_pre_assignments(writers_quota)

    # ── STEP 5: 키워드 전광판 로드 ──
    print(f"\n[6] 키워드 전광판 로드 중...")
    board_keywords = load_board_keywords(spreadsheet)
    print(f"    {len(board_keywords)}개 키워드 로드 완료")

    # ── STEP 6: 제품 선택 ──
    selected_products = select_products(board_keywords)

    # ── STEP 7: 최근 배정 이력 (중복 방지) ──
    print(f"\n[7] 최근 배정 이력 확인 중 (5일 중복 방지)...")
    recent_5d, recent_4d = get_recent_assignments(spreadsheet)
    print(f"    최근 5일 배정: {len(recent_5d)}건, 4일 이내: {len(recent_4d)}건")

    # ── STEP 8: 우선순위 분류 ──
    print(f"\n[8] 우선순위 분류 중...")
    p1, p2, p3, p4, p5 = prioritize_keywords(board_keywords, selected_products)
    print(f"    1차 (기존전환 50만+ & 순위밖):           {len(p1)}건")
    print(f"    2차 (기존전환 50만+ & 경과10일 & 전환없음): {len(p2)}건")
    print(f"    3차 (전환있음 & 순위밖):                  {len(p3)}건")
    print(f"    4차 (기존전환 & 경과10일+):               {len(p4)}건")
    print(f"    5차 (순위밖):                            {len(p5)}건")

    # ── STEP 9: 배정 실행 ──
    print(f"\n[9] 배정 실행 중 (작가-제품 효율 매칭 + 5일 중복 방지)...")
    results, remaining = assign_to_writers(
        writers_quota, (p1, p2, p3, p4, p5), pre_assignments,
        writer_efficiency, recent_5d, recent_4d,
    )

    if not results:
        print("  배정할 키워드가 없습니다.")
        return

    # ── 미리보기 + 확인 ──
    if not preview_and_confirm(results, writers_quota, (p1, p2, p3, p4, p5), writer_efficiency):
        print("\n  배정을 취소합니다.")
        return

    # ── STEP 10: 네이버 스마트블록/인기글 체크 ──
    print(f"\n[10] 네이버 스마트블록/인기글 체크 중...")
    check_all_keywords(results)

    # ── STEP 11: 원고 배정 탭에 기록 ──
    print(f"\n[11] 원고 배정 탭에 기록 중...")
    written = write_assignments(spreadsheet, results)
    print(f"    {written}건 기록 완료!")

    # 미배정 작가 알림
    unfilled = {w: r for w, r in remaining.items() if r > 0}
    if unfilled:
        print(f"\n  미배정 작가:")
        for w, r in unfilled.items():
            print(f"    {w}: {r}건 미배정")

    print(f"\n{'=' * 60}")
    print(f"  원고 배정 완료!")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
