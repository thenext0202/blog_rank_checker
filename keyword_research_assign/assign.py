#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
keyword_research/assign.py - 키워드 배정 프로그램

원고 작가별 키워드 배정:
1. 시트1에서 연관 검색어 읽어서 검색량 1,000 이상인 키워드를 키워드 창고에 추가
2. 원고 작성 건수 탭에서 오늘 날짜의 작가별 건수 확인
3. 사용자에게 각 작가별 최대 배정 건수 입력 받기
4. 키워드 창고에서 검색량 1,000 이상 키워드만 배정 (전환 60% + 잠재 40%)
5. 작가 전문 분야(제품) 기반 매칭
6. 2주 이내 중복 방지, 2주 초과 데이터 삭제
7. 네이버 검색 결과에서 스마트블록/인기글 확인
8. 키워드 배정 탭에 결과 기록
"""

import os
import sys
import json
import math
import time
import re
import hmac
import hashlib
import base64
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from collections import defaultdict

import gspread
from google.oauth2.service_account import Credentials

# ━━━━━━━━━━━━━━━━━━━━ 설정 ━━━━━━━━━━━━━━━━━━━━
SPREADSHEET_ID = "1_rytQ5eGEui7R-P8aq_7OmNulix-SxDxF3yIcOWmumU"
CRED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "credentials.json")

NAVER_API_KEY = os.environ.get("NAVER_API_KEY", "010000000061419c77434a47cc8ed45e1f410e7af57bc5873ffe2606c36b734b701d7d6c95")
NAVER_SECRET_KEY = os.environ.get("NAVER_SECRET_KEY", "AQAAAABhQZx3Q0pHzI7UXh9BDnr1Qon+MpR9eV8dvINigfkudg==")
NAVER_CUSTOMER_ID = os.environ.get("NAVER_CUSTOMER_ID", "2120690")

MIN_SEARCH_VOLUME = 1000  # 배정 최소 검색량

# 구매 의도 키워드
PURCHASE_INTENT_WORDS = [
    # 구매/비교
    "추천", "가격", "후기", "비교", "구매", "최저가", "할인", "직구",
    "순위", "TOP", "베스트", "인기", "브랜드", "제품",
    # 효과/성분
    "효능", "효과", "성분", "부작용", "복용법", "먹는법",
    # 건강/의료 전환
    "처방", "약", "치료", "병원", "진료", "검사", "증상", "원인",
    "예방", "개선", "관리", "영양제", "보충제", "유산균", "프로바이오틱스",
    # 구체적 행동
    "방법", "좋은", "먹으면", "하면", "언제", "얼마나", "몇",
]

# 카테고리-제품 매핑 (잠재 키워드 매칭용)
PRODUCT_CATEGORIES = {
    "블러드싸이클": ["혈압", "고혈압", "콜레스테롤", "고지혈증", "오메가3", "혈관", "동맥경화", "중성지방"],
    "혈당컷": ["혈당", "당뇨", "인슐린", "당화혈색소", "혈당조절", "공복혈당", "식후혈당", "임당"],
    "상어연골환": ["관절", "연골", "콘드로이친", "글루코사민", "보스웰리아", "무릎", "퇴행성"],
    "판토오틴": ["탈모", "비오틴", "판토텐산", "머리카락", "두피", "미녹시딜", "모발"],
    "활성엽산": ["엽산", "임산부", "임신", "임신전", "임신중", "모유수유", "철분", "빈혈"],
    "멜라토닌": ["멜라토닌", "수면", "불면", "가바", "수면영양제", "숙면", "잠"],
    "헬리컷": ["위", "속쓰림", "위염", "헬리코박터", "담적", "소화", "역류성"],
    "퓨어톤 부스트": ["글루타치온", "피부", "미백", "리포좀", "항산화", "비타민C"],
}


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


# ━━━━━━━━━━━━━━━━━━━━ 시트1 → 키워드 창고 이동 ━━━━━━━━━━━━━━━━━━━━
def load_conversion_keywords_from_tab(spreadsheet):
    """전환 키워드 탭에서 전환 키워드 목록 읽기"""
    try:
        ws = spreadsheet.worksheet("전환 키워드")
    except gspread.exceptions.WorksheetNotFound:
        print("  [전환 키워드] 탭이 없습니다.")
        return []

    rows = ws.get_all_values()
    if len(rows) < 3:
        return []

    # Row 0: 제품명 (4열마다), Row 1: 헤더 (키워드, 파라미터, 작가, 금액)
    products_row = rows[0]
    products = []
    for i in range(0, len(products_row), 4):
        p = products_row[i].strip()
        if p:
            products.append((p, i))

    conversion_kws = []
    seen = set()
    for row in rows[2:]:
        for product, start_col in products:
            if start_col < len(row):
                keyword = row[start_col].strip()
                amount_str = row[start_col + 3].strip() if len(row) > start_col + 3 else ""
                if not keyword or keyword in seen:
                    continue
                seen.add(keyword)
                try:
                    amount = float(amount_str.replace(",", "")) if amount_str else 0
                except ValueError:
                    amount = 0
                conversion_kws.append({
                    "product": product,
                    "keyword": keyword,
                    "amount": amount,
                })

    return conversion_kws


def refresh_warehouse_from_sheet1(spreadsheet):
    """키워드 창고 초기화: 전환 키워드 탭에서 전환 키워드 로드 + 시트1 연관 검색어 추가"""

    ws_warehouse = spreadsheet.worksheet("키워드 창고")
    wh_rows = ws_warehouse.get_all_values()

    header = wh_rows[0] if wh_rows else ["제품명", "키워드", "검색량", "평균전환금액", "분류"]

    # 1) 전환 키워드 탭에서 전환 키워드 로드
    conv_tab_kws = load_conversion_keywords_from_tab(spreadsheet)

    # 기존 창고의 전환 키워드도 유지 (탭에 없는 것 포함)
    existing_conv_kws = set()
    for kw_info in conv_tab_kws:
        existing_conv_kws.add(norm_keyword(kw_info["keyword"]))

    conversion_rows = []
    for kw_info in conv_tab_kws:
        conversion_rows.append([
            kw_info["product"],
            kw_info["keyword"],
            "",  # 검색량은 나중에 API로 조회
            str(int(kw_info["amount"])) if kw_info["amount"] else "",
            "전환 키워드",
        ])

    # 기존 창고에 있던 전환 키워드 중 탭에 없는 것도 유지
    for row in wh_rows[1:]:
        if len(row) >= 5 and "전환" in row[4]:
            kw = row[1].strip()
            if norm_keyword(kw) not in existing_conv_kws:
                conversion_rows.append(row)
                existing_conv_kws.add(norm_keyword(kw))

    # 기존 데이터 전체 클리어 후 전환 키워드 다시 쓰기
    ws_warehouse.batch_clear([f"A1:E{len(wh_rows) + 100}"])
    ws_warehouse.update(range_name="A1:E1", values=[header])

    if conversion_rows:
        ws_warehouse.update(
            range_name=f"A2:E{len(conversion_rows) + 1}",
            values=conversion_rows,
        )

    print(f"  [키워드 창고] 전환 키워드 {len(conversion_rows)}개 로드 (전환 키워드 탭 기준)")

    # 2) 시트1에서 연관 검색어 읽기
    try:
        ws_sheet1 = spreadsheet.worksheet("시트1")
    except gspread.exceptions.WorksheetNotFound:
        print("  [시트1] 시트1 탭이 없습니다. 건너뜁니다.")
        return len(conversion_rows)

    rows = ws_sheet1.get_all_values()
    if len(rows) <= 1:
        print("  [시트1] 데이터가 없습니다.")
        return len(conversion_rows)

    # 시트1 구조: A=제품명, B=시드 키워드, C=추천 키워드, D=출처, E=검색량
    existing_kws = set()
    for row in conversion_rows:
        if len(row) >= 2:
            existing_kws.add(clean_keyword(row[1].strip()))

    new_kws = []
    seen = set()
    for row in rows[1:]:
        if len(row) < 5:
            continue
        product = row[0].strip()
        keyword = row[2].strip()  # 추천 키워드 (C열)
        vol_str = row[4].strip().replace(",", "")

        if not keyword or keyword in seen or keyword in existing_kws:
            continue

        try:
            volume = int(vol_str) if vol_str else 0
        except ValueError:
            volume = 0

        if volume >= MIN_SEARCH_VOLUME:
            new_kws.append({
                "product": product,
                "keyword": keyword,
                "volume": volume,
            })
            seen.add(keyword)

    if not new_kws:
        print("  [시트1] 검색량 1,000 이상 신규 키워드가 없습니다.")
        return len(conversion_rows)

    # 3) 키워드 창고에 추가
    start_row = len(conversion_rows) + 2  # header + 전환 키워드 다음
    add_rows = []
    for kw in new_kws:
        add_rows.append([
            kw["product"],
            kw["keyword"],
            str(kw["volume"]),
            "",  # 평균전환금액 없음
            "잠재 키워드",
        ])

    end_row = start_row + len(add_rows) - 1
    ws_warehouse.update(range_name=f"A{start_row}:E{end_row}", values=add_rows)

    print(f"  [시트1 → 키워드 창고] {len(new_kws)}개 추가 (검색량 1,000 이상)")
    for kw in new_kws[:10]:
        print(f"    + {kw['product']} | {kw['keyword']} (검색량 {kw['volume']:,})")
    if len(new_kws) > 10:
        print(f"    ... 외 {len(new_kws) - 10}개")

    return len(conversion_rows) + len(new_kws)


# ━━━━━━━━━━━━━━━━━━━━ 원고 작성 건수 읽기 ━━━━━━━━━━━━━━━━━━━━
def get_today_quotas(spreadsheet):
    """원고 작성 건수 탭에서 오늘 날짜에 해당하는 작가별 건수 가져오기"""
    ws = spreadsheet.worksheet("원고 작성 건수")
    rows = ws.get_all_values()

    today = datetime.now()
    today_str = f"{today.month}/{today.day}"  # e.g. "3/9"

    writers = {}
    found_block = False

    for i, row in enumerate(rows):
        if row[0] == "작가명" and today_str in row:
            # 이 블록에서 오늘 날짜 컬럼 찾기
            col_idx = row.index(today_str)
            found_block = True
            # 다음 행부터 작가 데이터 읽기
            for j in range(i + 1, len(rows)):
                r = rows[j]
                name = r[0].strip()
                if name == "총합" or name == "작가명" or not name:
                    break
                try:
                    quota = int(r[col_idx]) if r[col_idx] else 0
                except ValueError:
                    quota = 0
                writers[name] = quota
            break

    if not found_block:
        print(f"[오류] 원고 작성 건수 탭에서 오늘 날짜({today_str})를 찾을 수 없습니다.")
        print("  헤더에 있는 날짜들:")
        for row in rows:
            if row[0] == "작가명":
                print(f"  {row[1:6]}")
        sys.exit(1)

    return writers


# ━━━━━━━━━━━━━━━━━━━━ 작가 전문 분야 파악 ━━━━━━━━━━━━━━━━━━━━
def get_writer_specialties(spreadsheet):
    """전환 키워드 탭에서 각 작가가 어떤 제품을 많이 작성했는지 파악"""
    ws = spreadsheet.worksheet("전환 키워드")
    rows = ws.get_all_values()

    if len(rows) < 3:
        return {}

    # Row 0: product names (every 4 columns)
    # Row 1: headers (키워드, 파라미터, 작가, 금액) repeated
    # Row 2+: data
    products_row = rows[0]
    products = []
    for i in range(0, len(products_row), 4):
        p = products_row[i].strip()
        if p:
            products.append((p, i))  # (product_name, start_col)

    writer_products = defaultdict(lambda: defaultdict(int))  # writer -> {product: count}
    writer_avg_amount = defaultdict(lambda: defaultdict(list))  # writer -> {product: [amounts]}

    for row in rows[2:]:
        for product, start_col in products:
            if start_col + 2 < len(row):
                writer = row[start_col + 2].strip() if len(row) > start_col + 2 else ""
                amount_str = row[start_col + 3].strip() if len(row) > start_col + 3 else ""
                if writer:
                    writer_products[writer][product] += 1
                    try:
                        amount = float(amount_str.replace(",", ""))
                        writer_avg_amount[writer][product].append(amount)
                    except (ValueError, AttributeError):
                        pass

    return writer_products, writer_avg_amount


# ━━━━━━━━━━━━━━━━━━━━ 키워드 이름 정리 ━━━━━━━━━━━━━━━━━━━━
def clean_keyword(keyword):
    """키워드에서 (1), (2) 같은 번호 접미사 제거"""
    return re.sub(r'\(\d+\)\s*$', '', keyword).strip()


def norm_keyword(keyword):
    """키워드 정규화 (띄어쓰기 제거 + 소문자) — 중복 비교용"""
    return keyword.replace(" ", "").lower()


# ━━━━━━━━━━━━━━━━━━━━ 검색량 조회 (네이버 검색광고 API) ━━━━━━━━━━━━━━━━━━━━
def generate_signature(timestamp, method, path):
    message = f"{timestamp}.{method}.{path}"
    sign = hmac.new(
        NAVER_SECRET_KEY.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(sign).decode("utf-8")


def fetch_search_volumes(keywords_list):
    """네이버 검색광고 API로 검색량 일괄 조회 (5개씩 배치)"""
    if not (NAVER_API_KEY and NAVER_SECRET_KEY and NAVER_CUSTOMER_ID):
        print("  [오류] 네이버 API 환경변수가 설정되지 않았습니다.")
        return {}

    volume_map = {}
    # 5개씩 배치
    for i in range(0, len(keywords_list), 5):
        batch = keywords_list[i:i+5]
        path = "/keywordstool"
        timestamp = str(int(time.time() * 1000))
        signature = generate_signature(timestamp, "GET", path)

        params = urllib.parse.urlencode({
            "hintKeywords": ",".join(s.replace(" ", "") for s in batch),
            "showDetail": "1",
        })
        url = f"https://api.searchad.naver.com{path}?{params}"

        req = urllib.request.Request(url, method="GET")
        req.add_header("X-Timestamp", timestamp)
        req.add_header("X-API-KEY", NAVER_API_KEY)
        req.add_header("X-Customer", NAVER_CUSTOMER_ID)
        req.add_header("X-Signature", signature)
        req.add_header("Content-Type", "application/json")

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            for item in data.get("keywordList", []):
                kw = item.get("relKeyword", "")
                pc = item.get("monthlyPcQcCnt", 0)
                mo = item.get("monthlyMobileQcCnt", 0)
                if isinstance(pc, str):
                    pc = 0
                if isinstance(mo, str):
                    mo = 0
                volume_map[kw] = int(pc) + int(mo)
                # 공백 제거 버전도 저장
                volume_map[kw.replace(" ", "")] = int(pc) + int(mo)
        except Exception as e:
            print(f"  [API 오류] {e}")

        time.sleep(0.3)

    return volume_map


# ━━━━━━━━━━━━━━━━━━━━ 키워드 창고 읽기 ━━━━━━━━━━━━━━━━━━━━
def get_keyword_warehouse(spreadsheet):
    """키워드 창고 탭에서 키워드 목록 읽기 + 검색량 없으면 API로 조회"""
    ws = spreadsheet.worksheet("키워드 창고")
    rows = ws.get_all_values()

    keywords = []
    need_volume = []  # 검색량 조회 필요한 키워드
    for row in rows[1:]:  # skip header
        if len(row) < 5:
            continue
        product = row[0].strip()
        keyword = clean_keyword(row[1].strip())
        search_vol = row[2].strip().replace(",", "")
        avg_amount = row[3].strip().replace(",", "")
        category = row[4].strip()  # "전환 키워드" or other

        if not keyword:
            continue

        try:
            search_vol = int(search_vol) if search_vol else 0
        except ValueError:
            search_vol = 0

        try:
            avg_amount = float(avg_amount) if avg_amount else 0
        except ValueError:
            avg_amount = 0

        keywords.append({
            "product": product,
            "keyword": keyword,
            "search_vol": search_vol,
            "avg_amount": avg_amount,
            "is_conversion": "전환" in category,
        })

        if search_vol == 0:
            need_volume.append(keyword)

    # 검색량 없는 키워드 API 조회
    if need_volume:
        print(f"  검색량 없는 키워드 {len(need_volume)}개 → API 조회 중...")
        volume_map = fetch_search_volumes(need_volume)
        for kw_info in keywords:
            if kw_info["search_vol"] == 0:
                kw = kw_info["keyword"]
                vol = volume_map.get(kw, volume_map.get(kw.replace(" ", ""), 0))
                kw_info["search_vol"] = vol

    return keywords


# ━━━━━━━━━━━━━━━━━━━━ 기존 배정 확인 (2주 중복 방지) ━━━━━━━━━━━━━━━━━━━━
def get_existing_assignments(spreadsheet):
    """키워드 배정 탭에서 기존 배정 데이터 읽기, 2주 초과 데이터 삭제"""
    ws = spreadsheet.worksheet("키워드 배정")
    rows = ws.get_all_values()

    if len(rows) <= 1:
        return set(), ws

    today = datetime.now().date()
    two_weeks_ago = today - timedelta(days=14)

    assigned_keywords = set()  # 키워드 (띄어쓰기 제거) 세트 — 작가 무관 2주 중복 방지
    rows_to_keep = [rows[0]]  # header

    for row in rows[1:]:
        if not row[0]:
            continue
        try:
            row_date = datetime.strptime(row[0], "%Y-%m-%d").date()
        except ValueError:
            continue

        if row_date >= two_weeks_ago:
            rows_to_keep.append(row)
            keyword = row[3].strip() if len(row) > 3 else ""
            if keyword:
                assigned_keywords.add(norm_keyword(keyword))

    # 2주 초과 데이터 삭제
    if len(rows_to_keep) < len(rows):
        deleted = len(rows) - len(rows_to_keep)
        print(f"[정리] 2주 초과 데이터 {deleted}건 삭제")
        ws.batch_clear([f"A2:K{len(rows) + 10}"])
        if len(rows_to_keep) > 1:
            ws.update(range_name=f"A2:K{len(rows_to_keep)}", values=rows_to_keep[1:])

    return assigned_keywords, ws


# ━━━━━━━━━━━━━━━━━━━━ 전환점수 계산 ━━━━━━━━━━━━━━━━━━━━
def calc_conversion_score(keyword_info):
    """잠재 키워드의 전환 가능성 점수 계산"""
    score = 0
    kw = keyword_info["keyword"]

    # 1) 검색량 점수 (최대 30점)
    vol = keyword_info["search_vol"]
    if vol >= 10000:
        score += 30
    elif vol >= 5000:
        score += 25
    elif vol >= 3000:
        score += 20
    elif vol >= 1000:
        score += 15
    elif vol >= 500:
        score += 10

    # 2) 구매의도 키워드 포함 (최대 50점) — 넓은 기준
    intent_count = sum(1 for w in PURCHASE_INTENT_WORDS if w in kw)
    score += min(intent_count * 15, 50)

    # 3) 카테고리 키워드 포함 (최대 15점)
    product = keyword_info["product"]
    categories = PRODUCT_CATEGORIES.get(product, [])
    for cat in categories:
        if cat in kw:
            score += 15
            break

    # 4) 전환금액 기반 (최대 20점)
    if keyword_info["avg_amount"] > 100000:
        score += 20
    elif keyword_info["avg_amount"] > 50000:
        score += 14
    elif keyword_info["avg_amount"] > 10000:
        score += 10

    return round(score, 1)


# ━━━━━━━━━━━━━━━━━━━━ 배정 사유 생성 ━━━━━━━━━━━━━━━━━━━━
def generate_reason(keyword_info, is_conversion):
    """배정 사유 텍스트 생성"""
    if is_conversion:
        amt = keyword_info["avg_amount"]
        if amt > 0:
            return f"평균 {int(amt):,}원"
        return "전환 키워드"

    # 잠재 키워드
    parts = []
    score = calc_conversion_score(keyword_info)
    parts.append(f"점수 {score}")

    kw = keyword_info["keyword"]
    # 구매의도
    matched_intents = [w for w in PURCHASE_INTENT_WORDS if w in kw]
    if matched_intents:
        parts.append(f"구매의도({', '.join(matched_intents[:3])})")

    # 카테고리 매칭
    product = keyword_info["product"]
    categories = PRODUCT_CATEGORIES.get(product, [])
    for cat in categories:
        if cat in kw:
            parts.append(f"카테고리({cat})")
            break

    # 검색량
    if keyword_info["search_vol"]:
        parts.append(f"검색량 {keyword_info['search_vol']:,}")

    return " | ".join(parts)


# ━━━━━━━━━━━━━━━━━━━━ 네이버 자동완성 띄어쓰기 ━━━━━━━━━━━━━━━━━━━━
def get_naver_spacing(keyword):
    """네이버 자동완성에서 키워드의 올바른 띄어쓰기 가져오기"""
    try:
        q = urllib.parse.quote(keyword.replace(" ", ""))
        url = (f"https://ac.search.naver.com/nx/ac?q={q}&q_enc=UTF-8"
               f"&st=100&frm=nv&r_format=json&r_enc=UTF-8&r_unicode=0"
               f"&t_koreng=1&ans=2&run=2&rev=4&con=1")
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "Mozilla/5.0")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        kw_nospace = keyword.replace(" ", "").lower()
        for group in data.get("items", []):
            for pair in group:
                if isinstance(pair, list) and len(pair) > 0:
                    candidate = pair[0].strip()
                    if candidate.replace(" ", "").lower() == kw_nospace:
                        return candidate
        return keyword
    except Exception:
        return keyword


def batch_naver_spacing(keywords):
    """여러 키워드의 네이버 자동완성 띄어쓰기 일괄 조회"""
    result = {}
    for kw in keywords:
        spaced = get_naver_spacing(kw)
        result[kw] = spaced
        time.sleep(0.15)
    return result


# ━━━━━━━━━━━━━━━━━━━━ 네이버 검색 (스마트블록/인기글) ━━━━━━━━━━━━━━━━━━━━
# 스마트블록이 아닌 일반 검색 섹션 이름들
GENERIC_SECTIONS = {
    "브랜드 콘텐츠", "이미지", "뉴스", "동영상", "지식iN", "쇼핑",
    "지도", "장소", "사전", "웹사이트", "카페", "학술정보",
    "어학사전", "도서", "뮤직", "영화", "TV", "플레이스",
}


def check_naver_blog_blocks(keyword):
    """네이버에서 키워드 검색 후 스마트블록 존재 여부 확인

    스마트블록: 네이버 검색 결과에서 키워드 관련 블로그 콘텐츠가
    별도 블록으로 큐레이션되어 노출되는 영역.
    일반 섹션(브랜드 콘텐츠, 이미지, 뉴스 등)을 제외한
    subjectTitle이 있으면 스마트블록으로 판별.
    """
    try:
        q = urllib.parse.quote(keyword)
        url = f"https://search.naver.com/search.naver?where=nexearch&query={q}"
        req = urllib.request.Request(url)
        req.add_header("User-Agent",
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8")

        # subjectTitle 추출 후 일반 섹션 제외 → 나머지가 스마트블록
        subject_titles = re.findall(r'"subjectTitle":"([^"]+)"', html)
        smart_blocks = [t for t in subject_titles if t not in GENERIC_SECTIONS]

        has_smart = "O" if smart_blocks else "X"
        smart_titles = ", ".join(smart_blocks) if smart_blocks else ""

        return has_smart, smart_titles
    except Exception as e:
        print(f"  [네이버 검색 오류] {keyword}: {e}")
        return "?", ""


# ━━━━━━━━━━━━━━━━━━━━ 잠재 키워드 미리보기 (전체 작가 한번에) ━━━━━━━━━━━━━━━━━━━━
def review_all_potential_keywords(writer_candidates, remaining_pot, writer_pot_needs):
    """전체 작가의 잠재 키워드를 한번에 보여주고 사용자 확인"""
    # 제외된 키워드 추적 (대체 후보에서도 제외)
    excluded_kws = set()

    while True:
        # ── 전체 미리보기 출력 ──
        print(f"\n{'=' * 70}")
        print(f"  잠재 키워드 배정 미리보기 (전체 작가)")
        print(f"{'=' * 70}")

        global_idx = 0
        idx_map = {}

        for writer in sorted(writer_candidates.keys()):
            candidates = writer_candidates[writer]
            if not candidates:
                print(f"\n  [{writer}] 잠재 키워드 없음")
                continue
            print(f"\n  ┌─ [{writer}] 잠재 {len(candidates)}건 ──────────")
            for local_idx, (score, kw) in enumerate(candidates):
                global_idx += 1
                idx_map[global_idx] = (writer, local_idx)
                vol = f"{kw['search_vol']:,}" if kw["search_vol"] else "-"
                intents = [w for w in PURCHASE_INTENT_WORDS if w in kw["keyword"]]
                intent_str = f" [{', '.join(intents[:3])}]" if intents else ""
                print(f"  │ {global_idx:>2}. {kw['product']:<10} {kw['keyword']:<25} "
                      f"검색량 {vol:>8}  점수 {score}{intent_str}")
            print(f"  └{'─' * 60}")

        total = sum(len(c) for c in writer_candidates.values())
        print(f"\n  총 {total}건")
        print(f"\n  선택하세요:")
        print(f"  1) 이대로 진행")
        print(f"  2) 일부 수정 (특정 키워드 교체)")
        print(f"  3) 전체 다시 선정")
        choice = input(f"  → ").strip()

        if choice == "1":
            return writer_candidates

        elif choice == "2":
            remove_input = input("  제외할 번호 (쉼표 구분, 예: 1,3,5): ").strip()
            try:
                remove_nums = set(int(x.strip()) for x in remove_input.split(","))
            except ValueError:
                print("  잘못된 입력입니다. 다시 선택하세요.")
                continue

            # 제외할 키워드 파악
            remove_by_writer = defaultdict(set)
            for num in remove_nums:
                if num in idx_map:
                    w, local_idx = idx_map[num]
                    remove_by_writer[w].add(local_idx)
                    excluded_kws.add(norm_keyword(writer_candidates[w][local_idx][1]["keyword"]))

            # 제외 적용
            for w, idxs in remove_by_writer.items():
                writer_candidates[w] = [
                    (s, k) for i, (s, k) in enumerate(writer_candidates[w])
                    if i not in idxs
                ]

            # 빈 자리 파악
            writers_need_fill = []
            for w in sorted(writer_candidates.keys()):
                need = writer_pot_needs.get(w, 0) - len(writer_candidates[w])
                if need > 0:
                    writers_need_fill.append((w, need))
            total_fill = sum(n for _, n in writers_need_fill)

            if total_fill > 0:
                _show_and_pick_replacements(
                    writer_candidates, remaining_pot, excluded_kws,
                    writers_need_fill, total_fill
                )
            # 다시 미리보기 루프

        elif choice == "3":
            # 현재 키워드 전부 제외 대상에 추가
            for candidates in writer_candidates.values():
                for _, kw in candidates:
                    excluded_kws.add(norm_keyword(kw["keyword"]))

            # 전체 비우기
            for w in writer_candidates:
                writer_candidates[w] = []

            writers_need_fill = [
                (w, writer_pot_needs[w]) for w in sorted(writer_pot_needs.keys())
            ]
            total_fill = sum(n for _, n in writers_need_fill)

            _show_and_pick_replacements(
                writer_candidates, remaining_pot, excluded_kws,
                writers_need_fill, total_fill
            )
            # 다시 미리보기 루프
        else:
            print("  1, 2, 3 중 선택하세요.")


def _show_and_pick_replacements(writer_candidates, remaining_pot, excluded_kws,
                                 writers_need_fill, total_fill):
    """대체 후보 5개씩 보여주고, 거절하면 다음 5개 (끝없이 반복)"""
    all_current_kws = set()
    for candidates in writer_candidates.values():
        for _, kw in candidates:
            all_current_kws.add(kw["keyword"])

    available = [
        (s, k) for s, k in remaining_pot
        if k["keyword"] not in all_current_kws and k["keyword"] not in excluded_kws
    ]

    offset = 0
    while total_fill > 0:
        batch = available[offset:offset + 5]
        if not batch:
            print("  더 이상 대체 후보가 없습니다.")
            break

        print(f"\n  대체 후보 ({offset + 1}~{offset + len(batch)}번째):")
        for i, (score, kw) in enumerate(batch, 1):
            vol = f"{kw['search_vol']:,}" if kw["search_vol"] else "-"
            intents = [w for w in PURCHASE_INTENT_WORDS if w in kw["keyword"]]
            intent_str = f" [{', '.join(intents[:3])}]" if intents else ""
            print(f"    {i}. {kw['product']:<10} {kw['keyword']:<25} "
                  f"검색량 {vol:>8}  점수 {score}{intent_str}")

        fill_str = ", ".join(f"{w}({n}건)" for w, n in writers_need_fill if n > 0)
        print(f"\n  채울 자리: {fill_str} (총 {total_fill}건)")
        print(f"  번호 입력 = 선택, n = 다음 5개 보기")
        pick_input = input(f"  → ").strip()

        if pick_input.lower() == "n":
            offset += 5
            continue

        try:
            pick_idxs = [int(x.strip()) - 1 for x in pick_input.split(",")]
            picked = []
            for idx in pick_idxs:
                if 0 <= idx < len(batch):
                    picked.append(batch[idx])

            # 빈 자리 있는 작가 순서대로 자동 채움
            pick_iter = iter(picked)
            new_writers_need = []
            for w, need in writers_need_fill:
                filled = 0
                for _ in range(need):
                    try:
                        item = next(pick_iter)
                        writer_candidates[w].append(item)
                        excluded_kws.add(norm_keyword(item[1]["keyword"]))
                        filled += 1
                    except StopIteration:
                        break
                remaining_need = need - filled
                if remaining_need > 0:
                    new_writers_need.append((w, remaining_need))
            writers_need_fill[:] = new_writers_need
            total_fill = sum(n for _, n in writers_need_fill)

            if total_fill > 0:
                # 선택된 것 제외하고 available 갱신
                all_current_kws = set()
                for candidates in writer_candidates.values():
                    for _, kw in candidates:
                        all_current_kws.add(norm_keyword(kw["keyword"]))
                available = [
                    (s, k) for s, k in remaining_pot
                    if norm_keyword(k["keyword"]) not in all_current_kws and norm_keyword(k["keyword"]) not in excluded_kws
                ]
                offset = 0
            else:
                print("  대체 완료!")
        except ValueError:
            print("  잘못된 입력입니다. 번호 또는 n을 입력하세요.")


# ━━━━━━━━━━━━━━━━━━━━ 사전 확정 키워드 입력 ━━━━━━━━━━━━━━━━━━━━
def get_pre_assignments(active_writers):
    """배정 전 확정된 키워드 입력받기

    입력 형식:
    - 작가명, 키워드  (예: 김대홍, 고혈압140)
    - 키워드만        (예: 고혈압 140) → 작가 미지정, 나중에 자동 배정
    """
    print(f"\n{'=' * 60}")
    print(f"  오늘 사전 확정 키워드가 있나요?")
    print(f"  형식: 작가명, 키워드 / 키워드만 입력 가능")
    print(f"  예시: 김대홍, 고혈압140")
    print(f"        고혈압 140")
    print(f"  (한 줄에 하나씩, 빈 줄 입력하면 종료)")
    print(f"{'=' * 60}")

    pre_assignments = []  # [{"writer": str or None, "keyword": str}]
    writer_names = set(active_writers.keys())

    while True:
        line = input("  → ").strip()
        if not line:
            break

        # 쉼표가 있으면 작가명, 키워드 분리
        if "," in line:
            parts = line.split(",", 1)
            writer = parts[0].strip()
            keyword = parts[1].strip()

            if writer not in writer_names:
                print(f"    ⚠ '{writer}'는 오늘 배정 작가가 아닙니다. 작가 목록: {', '.join(sorted(writer_names))}")
                retry = input(f"    키워드 '{keyword}'를 자동 배정으로 추가할까요? (y/n): ").strip().lower()
                if retry == "y":
                    pre_assignments.append({"writer": None, "keyword": keyword})
                    print(f"    + {keyword} (자동 배정)")
                continue

            pre_assignments.append({"writer": writer, "keyword": keyword})
            print(f"    + {writer} ← {keyword}")
        else:
            # 키워드만
            pre_assignments.append({"writer": None, "keyword": line})
            print(f"    + {line} (자동 배정)")

    if pre_assignments:
        print(f"\n  확정 키워드 {len(pre_assignments)}건 등록")
    else:
        print(f"\n  확정 키워드 없음")

    return pre_assignments


# ━━━━━━━━━━━━━━━━━━━━ 오늘 배정 제품 선택 ━━━━━━━━━━━━━━━━━━━━
def select_today_products(warehouse):
    """키워드 창고의 제품 목록을 보여주고 오늘 배정할 제품 선택"""
    # 제품별 키워드 수 집계
    product_counts = defaultdict(lambda: {"전환": 0, "잠재": 0})
    for kw in warehouse:
        cat = "전환" if kw["is_conversion"] else "잠재"
        product_counts[kw["product"]][cat] += 1

    products = sorted(product_counts.keys())

    print(f"\n{'=' * 60}")
    print(f"  오늘 배정할 제품을 선택하세요")
    print(f"{'=' * 60}")
    for i, product in enumerate(products, 1):
        c = product_counts[product]
        print(f"  {i}. {product:<15} (전환 {c['전환']}개, 잠재 {c['잠재']}개)")

    print(f"\n  번호 입력 (쉼표 구분, 예: 1,3,5 / 엔터=전체)")
    pick_input = input(f"  → ").strip()

    if not pick_input:
        selected = products
    else:
        try:
            idxs = [int(x.strip()) - 1 for x in pick_input.split(",")]
            selected = [products[i] for i in idxs if 0 <= i < len(products)]
        except ValueError:
            print("  잘못된 입력입니다. 전체 제품으로 진행합니다.")
            selected = products

    if not selected:
        selected = products

    print(f"  → 선택된 제품: {', '.join(selected)}")
    return selected


# ━━━━━━━━━━━━━━━━━━━━ 키워드 중복 제거 (띄어쓰기 무시) ━━━━━━━━━━━━━━━━━━━━
def dedup_keywords(keywords):
    """띄어쓰기만 다른 키워드 중복 제거 (먼저 나온 것 유지)"""
    seen = set()
    result = []
    for kw in keywords:
        nk = norm_keyword(kw["keyword"])
        if nk not in seen:
            seen.add(nk)
            result.append(kw)
    return result


# ━━━━━━━━━━━━━━━━━━━━ 키워드 배정 로직 ━━━━━━━━━━━━━━━━━━━━
def assign_keywords(writers_quota, warehouse, writer_specialties, writer_amounts,
                    existing_assignments, selected_products, pre_assignments=None):
    """각 작가에게 키워드 배정 (전체 기준 전환 70% + 잠재 30%, 작가별 quota 준수)"""
    used_norms = set()  # norm_keyword 기준 중복 방지

    # 선택된 제품만 필터 + 띄어쓰기 중복 제거
    warehouse = dedup_keywords([kw for kw in warehouse if kw["product"] in selected_products])

    all_warehouse = list(warehouse)
    warehouse_vol = [kw for kw in warehouse if kw["search_vol"] >= MIN_SEARCH_VOLUME]
    print(f"  선택 제품: {', '.join(selected_products)}")
    print(f"  검색량 {MIN_SEARCH_VOLUME:,} 이상 키워드: {len(warehouse_vol)}개")

    conversion_kws = [kw for kw in warehouse_vol if kw["is_conversion"]]
    potential_kws = [kw for kw in all_warehouse if not kw["is_conversion"]]
    print(f"  전환 키워드 풀: {len(conversion_kws)}개")
    print(f"  잠재 키워드 풀: {len(potential_kws)}개")

    num_products = len(selected_products)

    # ── PASS 0: 사전 확정 키워드 처리 ──
    pre_results = []
    if pre_assignments:
        print(f"\n  사전 확정 키워드 {len(pre_assignments)}건 처리 중...")
        for pa in pre_assignments:
            kw_text = pa["keyword"]
            nk = norm_keyword(kw_text)

            # 키워드 창고에서 매칭
            matched = None
            for wk in all_warehouse:
                if norm_keyword(wk["keyword"]) == nk:
                    matched = wk
                    break

            if not matched:
                # 창고에 없으면 기본 정보로 생성
                matched = {
                    "product": "",
                    "keyword": kw_text,
                    "search_vol": 0,
                    "avg_amount": 0,
                    "is_conversion": False,
                }

            writer = pa["writer"]
            if not writer:
                # 자동 배정: 배정 건수 가장 많이 남은 작가에게
                remaining = {
                    w: writers_quota[w] - sum(1 for a in pre_results if a["writer"] == w)
                    for w in writers_quota if writers_quota[w] > 0
                }
                writer = max(remaining, key=remaining.get) if remaining else None

            if writer:
                used_norms.add(nk)
                kw_type = "전환" if matched["is_conversion"] else "고잠재"
                pre_results.append({
                    **matched,
                    "keyword": kw_text,
                    "writer": writer,
                    "type": kw_type,
                    "score": calc_conversion_score(matched) if not matched["is_conversion"] else "",
                    "reason": "사전 확정",
                })
                print(f"    {writer} ← {kw_text} ({kw_type})")

    # 사전 확정분 반영하여 남은 건수 계산
    writer_remaining = {}
    for writer, max_count in writers_quota.items():
        pre_count = sum(1 for a in pre_results if a["writer"] == writer)
        writer_remaining[writer] = max(max_count - pre_count, 0)

    # ── 전체 총합 기준으로 전환/잠재 건수 계산 ──
    total_remaining = sum(writer_remaining.values())
    total_pot = math.ceil(total_remaining * 0.3)
    total_conv = total_remaining - total_pot
    print(f"\n  총 배정: {total_remaining}건 (전환 {total_conv}건 + 잠재 {total_pot}건)")

    # ── PASS 1: 전환 키워드 배정 (각 작가 quota만큼 전환 우선 배정) ──
    conv_assignments = []
    active_list = [(w, r) for w, r in writer_remaining.items() if r > 0]

    # 먼저 각 작가에게 quota 전체를 전환으로 배정 시도
    for writer, cap in active_list:
        # ★ 작가별 효율 순으로 제품 정렬 (전환금액 합계 기준)
        amounts = writer_amounts.get(writer, {})
        product_efficiency = []
        for product in selected_products:
            amt_list = amounts.get(product, [])
            total_amt = sum(amt_list) if amt_list else 0
            product_efficiency.append((product, total_amt))
        product_efficiency.sort(key=lambda x: x[1], reverse=True)
        sorted_products = [p for p, _ in product_efficiency]

        eff_str = ", ".join(
            f"{p}({int(a):,}원)" for p, a in product_efficiency if a > 0
        )
        if eff_str:
            print(f"  [{writer}] 효율 순서: {eff_str}")

        # 제품별 균등 배분 (cap 초과 방지)
        per_product = cap // num_products if num_products <= cap else 0
        remainder_slots = cap - per_product * num_products

        writer_conv = []
        for pi, product in enumerate(sorted_products):
            if len(writer_conv) >= cap:
                break
            target = per_product + (1 if pi < remainder_slots else 0)
            target = min(target, cap - len(writer_conv))

            scored = []
            for kw in conversion_kws:
                if kw["product"] != product:
                    continue
                if norm_keyword(kw["keyword"]) in used_norms:
                    continue
                if norm_keyword(kw["keyword"]) in existing_assignments:
                    continue
                scored.append((kw["avg_amount"], kw))

            scored.sort(key=lambda x: x[0], reverse=True)
            for _, kw in scored[:target]:
                used_norms.add(norm_keyword(kw["keyword"]))
                writer_conv.append({
                    **kw,
                    "writer": writer,
                    "type": "전환",
                    "score": "",
                    "reason": generate_reason(kw, True),
                })

        # 제품별로 부족하면 다른 제품에서 채우기 (cap 한도 내)
        if len(writer_conv) < cap:
            need = cap - len(writer_conv)
            extra = []
            for kw in conversion_kws:
                if norm_keyword(kw["keyword"]) in used_norms:
                    continue
                if norm_keyword(kw["keyword"]) in existing_assignments:
                    continue
                extra.append((kw["avg_amount"], kw))
            extra.sort(key=lambda x: x[0], reverse=True)
            for _, kw in extra[:need]:
                used_norms.add(norm_keyword(kw["keyword"]))
                writer_conv.append({
                    **kw,
                    "writer": writer,
                    "type": "전환",
                    "score": "",
                    "reason": generate_reason(kw, True),
                })

        conv_assignments.extend(writer_conv)

    # ── PASS 2: 잠재 키워드 (전체 30%만큼 전환 슬롯을 잠재로 교체) ──
    # 잠재 키워드 후보 준비
    pot_assignments = []
    all_scored_pot = []

    for kw in potential_kws:
        if norm_keyword(kw["keyword"]) in used_norms:
            continue
        if norm_keyword(kw["keyword"]) in existing_assignments:
            continue
        score = calc_conversion_score(kw)
        all_scored_pot.append((score, kw))

    all_scored_pot.sort(key=lambda x: x[0], reverse=True)

    # 전환 배정 중 뒤쪽(전환금액 낮은 순)부터 잠재로 교체
    # quota가 큰 작가부터 잠재 슬롯 배분 (quota 큰 작가에 여유가 더 많음)
    writer_conv_counts = defaultdict(int)
    for a in conv_assignments:
        writer_conv_counts[a["writer"]] += 1

    writer_pot_needs = {}
    pot_left = total_pot
    # quota 큰 작가 순으로 잠재 슬롯 배분
    sorted_writers = sorted(active_list, key=lambda x: x[1], reverse=True)
    for writer, cap in sorted_writers:
        if pot_left <= 0:
            break
        conv_count = writer_conv_counts.get(writer, 0)
        if conv_count <= 0:
            continue
        # 이 작가에서 잠재로 교체할 건수 (최소 1건 전환은 남겨둠)
        max_replace = conv_count - 1 if conv_count > 1 else 0
        give = min(max_replace, pot_left)
        if give > 0:
            writer_pot_needs[writer] = give
            pot_left -= give

    # 아직 잠재 건수가 남았으면 빈 슬롯 있는 작가에게 추가
    if pot_left > 0:
        for writer, cap in sorted_writers:
            if pot_left <= 0:
                break
            filled = writer_conv_counts.get(writer, 0)
            empty_slots = cap - filled
            if empty_slots > 0:
                give = min(empty_slots, pot_left)
                writer_pot_needs[writer] = writer_pot_needs.get(writer, 0) + give
                pot_left -= give

    # 잠재로 교체할 작가의 전환 키워드 중 뒤쪽(전환금액 낮은 순)부터 제거
    for writer, pot_count in writer_pot_needs.items():
        # 이 작가의 전환 키워드를 전환금액 오름차순 정렬 → 낮은 것부터 제거
        writer_convs = [(i, a) for i, a in enumerate(conv_assignments) if a["writer"] == writer]
        writer_convs.sort(key=lambda x: x[1]["avg_amount"])
        remove_count = pot_count
        remove_indices = set()
        for idx, a in writer_convs:
            if remove_count <= 0:
                break
            remove_indices.add(idx)
            used_norms.discard(norm_keyword(a["keyword"]))
            remove_count -= 1
        conv_assignments = [a for i, a in enumerate(conv_assignments) if i not in remove_indices]

    print(f"  잠재 배정 계획: {', '.join(f'{w}({n}건)' for w, n in writer_pot_needs.items())}")

    # 잠재 키워드를 제품별 균등하게 뽑기
    pot_pool_used = set()
    writer_pot_candidates = {}

    # 제품별 균등: total_pot을 제품 수로 나눔
    pot_per_product = max(total_pot // num_products, 1)
    pot_product_remainder = total_pot - pot_per_product * num_products

    # 먼저 제품별로 균등하게 후보 뽑기
    product_pot_picks = []
    for pi, product in enumerate(selected_products):
        target = pot_per_product + (1 if pi < pot_product_remainder else 0)
        count = 0
        for score, kw in all_scored_pot:
            if kw["product"] != product:
                continue
            if norm_keyword(kw["keyword"]) in pot_pool_used:
                continue
            if count >= target:
                break
            product_pot_picks.append((score, kw))
            pot_pool_used.add(norm_keyword(kw["keyword"]))
            count += 1

    # 부족하면 제품 무관하게 채우기
    if len(product_pot_picks) < total_pot:
        for score, kw in all_scored_pot:
            if norm_keyword(kw["keyword"]) in pot_pool_used:
                continue
            if len(product_pot_picks) >= total_pot:
                break
            product_pot_picks.append((score, kw))
            pot_pool_used.add(norm_keyword(kw["keyword"]))

    # 뽑힌 잠재 키워드를 작가별로 배분
    pick_iter = iter(product_pot_picks)
    for writer, needed in writer_pot_needs.items():
        picks = []
        for _ in range(needed):
            try:
                picks.append(next(pick_iter))
            except StopIteration:
                break
        writer_pot_candidates[writer] = picks

    # ── 잠재 키워드 미리보기 (전체 작가 한번에) ──
    remaining_pot = [
        (s, k) for s, k in all_scored_pot
        if norm_keyword(k["keyword"]) not in pot_pool_used
    ]
    writer_pot_candidates = review_all_potential_keywords(
        writer_pot_candidates, remaining_pot, writer_pot_needs
    )

    # 잠재 키워드 확정
    for writer, candidates in writer_pot_candidates.items():
        for score, kw in candidates:
            used_norms.add(norm_keyword(kw["keyword"]))
            pot_assignments.append({
                **kw,
                "writer": writer,
                "type": "고잠재",
                "score": calc_conversion_score(kw),
                "reason": generate_reason(kw, False),
            })

    # ── 합치기 + 작가별 오름차순 정렬 ──
    assignments = pre_results + conv_assignments + pot_assignments
    assignments.sort(key=lambda a: a["writer"])

    # 결과 요약
    for writer in sorted(writers_quota.keys()):
        w_conv = sum(1 for a in assignments if a["writer"] == writer and a["type"] == "전환")
        w_pot = sum(1 for a in assignments if a["writer"] == writer and a["type"] == "고잠재")
        if w_conv + w_pot > 0:
            print(f"  [{writer}] 전환 {w_conv}건 + 잠재 {w_pot}건 = {w_conv + w_pot}건")

    return assignments


# ━━━━━━━━━━━━━━━━━━━━ 시트에 기록 ━━━━━━━━━━━━━━━━━━━━
def write_assignments(ws, assignments):
    """키워드 배정 탭에 결과 추가"""
    existing = ws.get_all_values()
    start_row = len(existing) + 1

    today_str = datetime.now().strftime("%Y-%m-%d")

    # 네이버 자동완성으로 띄어쓰기 보정
    all_kws = list(set(a["keyword"] for a in assignments))
    print(f"\n[네이버 자동완성] 띄어쓰기 보정 중... ({len(all_kws)}개)")
    spacing_map = batch_naver_spacing(all_kws)
    for orig, spaced in spacing_map.items():
        if orig != spaced:
            print(f"  {orig} → {spaced}")

    print(f"\n[네이버 검색] 스마트블록/인기글 체크 중...")
    rows = []
    for i, a in enumerate(assignments):
        # 띄어쓰기 보정된 키워드 사용
        spaced_kw = spacing_map.get(a["keyword"], a["keyword"])

        # 네이버 검색으로 스마트블록 확인
        smart, smart_title = check_naver_blog_blocks(spaced_kw)
        time.sleep(0.3)

        vol_str = f"{a['search_vol']:,}" if a["search_vol"] else ""
        amt_str = f"{int(a['avg_amount']):,}원" if a["avg_amount"] else ""
        score_str = str(a["score"]) if a["score"] else ""

        rows.append([
            today_str,
            a["writer"],
            a["product"],
            spaced_kw,
            a["type"],
            vol_str,
            amt_str,
            score_str,
            a["reason"],
            smart,
            smart_title,
        ])

        print(f"  {i+1}/{len(assignments)} {a['writer']} ← {spaced_kw} "
              f"({a['type']}) [스마트블록:{smart}] {smart_title}")

    if rows:
        end_row = start_row + len(rows) - 1
        ws.update(range_name=f"A{start_row}:K{end_row}", values=rows)
        print(f"\n[시트] {len(rows)}건 기록 완료")


# ━━━━━━━━━━━━━━━━━━━━ 메인 ━━━━━━━━━━━━━━━━━━━━
def main():
    print("=" * 60)
    print("  키워드 배정 프로그램")
    print("=" * 60)

    # 1) 시트 연결
    print("\n[1/7] Google Sheets 연결 중...")
    spreadsheet = connect_spreadsheet()

    # 2) 키워드 창고 초기화: 전환 키워드 외 삭제 → 시트1에서 다시 넣기
    print("[2/7] 키워드 창고 초기화 (전환 키워드 유지 + 시트1 재입력)...")
    total_kws = refresh_warehouse_from_sheet1(spreadsheet)

    # 3) 오늘 작가별 건수 확인
    print("[3/7] 원고 작성 건수 확인 중...")
    quotas = get_today_quotas(spreadsheet)

    today = datetime.now()
    print(f"\n  오늘 날짜: {today.strftime('%Y-%m-%d')} ({today.month}/{today.day})")
    print(f"\n  {'작가명':<10} {'건수':>5}")
    print(f"  {'─' * 20}")
    for writer, count in quotas.items():
        print(f"  {writer:<10} {count:>5}건")

    # 3) 배정 건수 입력
    print(f"\n{'─' * 60}")
    print("  작가별로 배정 건수를 다르게 설정하시겠습니까?")
    diff_input = input("  → (y/n, 엔터=n): ").strip().lower()

    final_quotas = {}
    if diff_input in ("y", "yes"):
        # 작가별 개별 건수 입력
        print(f"\n  각 작가별 배정 건수를 입력하세요 (엔터=시트 건수 그대로)")
        for writer in sorted(quotas.keys()):
            sheet_count = quotas[writer]
            if sheet_count <= 0:
                continue
            w_input = input(f"    {writer} (시트: {sheet_count}건) → ").strip()
            if w_input:
                try:
                    final_quotas[writer] = max(int(w_input), 0)
                except ValueError:
                    print(f"      숫자 오류. 시트 건수({sheet_count}건) 유지.")
                    final_quotas[writer] = sheet_count
            else:
                final_quotas[writer] = sheet_count
        # 0건 작가 제외
        final_quotas = {w: q for w, q in final_quotas.items() if q > 0}
    else:
        # 기존 방식: 전체 공통 최대 건수
        user_input = input("  오늘 작가당 최대 배정 건수를 입력하세요 (엔터=제한없음): ").strip()
        max_cap = None
        if user_input:
            try:
                max_cap = int(user_input)
                print(f"  → 최대 {max_cap}건 제한 적용")
            except ValueError:
                print("  → 숫자가 아닙니다. 제한 없이 적용합니다.")

        for writer, sheet_count in quotas.items():
            if sheet_count <= 0:
                continue
            if max_cap is not None and sheet_count > max_cap:
                final_quotas[writer] = max_cap
            else:
                final_quotas[writer] = sheet_count
    print(f"{'─' * 60}")

    # 적용 결과 표시
    print(f"\n  {'작가명':<10} {'시트건수':>6} {'배정건수':>8}")
    print(f"  {'─' * 28}")
    for writer in final_quotas:
        print(f"  {writer:<10} {quotas[writer]:>5}건 → {final_quotas[writer]:>5}건")

    active_writers = {w: c for w, c in final_quotas.items() if c > 0}
    if not active_writers:
        print("\n배정할 작가가 없습니다.")
        return

    total = sum(active_writers.values())
    print(f"\n  → 총 {len(active_writers)}명, {total}건 배정 예정")

    # 4) 데이터 수집
    print("\n[4/8] 키워드 창고 읽는 중...")
    warehouse = get_keyword_warehouse(spreadsheet)
    conv_count = sum(1 for k in warehouse if k["is_conversion"])
    pot_count = len(warehouse) - conv_count
    vol_ok = sum(1 for k in warehouse if k["search_vol"] >= MIN_SEARCH_VOLUME)
    print(f"  전환 키워드: {conv_count}개, 잠재 키워드: {pot_count}개")
    print(f"  검색량 {MIN_SEARCH_VOLUME:,} 이상: {vol_ok}개")

    # 5) 사전 확정 키워드 입력
    print("\n[5/9] 사전 확정 키워드...")
    pre_assignments = get_pre_assignments(active_writers)

    # 6) 오늘 배정할 제품 선택
    print("\n[6/9] 제품 선택...")
    selected_products = select_today_products(warehouse)

    print("[7/9] 작가 전문 분야 파악 중...")
    writer_specialties, writer_amounts = get_writer_specialties(spreadsheet)
    for writer in active_writers:
        if writer in writer_specialties:
            top = sorted(writer_specialties[writer].items(), key=lambda x: x[1], reverse=True)[:3]
            products_str = ", ".join(f"{p}({c}건)" for p, c in top)
            print(f"  {writer}: {products_str}")

    print("[8/9] 기존 배정 확인 (2주 중복 방지)...")
    existing_assignments, assign_ws = get_existing_assignments(spreadsheet)
    print(f"  최근 2주 배정: {len(existing_assignments)}건")

    # 7) 키워드 배정
    print("\n[9/9] 키워드 배정 중...")
    assignments = assign_keywords(
        active_writers, warehouse, writer_specialties, writer_amounts,
        existing_assignments, selected_products, pre_assignments
    )

    if not assignments:
        print("\n배정할 키워드가 없습니다.")
        return

    # 배정 결과 미리보기
    print(f"\n{'=' * 80}")
    print(f"  배정 결과 미리보기")
    print(f"{'=' * 80}")
    print(f"  {'작가명':<8} {'제품':<12} {'키워드':<25} {'구분':<6} {'검색량':>8}")
    print(f"  {'─' * 70}")
    for a in assignments:
        vol_str = f"{a['search_vol']:,}" if a["search_vol"] else "-"
        print(f"  {a['writer']:<8} {a['product']:<12} {a['keyword']:<25} "
              f"{a['type']:<6} {vol_str:>8}")

    # 확인
    confirm = input(f"\n  총 {len(assignments)}건을 시트에 기록하시겠습니까? (y/n): ").strip().lower()
    if confirm != "y":
        print("  취소되었습니다.")
        return

    # 6) 시트에 기록
    write_assignments(assign_ws, assignments)

    print(f"\n{'=' * 60}")
    print(f"  완료! 총 {len(assignments)}건 배정")
    print("=" * 60)


if __name__ == "__main__":
    main()
