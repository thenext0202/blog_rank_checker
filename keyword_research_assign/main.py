#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
keyword_research/main.py - 키워드 연관검색어 리서치

시드 키워드별로 구글/다음/네이버 연관검색어를 수집하고
네이버 검색광고 API로 검색량을 조회하여 시트에 기록합니다.

시트 구조:
  A: 제품명 | B: 시드 키워드 | C: 추천 키워드 | D: 출처 | E: 검색량
"""

import os
import sys
import time
import json
import hmac
import hashlib
import base64
import urllib.parse
import urllib.request
import gspread
from google.oauth2.service_account import Credentials

# ━━━━━━━━━━━━━━━━━━━━ 설정 ━━━━━━━━━━━━━━━━━━━━
NAVER_API_KEY     = os.environ.get("NAVER_API_KEY", "010000000061419c77434a47cc8ed45e1f410e7af57bc5873ffe2606c36b734b701d7d6c95")
NAVER_SECRET_KEY  = os.environ.get("NAVER_SECRET_KEY", "AQAAAABhQZx3Q0pHzI7UXh9BDnr1Qon+MpR9eV8dvINigfkudg==")
NAVER_CUSTOMER_ID = os.environ.get("NAVER_CUSTOMER_ID", "2120690")

SPREADSHEET_ID = "1xJAogt0alaQ8A5OctxltPaF3kg_0PFSF5Z0ePxMw3tY"
SHEET_NAME     = "연관 검색어"
def _base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

CRED_FILE      = os.path.join(_base_dir(), "credentials.json")

MIN_VOLUME = 500


# ━━━━━━━━━━━━━━━━━━━━ 시트 연결 ━━━━━━━━━━━━━━━━━━━━
def connect_sheet():
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
    return gc.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)


def read_seeds_from_sheet(ws):
    """시트 A열(제품명) + B열(시드 키워드) 읽어오기"""
    rows = ws.get_all_values()
    pairs = []
    seen = set()
    for row in rows[1:]:
        product = row[0].strip() if len(row) > 0 else ""
        kw = row[1].strip() if len(row) > 1 else ""
        if not kw or kw in seen:
            continue
        seen.add(kw)
        pairs.append((product, kw))
    print(f"[시트] {len(pairs)}개 제품-키워드 쌍 읽음:")
    for prod, kw in pairs:
        print(f"  {prod} → {kw}")
    return pairs, [kw for _, kw in pairs]


def write_results_to_sheet(ws, pairs, results_by_seed):
    """시트에 결과 쓰기: A=제품명, B=시드, C=추천키워드, D=출처, E=검색량"""
    seed_to_product = {kw: prod for prod, kw in pairs}

    # 기존 데이터 클리어
    rows = ws.get_all_values()
    total_rows = len(rows)
    if total_rows > 1:
        ws.batch_clear([f"A2:E{total_rows + 500}"])

    # 헤더
    ws.update(range_name="A1:E1", values=[["제품명", "시드 키워드", "추천 키워드", "출처", "검색량"]])

    # 행 데이터 조립 (시드별 묶음)
    data_rows = []
    for seed, items in results_by_seed.items():
        product = seed_to_product.get(seed, "")
        for item in items:
            data_rows.append([
                product, seed, item["keyword"], item["source"], item.get("volume", "")
            ])

    if not data_rows:
        print("[시트] 쓸 결과가 없습니다.")
        return

    end_row = len(data_rows) + 1
    ws.update(range_name=f"A2:E{end_row}", values=data_rows)
    print(f"[시트] {len(data_rows)}개 행 기록 완료")


# ━━━━━━━━━━━━━━━━━━━━ 연관검색어 수집 ━━━━━━━━━━━━━━━━━━━━
def get_google_suggestions(keyword):
    """구글 자동완성 연관검색어"""
    try:
        q = urllib.parse.quote(keyword)
        url = f"https://suggestqueries.google.com/complete/search?client=firefox&hl=ko&q={q}"
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "Mozilla/5.0")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data[1] if len(data) > 1 else []
    except Exception as e:
        print(f"  [구글] 오류: {e}")
        return []


def get_naver_suggestions(keyword):
    """네이버 자동완성 + 연관검색어"""
    import re
    results = []
    seen = set()

    # 1) 자동완성
    try:
        q = urllib.parse.quote(keyword)
        url = (f"https://ac.search.naver.com/nx/ac?q={q}&q_enc=UTF-8"
               f"&st=100&frm=nv&r_format=json&r_enc=UTF-8&r_unicode=0"
               f"&t_koreng=1&ans=2&run=2&rev=4&con=1")
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "Mozilla/5.0")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for group in data.get("items", []):
            for pair in group:
                if isinstance(pair, list) and len(pair) > 0:
                    kw = pair[0].strip()
                    if kw and kw not in seen:
                        seen.add(kw)
                        results.append(kw)
    except Exception as e:
        print(f"  [네이버 자동완성] 오류: {e}")

    # 2) 검색 페이지 연관검색어
    try:
        q = urllib.parse.quote(keyword)
        url = f"https://search.naver.com/search.naver?where=nexearch&query={q}"
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8")
        idx = html.find("_related_keywords")
        if idx >= 0:
            section = html[idx:idx + 5000]
            matches = re.findall(r'<div class="tit">([^<]+)</div>', section)
            for kw in matches:
                kw = kw.strip()
                if kw and kw not in seen:
                    seen.add(kw)
                    results.append(kw)
    except Exception as e:
        print(f"  [네이버 연관검색어] 오류: {e}")

    return results


def get_daum_suggestions(keyword):
    """다음 연관검색어 (검색 페이지에서 수집)"""
    import re
    try:
        q = urllib.parse.quote(keyword)
        url = f"https://search.daum.net/search?w=tot&q={q}"
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8")
        matches = re.findall(r'class="keyword"[^>]*>([^<]+)<', html)
        # 중복 제거 (상단/하단 동일 블록)
        seen = set()
        results = []
        for kw in matches:
            kw = kw.strip()
            if kw and kw not in seen:
                seen.add(kw)
                results.append(kw)
        return results
    except Exception as e:
        print(f"  [다음] 오류: {e}")
        return []


# ━━━━━━━━━━━━━━━━━━━━ 검색량 조회 ━━━━━━━━━━━━━━━━━━━━
def generate_signature(timestamp, method, path):
    message = f"{timestamp}.{method}.{path}"
    sign = hmac.new(
        NAVER_SECRET_KEY.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(sign).decode("utf-8")


def call_keyword_api(seeds):
    """네이버 검색광고 API로 검색량 조회"""
    if not (NAVER_API_KEY and NAVER_SECRET_KEY and NAVER_CUSTOMER_ID):
        print("[오류] 네이버 API 환경변수가 설정되지 않았습니다.")
        return {}

    path = "/keywordstool"
    timestamp = str(int(time.time() * 1000))
    signature = generate_signature(timestamp, "GET", path)

    params = urllib.parse.urlencode({
        "hintKeywords": ",".join(s.replace(" ", "") for s in seeds),
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
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"[오류] API 호출 실패: {e} / {body}")
        return {}
    except Exception as e:
        print(f"[오류] API 호출 실패: {e}")
        return {}

    volume_map = {}
    for item in data.get("keywordList", []):
        kw = item.get("relKeyword", "")
        pc = item.get("monthlyPcQcCnt", 0)
        mo = item.get("monthlyMobileQcCnt", 0)
        if isinstance(pc, str):
            pc = 0
        if isinstance(mo, str):
            mo = 0
        volume_map[kw] = int(pc) + int(mo)

    return volume_map


# ━━━━━━━━━━━━━━━━━━━━ 메인 리서치 ━━━━━━━━━━━━━━━━━━━━
def run_research(seed_keywords):
    print("=" * 60)
    print("  키워드 연관검색어 리서치")
    print("=" * 60)
    print(f"\n  시드 키워드: {', '.join(seed_keywords)}")

    results_by_seed = {}

    for seed in seed_keywords:
        print(f"\n{'─' * 60}")
        print(f"  [{seed}] 연관검색어 수집")
        print(f"{'─' * 60}")

        # 1) 구글/다음/네이버 연관검색어 수집
        google_kws = get_google_suggestions(seed)
        print(f"  구글: {len(google_kws)}개")

        time.sleep(0.3)
        daum_kws = get_daum_suggestions(seed)
        print(f"  다음: {len(daum_kws)}개")

        time.sleep(0.3)
        naver_kws = get_naver_suggestions(seed)
        print(f"  네이버: {len(naver_kws)}개")

        # 2) 검색량 조회 (네이버 검색광고 API)
        time.sleep(0.3)
        print(f"  검색량 조회 중...")
        volume_map = call_keyword_api([seed])

        # 3) 네이버 검색광고 API 연관 키워드 중 시드 포함된 것 추가
        seed_norm = seed.lower().replace(" ", "")
        api_kws = []
        for kw in volume_map:
            if seed_norm in kw.lower().replace(" ", ""):
                api_kws.append(kw)
        print(f"  네이버 검색광고 API: {len(api_kws)}개 (시드 포함)")

        # 4) 전체 연관검색어 모으기 (중복 제거)
        all_kws = []
        seen = set()
        for source, kws in [("구글 연관검색어", google_kws),
                            ("다음 연관검색어", daum_kws),
                            ("네이버 연관검색어", naver_kws),
                            ("네이버 검색광고", api_kws)]:
            for kw in kws:
                kw = kw.strip()
                if not kw or kw in seen:
                    continue
                seen.add(kw)
                all_kws.append((kw, source))

        # 5) 검색량 없는 키워드 추가 조회 (5개씩 배치)
        missing = [kw for kw, _ in all_kws
                   if kw not in volume_map and kw.replace(" ", "") not in volume_map]
        if missing:
            for i in range(0, len(missing), 5):
                batch = missing[i:i+5]
                extra = call_keyword_api(batch)
                volume_map.update(extra)
                time.sleep(0.3)

        # 검색량 룩업 (공백 제거 버전도 매핑)
        vol_lookup = {}
        for k, v in volume_map.items():
            vol_lookup[k] = v
            vol_lookup[k.replace(" ", "")] = v

        # 6) 결과 조립
        items = []
        for kw, source in all_kws:
            vol = vol_lookup.get(kw, vol_lookup.get(kw.replace(" ", ""), ""))
            items.append({"keyword": kw, "source": source, "volume": vol})

        results_by_seed[seed] = items

        # 콘솔 출력
        print(f"\n  {'키워드':<30} {'출처':<15} {'검색량':>8}")
        print(f"  {'─' * 55}")
        for item in items:
            vol_str = f"{item['volume']:>8,}" if isinstance(item['volume'], int) else f"{'':>8}"
            print(f"  {item['keyword']:<30} {item['source']:<15} {vol_str}")

        print(f"  → 총 {len(items)}개")

        if len(seed_keywords) > 1:
            time.sleep(0.5)

    # 총계
    total = sum(len(v) for v in results_by_seed.values())
    print(f"\n{'=' * 60}")
    print(f"  완료! 총 {total}개 연관검색어 수집")
    print("=" * 60)

    return results_by_seed


# ━━━━━━━━━━━━━━━━━━━━ 실행 ━━━━━━━━━━━━━━━━━━━━
if __name__ == "__main__":
    use_sheet = False

    if len(sys.argv) >= 2 and sys.argv[1] == "--file":
        filepath = sys.argv[2] if len(sys.argv) > 2 else "seeds.txt"
        with open(filepath, "r", encoding="utf-8") as f:
            seeds = [line.strip() for line in f if line.strip()]
    elif len(sys.argv) >= 2:
        seeds = sys.argv[1:]
    else:
        use_sheet = True

    if use_sheet:
        print("[시트] Google Sheets 연결 중...")
        ws = connect_sheet()
        pairs, seeds = read_seeds_from_sheet(ws)

    if not seeds:
        print("키워드가 없습니다.")
        input("\n엔터를 눌러 종료...")
        sys.exit(1)

    results_by_seed = run_research(seeds)

    if use_sheet:
        write_results_to_sheet(ws, pairs, results_by_seed)

    input("\n 엔터를 눌러 종료...")
