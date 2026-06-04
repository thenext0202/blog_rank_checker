# -*- coding: utf-8 -*-
"""네이버 SERP 블록 분류 + 날짜 추출/환산 + 셀 포맷."""
import re
from datetime import date, timedelta

# 날짜 토큰: 상대형(N초/분/시간/일/주/개월 전, 어제/그제) + 절대형(YYYY.MM.DD)
DATE_RE = re.compile(
    r'(\d+초 전|\d+분 전|\d+시간 전|\d+일 전|\d+주 전|\d+개월 전|어제|그제|\d{4}\.\d{2}\.\d{2}\.?)'
)


def extract_dates(text):
    """유닛 텍스트에서 날짜 토큰을 등장 순서대로 모두 추출(중복 허용 = 글 수 반영)."""
    return DATE_RE.findall(text or "")


def normalize_date(token, today):
    """날짜 토큰을 date 객체로 환산. 상대형은 today 기준. 개월은 30일 근사."""
    token = token.strip()
    # 절대형 YYYY.MM.DD
    m = re.match(r'(\d{4})\.(\d{2})\.(\d{2})', token)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if token == "어제":
        return today - timedelta(days=1)
    if token == "그제":
        return today - timedelta(days=2)
    m = re.match(r'(\d+)(초|분|시간|일|주|개월) 전', token)
    if m:
        n = int(m.group(1)); unit = m.group(2)
        if unit in ("초", "분", "시간"):
            return today  # 당일
        if unit == "일":
            return today - timedelta(days=n)
        if unit == "주":
            return today - timedelta(days=7 * n)
        if unit == "개월":
            return today - timedelta(days=30 * n)
    return today  # 해석 불가 시 당일로 폴백(드묾)


# 블로그 계열 아님 — 제외 헤더 키워드
EXCLUDE = [
    '광고', '가격비교', '플러스 스토어', '네이버 클립', '함께 많이 찾는', 'AI 브리핑',
    '인플루언서', '지식백과', '이미지', '동영상', '관련 브랜드 콘텐츠', '뉴스', '지식iN',
    '나무위키', '위키백과', 'www.', '.com', '.go.kr', '.org', '건강 소식',
]

def _is_excluded(header):
    return any(x in header for x in EXCLUDE)

def classify(unit, n_posts):
    """유닛 → (종류, 헤더) 또는 None.
    n_posts = 유닛 안 날짜 토큰 수 ≈ 묶인 글 수. 2개 이상이면 묶음 블록.
    """
    h = unit["header"]
    if unit["blog"] == 0 and unit["cafe"] == 0:
        return None
    if _is_excluded(h):
        return None
    grouped = n_posts >= 2
    # 인기글: _fe_view_root + "인기글"로 끝남 + 묶음
    if unit["fe_view"] and h.endswith("인기글") and grouped:
        return ("인기글", h)
    # 스블: 그 외 묶음 블록
    if grouped:
        return ("스블", h)
    # 낱개 글: 블로그면 통검블로그 (카페 낱개는 블로그계열 아님 → 제외)
    if unit["blog"] > 0:
        return ("통검블로그", h)
    return None


def _fmt_one_date(d, today):
    """올해면 MM.DD, 다른 해면 YYYY.MM.DD."""
    if d.year == today.year:
        return d.strftime("%m.%d")
    return d.strftime("%Y.%m.%d")

def _dates_str(dates, today):
    """date 리스트 → '3건: 06.03, 05.28, 2025.09.18' (최신순)."""
    ds = sorted(dates, reverse=True)
    joined = ", ".join(_fmt_one_date(d, today) for d in ds)
    return f"{len(ds)}건: {joined}"

def fmt_popular(blocks, today):
    """인기글 → (flag, 날짜문자열). blocks는 보통 0~1개."""
    if not blocks:
        return ("❌", "")
    header = blocks[0]["header"]
    field = header[:-len("인기글")].strip() if header != "인기글" else ""
    flag = f"✅ {field}" if field else "✅"
    all_dates = [d for b in blocks for d in b["dates"]]
    return (flag, _dates_str(all_dates, today))

def fmt_smartblock(blocks, today):
    """스블 → (flag, 블록별 줄바꿈 텍스트)."""
    if not blocks:
        return ("❌", "")
    lines = []
    for b in blocks:
        ds = sorted(b["dates"], reverse=True)
        joined = ", ".join(_fmt_one_date(d, today) for d in ds)
        lines.append(f"{b['header']}({len(ds)}): {joined}")
    return (f"✅ {len(blocks)}블록", "\n".join(lines))

def fmt_general(blocks, today):
    """통검블로그 낱개 → (flag, 날짜문자열). 블록 1개 = 글 1개."""
    if not blocks:
        return ("❌", "")
    all_dates = [d for b in blocks for d in b["dates"]]
    return (f"✅ {len(blocks)}건", _dates_str(all_dates, today))


import time, urllib.parse
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

# main_pack 전체에서 섹션박스 넓게 수집 + 조상 중복 제거(낱개 글은 각자 유닛 유지)
UNITS_JS = r"""
var pack=document.getElementById('main_pack')||document.body;
var nodes=pack.querySelectorAll('section, div.api_subject_bx, div[class*="sc_"], div[class*="fds-"]');
var out=[], seen=new Set();
function header(el){var h=el.querySelector('h2,h3,.api_title,[class*="title"]');
  return h?h.textContent.trim().replace(/\s+/g,' ').slice(0,45):'';}
for(var i=0;i<nodes.length;i++){var el=nodes[i];
  var skip=false,p=el.parentElement;
  while(p){if(seen.has(p)){skip=true;break;}p=p.parentElement;}
  if(skip)continue;
  var blog=el.querySelectorAll('a[href*="blog.naver.com"]').length;
  var cafe=el.querySelectorAll('a[href*="cafe.naver.com"]').length;
  var h=header(el);
  if(!h && blog===0 && cafe===0)continue;
  seen.add(el);
  out.push({header:h, fe_view:((el.className||'').indexOf('_fe_view_root')>=0),
            blog:blog, cafe:cafe, text:(el.innerText||'').slice(0,5000)});
}
return out;
"""

def create_driver():
    """headless Chrome (자동화 탐지 우회) — 순위체커 패턴 재사용."""
    opts = Options()
    for a in ["--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
              "--disable-gpu", "--window-size=1920,1080",
              "--disable-blink-features=AutomationControlled"]:
        opts.add_argument(a)
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
    import os
    chrome_bin = os.environ.get("CHROME_BIN")
    if chrome_bin:
        opts.binary_location = chrome_bin
        driver = webdriver.Chrome(options=opts)
    else:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"})
    driver.implicitly_wait(5)
    return driver

def capture_units(driver, keyword):
    """키워드 PC 검색결과 렌더링 후 유닛 리스트 반환."""
    driver.get("https://search.naver.com/search.naver?query=" + urllib.parse.quote(keyword))
    time.sleep(3)
    for _ in range(6):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1.0)
    return driver.execute_script(UNITS_JS) or []

def parse_keyword(driver, keyword, today):
    """키워드 1개 → {'인기글':[{header,dates}], '스블':[...], '통검블로그':[...]}.
    dates는 정규화된 date 객체 리스트."""
    units = capture_units(driver, keyword)
    result = {"인기글": [], "스블": [], "통검블로그": []}
    for u in units:
        raw = extract_dates(u["text"])
        c = classify(u, len(raw))
        if not c:
            continue
        kind, header = c
        dates = [normalize_date(t, today) for t in raw]
        result[kind].append({"header": header, "dates": dates})
    return result
