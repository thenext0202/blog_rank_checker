# 네이버 블록 체커 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 키워드별 네이버 SERP에서 인기글/스마트블록/통검블로그 블록을 분류하고 각 블록 글들의 발행일을 공통시트 `블록 체커` 탭에 기록한다.

**Architecture:** Selenium으로 PC 검색결과를 렌더링·캡처(`serp_parser`) → 순수함수로 블록 분류·날짜 환산·셀 포맷 → `sheets`가 `블록 체커` 탭에만 기록(기존 24개 탭 불가침) → `main`이 체크박스 트리거로 오케스트레이션. 분류 로직은 캡처 5건으로 검증 완료(`순위체커/_diag_*`).

**Tech Stack:** Python 3.14, selenium 4.40, webdriver_manager, gspread, google-auth, pytest

---

## 파일 구조

```
블로그 블록 체커/
├── main.py            # 실행 흐름 (1회/감시), CLI
├── sheets.py          # 블록 체커 탭 연결·읽기·기록 (gspread)
├── serp_parser.py     # 캡처 JS + 분류/날짜/셀포맷 (순수함수 + Selenium)
├── config.json        # SHEET_ID, TAB_NAME, 크레덴셜 경로
└── tests/
    └── test_serp_parser.py   # 순수함수 단위 테스트 (실캡처 fixture 기반)
```

책임 분리:
- `serp_parser.py`: "SERP → 구조화 결과 → 셀 문자열". Selenium 캡처 + 순수 변환함수. 순수함수만 단위테스트.
- `sheets.py`: 구글시트 I/O. **오직 `블록 체커` 탭만** 다룸. `ws.update()` 명시 범위만(append 금지).
- `main.py`: 트리거 감지 → 캡처 → 기록 → 상태 갱신.

검증 기준(CLAUDE.md): 순수함수는 pytest, Selenium/시트는 실데이터 실행 결과로 확인.

---

## Task 1: 프로젝트 스캐폴드 + config

**Files:**
- Create: `블로그 블록 체커/config.json`
- Create: `블로그 블록 체커/__init__.py` (빈 파일)
- Create: `블로그 블록 체커/tests/__init__.py` (빈 파일)

- [ ] **Step 1: 폴더·config 생성**

`블로그 블록 체커/config.json`:
```json
{
  "SHEET_ID": "1jflcdbmBjQsY4hp8rNULXGGVqb64fGno4kudlTJoqM4",
  "TAB_NAME": "블록 체커",
  "CRED_FILE_REL": "../blog_management_hub/credentials.json"
}
```

빈 파일 2개 생성: `블로그 블록 체커/__init__.py`, `블로그 블록 체커/tests/__init__.py`

- [ ] **Step 2: pytest 설치 확인**

Run: `py -m pytest --version`
Expected: 버전 출력. 없으면 `py -m pip install pytest` 후 재확인.

- [ ] **Step 3: 커밋**

```bash
git add 블로그 블록 체커/config.json 블로그 블록 체커/__init__.py 블로그 블록 체커/tests/__init__.py
git commit -m "feat(블로그 블록 체커): 프로젝트 스캐폴드 + config"
```

---

## Task 2: 날짜 토큰 추출 (extract_dates)

**Files:**
- Create: `블로그 블록 체커/serp_parser.py`
- Test: `블로그 블록 체커/tests/test_serp_parser.py`

- [ ] **Step 1: 실패 테스트 작성**

`블로그 블록 체커/tests/test_serp_parser.py`:
```python
# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from serp_parser import extract_dates


def test_extract_dates_상대형():
    # 인기글 블록 텍스트 모사 — 글마다 날짜 1개
    text = "글제목A 2일 전 글제목B 1주 전 글제목C 3주 전"
    assert extract_dates(text) == ["2일 전", "1주 전", "3주 전"]


def test_extract_dates_절대형_혼합():
    text = "2026.02.13. ... 14시간 전 ... 2025.09.18."
    assert extract_dates(text) == ["2026.02.13.", "14시간 전", "2025.09.18."]


def test_extract_dates_없으면_빈리스트():
    assert extract_dates("날짜 없는 텍스트") == []
```

- [ ] **Step 2: 실패 확인**

Run: `py -m pytest 블로그 블록 체커/tests/test_serp_parser.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'serp_parser'`

- [ ] **Step 3: 최소 구현**

`블로그 블록 체커/serp_parser.py`:
```python
# -*- coding: utf-8 -*-
"""네이버 SERP 블록 분류 + 날짜 추출/환산 + 셀 포맷."""
import re

# 날짜 토큰: 상대형(N초/분/시간/일/주/개월 전, 어제/그제) + 절대형(YYYY.MM.DD)
DATE_RE = re.compile(
    r'(\d+초 전|\d+분 전|\d+시간 전|\d+일 전|\d+주 전|\d+개월 전|어제|그제|\d{4}\.\d{2}\.\d{2}\.?)'
)


def extract_dates(text):
    """유닛 텍스트에서 날짜 토큰을 등장 순서대로 모두 추출(중복 허용 = 글 수 반영)."""
    return DATE_RE.findall(text or "")
```

- [ ] **Step 4: 통과 확인**

Run: `py -m pytest 블로그 블록 체커/tests/test_serp_parser.py -v`
Expected: 3 PASS

- [ ] **Step 5: 커밋**

```bash
git add 블로그 블록 체커/serp_parser.py 블로그 블록 체커/tests/test_serp_parser.py
git commit -m "feat(블로그 블록 체커): 날짜 토큰 추출 extract_dates"
```

---

## Task 2.5: ⚠️ 날짜 토큰 정규식 실데이터 재검증 (가정 점검)

**근거:** 정규식이 모든 블록 유형에서 글 수와 맞는지 추측 말고 확인. `순위체커/_diag_extract_result.json`이 실캡처 결과(글 수 검증된 데이터)다.

**Files:**
- Read: `순위체커/_diag_extract_result.json`

- [ ] **Step 1: 실캡처 날짜 수 대조**

`_diag_extract_result.json`을 열어 각 블록의 `dates` 길이를 확인:
기대값(검증됨) — 오메가3영양제 인기글=7, 콘드로이친 스블 3블록 각 3, 고혈압수치 통검 5건 각 1, 코큐텐 인기글=7.

`extract_dates`를 그 JSON의 어떤 블록 원문에 적용했을 때 같은 개수가 나오는지 즉석 확인:
```bash
py -c "import json; d=json.load(open('순위체커/_diag_extract_result.json',encoding='utf-8')); print({k:[len(b['dates']) for b in v['스블']] for k,v in d.items()})"
```
Expected: 콘드로이친 `[3,3,3]`, 오메가3 추천 `[3,3,3]` 등 — 위 기대값과 일치.

- [ ] **Step 2: 불일치 시 정규식 보완**

날짜 형식이 추가로 발견되면(`방금 전`, `오늘` 등) `DATE_RE`에 추가하고 Task 2 테스트에 케이스 추가 후 재실행. 일치하면 그대로 진행.

(코드 변경 없으면 커밋 생략)

---

## Task 3: 상대날짜 → 절대일 환산 (normalize_date)

**Files:**
- Modify: `블로그 블록 체커/serp_parser.py`
- Test: `블로그 블록 체커/tests/test_serp_parser.py`

- [ ] **Step 1: 실패 테스트 작성** (test 파일에 추가)

```python
from datetime import date
from serp_parser import normalize_date

TODAY = date(2026, 6, 4)

def test_normalize_상대_일():
    assert normalize_date("2일 전", TODAY) == date(2026, 6, 2)

def test_normalize_상대_주():
    assert normalize_date("1주 전", TODAY) == date(2026, 5, 28)

def test_normalize_상대_시간은_오늘():
    assert normalize_date("14시간 전", TODAY) == date(2026, 6, 4)

def test_normalize_어제_그제():
    assert normalize_date("어제", TODAY) == date(2026, 6, 3)
    assert normalize_date("그제", TODAY) == date(2026, 6, 2)

def test_normalize_절대형():
    assert normalize_date("2025.09.18.", TODAY) == date(2025, 9, 18)

def test_normalize_개월_근사30일():
    assert normalize_date("2개월 전", TODAY) == date(2026, 6, 4) - __import__("datetime").timedelta(days=60)
```

- [ ] **Step 2: 실패 확인**

Run: `py -m pytest 블로그 블록 체커/tests/test_serp_parser.py -v`
Expected: 새 테스트 FAIL — `ImportError: cannot import name 'normalize_date'`

- [ ] **Step 3: 구현** (serp_parser.py에 추가)

```python
from datetime import date, timedelta

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
```

- [ ] **Step 4: 통과 확인**

Run: `py -m pytest 블로그 블록 체커/tests/test_serp_parser.py -v`
Expected: 전체 PASS

- [ ] **Step 5: 커밋**

```bash
git add 블로그 블록 체커/serp_parser.py 블로그 블록 체커/tests/test_serp_parser.py
git commit -m "feat(블로그 블록 체커): 상대날짜 절대일 환산 normalize_date"
```

---

## Task 4: 블록 분류 (classify)

**Files:**
- Modify: `블로그 블록 체커/serp_parser.py`
- Test: `블로그 블록 체커/tests/test_serp_parser.py`

- [ ] **Step 1: 실패 테스트 작성** (실캡처 5건 기반 fixture)

```python
from serp_parser import classify

def _u(header, fe_view, blog, cafe):
    return {"header": header, "fe_view": fe_view, "blog": blog, "cafe": cafe}

def test_classify_인기글():  # 오메가3 영양제
    assert classify(_u("인기글", True, 10, 15), n_posts=7) == ("인기글", "인기글")

def test_classify_분야인기글():  # 코큐텐 영양제
    assert classify(_u("건강·의학 인기글", True, 13, 6), n_posts=7) == ("인기글", "건강·의학 인기글")

def test_classify_스블_키워드인기글():  # 오메가3 추천 (fe_view 없음)
    assert classify(_u("'오메가3추천' 인기글", False, 17, 10), n_posts=3) == ("스블", "'오메가3추천' 인기글")

def test_classify_스블_주제():  # 콘드로이친
    assert classify(_u("맥스콘드로이친", False, 19, 0), n_posts=3) == ("스블", "맥스콘드로이친")

def test_classify_통검블로그_낱개():  # 고혈압 수치
    assert classify(_u("팬더2주 전Keep에 저장", False, 3, 0), n_posts=1) == ("통검블로그", "팬더2주 전Keep에 저장")

def test_classify_낱개카페_제외():  # 고혈압 예쁜카페 오탐 방지
    assert classify(_u("예쁜카페 예카4주 전", False, 0, 9), n_posts=1) is None

def test_classify_브랜드콘텐츠_제외():
    assert classify(_u("'콘드로이친' 관련 브랜드 콘텐츠", True, 0, 0), n_posts=0) is None

def test_classify_비블로그_제외():
    assert classify(_u("네이버 가격비교", False, 0, 0), n_posts=0) is None
    assert classify(_u("네이버 지식iN 2주 전", False, 0, 0), n_posts=1) is None
```

- [ ] **Step 2: 실패 확인**

Run: `py -m pytest 블로그 블록 체커/tests/test_serp_parser.py -v`
Expected: classify 테스트 FAIL — import 실패

- [ ] **Step 3: 구현** (serp_parser.py에 추가)

```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `py -m pytest 블로그 블록 체커/tests/test_serp_parser.py -v`
Expected: 전체 PASS

- [ ] **Step 5: 커밋**

```bash
git add 블로그 블록 체커/serp_parser.py 블로그 블록 체커/tests/test_serp_parser.py
git commit -m "feat(블로그 블록 체커): 블록 분류 classify (실캡처 5건 검증)"
```

---

## Task 5: 셀 포맷 함수 (fmt_popular / fmt_smartblock / fmt_general)

**Files:**
- Modify: `블로그 블록 체커/serp_parser.py`
- Test: `블로그 블록 체커/tests/test_serp_parser.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
from datetime import date
from serp_parser import fmt_popular, fmt_smartblock, fmt_general

T = date(2026, 6, 4)

def test_fmt_popular_분야명():
    blocks = [{"header": "건강·의학 인기글",
               "dates": [date(2026,5,7), date(2026,3,27)]}]
    flag, dates = fmt_popular(blocks, T)
    assert flag == "✅ 건강·의학"
    assert dates == "2건: 05.07, 03.27"

def test_fmt_popular_접두어없음():
    blocks = [{"header": "인기글", "dates": [date(2026,6,3)]}]
    flag, dates = fmt_popular(blocks, T)
    assert flag == "✅"
    assert dates == "1건: 06.03"

def test_fmt_popular_없음():
    assert fmt_popular([], T) == ("❌", "")

def test_fmt_smartblock_여러블록_줄바꿈():
    blocks = [
        {"header": "맥스콘드로이친", "dates": [date(2026,5,14), date(2025,9,18)]},
        {"header": "관절엔 콘드로이친", "dates": [date(2026,5,31)]},
    ]
    flag, text = fmt_smartblock(blocks, T)
    assert flag == "✅ 2블록"
    assert text == "맥스콘드로이친(2): 05.14, 2025.09.18\n관절엔 콘드로이친(1): 05.31"

def test_fmt_general():
    blocks = [
        {"header": "x", "dates": [date(2026,5,30)]},
        {"header": "y", "dates": [date(2026,5,21)]},
    ]
    flag, dates = fmt_general(blocks, T)
    assert flag == "✅ 2건"
    assert dates == "2건: 05.30, 05.21"
```

- [ ] **Step 2: 실패 확인**

Run: `py -m pytest 블로그 블록 체커/tests/test_serp_parser.py -v`
Expected: fmt 테스트 FAIL — import 실패

- [ ] **Step 3: 구현** (serp_parser.py에 추가)

```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `py -m pytest 블로그 블록 체커/tests/test_serp_parser.py -v`
Expected: 전체 PASS

- [ ] **Step 5: 커밋**

```bash
git add 블로그 블록 체커/serp_parser.py 블로그 블록 체커/tests/test_serp_parser.py
git commit -m "feat(블로그 블록 체커): 셀 포맷 함수 (줄바꿈 스블 포함)"
```

---

## Task 6: 캡처 + 파싱 (create_driver, capture_units, parse_keyword) — 실데이터 검증

**Files:**
- Modify: `블로그 블록 체커/serp_parser.py`

TDD 대신 실데이터 실행으로 검증(Selenium은 단위테스트 부적합). 분류 로직은 Task 4에서 검증됨.

- [ ] **Step 1: 드라이버 + 캡처 JS + parse_keyword 구현** (serp_parser.py에 추가)

```python
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
```

- [ ] **Step 2: 실데이터 스모크 실행**

임시 실행 스크립트로 5개 키워드 확인:
```bash
py -c "
import sys; sys.path.insert(0,'블로그 블록 체커')
from datetime import date
from serp_parser import create_driver, parse_keyword
d=create_driver()
for kw in ['오메가3 영양제','콘드로이친','고혈압 수치','오메가3 추천','코큐텐 영양제']:
    r=parse_keyword(d, kw, date.today())
    print(kw, '| 인기글', len(r['인기글']), '스블', len(r['스블']), '통검', len(r['통검블로그']))
d.quit()
"
```
Expected (검증된 정답):
```
오메가3 영양제 | 인기글 1 스블 0 통검 0
콘드로이친 | 인기글 0 스블 3 통검 0
고혈압 수치 | 인기글 0 스블 0 통검 5
오메가3 추천 | 인기글 0 스블 3 통검 0
코큐텐 영양제 | 인기글 1 스블 0 통검 0
```
불일치 시 분류/캡처 로직 점검 후 재실행(네이버 결과는 시점에 따라 ±1 블록 변동 가능 — 종류가 맞으면 통과).

- [ ] **Step 3: 커밋**

```bash
git add 블로그 블록 체커/serp_parser.py
git commit -m "feat(블로그 블록 체커): SERP 캡처 + parse_keyword (실데이터 5건 검증)"
```

---

## Task 7: 시트 연결 + 탭 보장 (sheets.connect, ensure_tab) — 실데이터 검증

**Files:**
- Create: `블로그 블록 체커/sheets.py`

⚠️ **데이터 보호: `블록 체커` 탭만 생성/접근. 기존 24개 탭은 절대 안 건드림.**

- [ ] **Step 1: 구현**

`블로그 블록 체커/sheets.py`:
```python
# -*- coding: utf-8 -*-
"""블록 체커 탭 연결·읽기·기록. 이 탭 외 다른 탭은 절대 다루지 않는다."""
import os, json, base64, re
import gspread
from google.oauth2.service_account import Credentials

BASE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(BASE, "config.json"), encoding="utf-8") as f:
    CFG = json.load(f)

SHEET_ID = CFG["SHEET_ID"]
TAB_NAME = CFG["TAB_NAME"]
CRED_FILE = os.path.normpath(os.path.join(BASE, CFG["CRED_FILE_REL"]))

HEADER = ["키워드", "실행", "인기글", "인기글 날짜", "스블",
          "스블 주제·날짜", "통검블로그", "통검 날짜", "상태"]

def _client():
    scope = ["https://www.googleapis.com/auth/spreadsheets",
             "https://www.googleapis.com/auth/drive"]
    b64 = os.environ.get("GOOGLE_CREDENTIALS_BASE64")
    if b64:
        creds = Credentials.from_service_account_info(json.loads(base64.b64decode(b64)), scopes=scope)
    else:
        creds = Credentials.from_service_account_file(CRED_FILE, scopes=scope)
    return gspread.authorize(creds)

def connect():
    """블록 체커 탭 워크시트 반환(없으면 생성 + 헤더 + 체크박스)."""
    ss = _client().open_by_key(SHEET_ID)
    titles = [w.title for w in ss.worksheets()]
    if TAB_NAME in titles:
        return ss.worksheet(TAB_NAME)
    ws = ss.add_worksheet(title=TAB_NAME, rows=500, cols=len(HEADER))
    ws.update(values=[HEADER], range_name=f"A1:{chr(ord('A')+len(HEADER)-1)}1")
    _set_checkbox(ss, ws, "B2:B500")
    return ws

def _set_checkbox(ss, ws, range_str):
    m = re.match(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", range_str)
    sc = ord(m.group(1)) - ord("A"); sr = int(m.group(2)) - 1
    ec = ord(m.group(3)) - ord("A") + 1; er = int(m.group(4))
    ss.batch_update({"requests": [{"setDataValidation": {
        "range": {"sheetId": ws.id, "startRowIndex": sr, "endRowIndex": er,
                  "startColumnIndex": sc, "endColumnIndex": ec},
        "rule": {"condition": {"type": "BOOLEAN"}, "showCustomUi": True}}}]})
```

- [ ] **Step 2: 실행 — 탭 생성 확인**

```bash
py -c "import sys; sys.path.insert(0,'블로그 블록 체커'); import sheets; ws=sheets.connect(); print('탭 OK:', ws.title, '| 헤더:', ws.row_values(1))"
```
Expected: `탭 OK: 블록 체커 | 헤더: ['키워드','실행','인기글',...,'상태']`
그리고 구글시트에서 `블록 체커` 탭이 새로 생기고 B열에 체크박스가 보임. **기존 탭 수(24개)는 그대로 + 1.**

- [ ] **Step 3: 커밋**

```bash
git add 블로그 블록 체커/sheets.py
git commit -m "feat(블로그 블록 체커): 블록 체커 탭 연결/생성 (기존 탭 불가침)"
```

---

## Task 8: 대상 행 읽기 + 체크 해제 (read_targets, clear_checkboxes)

**Files:**
- Modify: `블로그 블록 체커/sheets.py`
- Test: `블로그 블록 체커/tests/test_sheets.py`

- [ ] **Step 1: 실패 테스트 작성** (순수 파싱 함수만 테스트)

`블로그 블록 체커/tests/test_sheets.py`:
```python
# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sheets import parse_targets

def test_parse_targets_체크된행만():
    rows = [
        ["키워드","실행","인기글"],          # 1행 헤더
        ["오메가3 영양제","TRUE",""],          # 2행 체크됨
        ["콘드로이친","FALSE",""],             # 3행 미체크
        ["고혈압 수치","TRUE",""],             # 4행 체크됨
        ["","",""],                            # 5행 빈 행
    ]
    assert parse_targets(rows) == [(2, "오메가3 영양제"), (4, "고혈압 수치")]

def test_parse_targets_키워드없으면_제외():
    rows = [["키워드","실행"], ["","TRUE"]]
    assert parse_targets(rows) == []
```

- [ ] **Step 2: 실패 확인**

Run: `py -m pytest 블로그 블록 체커/tests/test_sheets.py -v`
Expected: FAIL — `cannot import name 'parse_targets'`

- [ ] **Step 3: 구현** (sheets.py에 추가)

```python
def parse_targets(rows):
    """get_all_values() 결과 → 체크된(B열 TRUE) + 키워드 있는 행 [(행번호, 키워드)]."""
    out = []
    for idx, row in enumerate(rows[1:], start=2):
        kw = (row[0].strip() if len(row) > 0 else "")
        chk = (row[1].strip().upper() if len(row) > 1 else "")
        if kw and chk in ("TRUE", "O", "V", "Y", "1", "ㅇ"):
            out.append((idx, kw))
    return out

def read_targets(ws):
    """워크시트에서 체크된 대상 행 읽기."""
    return parse_targets(ws.get_all_values())

def clear_checkboxes(ws, row_nums):
    """처리한 행들의 B열 체크 해제."""
    if not row_nums:
        return
    ws.batch_update([{"range": f"B{r}", "values": [[False]]} for r in row_nums])
```

- [ ] **Step 4: 통과 확인**

Run: `py -m pytest 블로그 블록 체커/tests/test_sheets.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add 블로그 블록 체커/sheets.py 블로그 블록 체커/tests/test_sheets.py
git commit -m "feat(블로그 블록 체커): 대상 행 읽기 + 체크 해제"
```

---

## Task 9: 결과 기록 (write_result)

**Files:**
- Modify: `블로그 블록 체커/sheets.py`

- [ ] **Step 1: 구현** (sheets.py에 추가)

```python
from datetime import datetime
from serp_parser import fmt_popular, fmt_smartblock, fmt_general

def build_row_values(result, today, now_str):
    """parse_keyword 결과 → C..I열 값 리스트 (포맷 적용)."""
    p_flag, p_dates = fmt_popular(result["인기글"], today)
    s_flag, s_text = fmt_smartblock(result["스블"], today)
    g_flag, g_dates = fmt_general(result["통검블로그"], today)
    status = f"완료 {now_str}"
    return [p_flag, p_dates, s_flag, s_text, g_flag, g_dates, status]

def write_result(ws, row_num, result, today):
    """C{row}:I{row}에 결과 1행 기록 (명시 범위, append 금지)."""
    now_str = datetime.now().strftime("%m/%d %H:%M")
    values = build_row_values(result, today, now_str)
    ws.update(values=[values], range_name=f"C{row_num}:I{row_num}")

def write_error(ws, row_num, msg):
    """I열에 오류 상태 기록."""
    ws.update(values=[[f"오류: {msg}"]], range_name=f"I{row_num}")
```

- [ ] **Step 2: 실데이터 기록 검증**

`블록 체커` 탭 A2에 `오메가3 영양제`, A3에 `콘드로이친` 직접 입력 후:
```bash
py -c "
import sys; sys.path.insert(0,'블로그 블록 체커')
from datetime import date
import sheets
from serp_parser import create_driver, parse_keyword
ws=sheets.connect(); d=create_driver()
for row,kw in [(2,'오메가3 영양제'),(3,'콘드로이친')]:
    r=parse_keyword(d,kw,date.today())
    sheets.write_result(ws,row,r,date.today())
    print('기록:',row,kw)
d.quit()
"
```
Expected: 시트 2행 인기글 `✅` + 날짜, 3행 스블 `✅ 3블록` + 줄바꿈 주제·날짜. **다른 탭 변화 없음.**

- [ ] **Step 3: 커밋**

```bash
git add 블로그 블록 체커/sheets.py
git commit -m "feat(블로그 블록 체커): 결과 기록 write_result (C:I 명시범위)"
```

---

## Task 10: 오케스트레이션 (main.run_once) — 엔드투엔드

**Files:**
- Create: `블로그 블록 체커/main.py`

- [ ] **Step 1: 구현**

`블로그 블록 체커/main.py`:
```python
# -*- coding: utf-8 -*-
"""네이버 블록 체커 — 블록 체커 탭 B열 체크 → 인기글/스블/통검블로그 분석·기록.
실행: py main.py   (체크된 행 1회 처리)
      py main.py watch  (60초 감시)
"""
import sys, time
from datetime import date
import sheets
from serp_parser import create_driver, parse_keyword

def run_once():
    print("=" * 50); print("  네이버 블록 체커"); print("=" * 50)
    print("\n[1] 시트 연결...")
    ws = sheets.connect()
    targets = sheets.read_targets(ws)
    if not targets:
        print("    처리 대상 없음. 블록 체커 탭 B열에 체크하세요.")
        return
    print(f"    {len(targets)}개 처리 대상")
    sheets.clear_checkboxes(ws, [r for r, _ in targets])

    print("\n[2] 브라우저 준비...")
    driver = create_driver()
    today = date.today()
    try:
        for i, (row, kw) in enumerate(targets, 1):
            print(f"\n  [{i}/{len(targets)}] {kw} (행 {row})")
            try:
                result = parse_keyword(driver, kw, today)
                sheets.write_result(ws, row, result, today)
                print(f"        인기글 {len(result['인기글'])} / "
                      f"스블 {len(result['스블'])} / 통검 {len(result['통검블로그'])}")
            except Exception as e:
                print(f"        [!] 오류: {e}")
                sheets.write_error(ws, row, str(e)[:80])
            time.sleep(2)
    finally:
        try: driver.quit()
        except Exception: pass
    print("\n  완료!")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "once"
    if cmd == "watch":
        from watch_mode import watch
        watch()
    else:
        run_once()
```

- [ ] **Step 2: 엔드투엔드 실행**

`블록 체커` 탭 A2~A4에 키워드 3개 입력, B2~B4 체크 후:
```bash
py 블로그 블록 체커/main.py
```
Expected: 콘솔에 각 키워드 종류별 개수 출력, 시트에 결과 기록, B열 체크 자동 해제, I열 `완료 MM/DD HH:MM`.

- [ ] **Step 3: 커밋**

```bash
git add 블로그 블록 체커/main.py
git commit -m "feat(블로그 블록 체커): run_once 오케스트레이션 (엔드투엔드)"
```

---

## Task 11: 감시 모드 + 실행 편의 (watch, bat)

**Files:**
- Create: `블로그 블록 체커/watch_mode.py`
- Create: `블로그 블록 체커/블로그블록체커_실행.bat`

- [ ] **Step 1: 감시 모드 구현**

`블로그 블록 체커/watch_mode.py`:
```python
# -*- coding: utf-8 -*-
"""60초마다 블록 체커 탭 확인 → 체크 감지 시 run_once 실행."""
import time
from datetime import datetime
import sheets
import main as m

def watch(interval=60):
    print("블록 체커 감시 모드 (60초 간격, Ctrl+C 종료)")
    try:
        while True:
            ws = sheets.connect()
            targets = sheets.read_targets(ws)
            if targets:
                print(f"\n>> 체크 감지 {len(targets)}개 — 처리 시작")
                m.run_once()
            else:
                now = datetime.now().strftime("%H:%M:%S")
                print(f"\r[{now}] 대기 중...", end="", flush=True)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n감시 종료")
```

- [ ] **Step 2: bat 런처 작성**

`블로그 블록 체커/블로그블록체커_실행.bat`:
```bat
@echo off
chcp 65001 >nul
cd /d "%~dp0"
py main.py
pause
```

- [ ] **Step 3: 실행 확인**

Run: `py 블로그 블록 체커/main.py watch` (몇 초 후 Ctrl+C)
Expected: "대기 중..." 출력, 에러 없이 종료. bat 더블클릭 시 run_once 동작.

- [ ] **Step 4: 커밋**

```bash
git add 블로그 블록 체커/watch_mode.py 블로그 블록 체커/블로그블록체커_실행.bat
git commit -m "feat(블로그 블록 체커): 감시 모드 + bat 런처"
```

---

## Task 12: 진단 임시파일 정리 + 마무리

**Files:**
- Delete: `순위체커/_diag_capture.py`, `_diag_tree.py`, `_diag_extract.py`, `_diag_*.json`, `_diag_*.html`

- [ ] **Step 1: 전체 테스트 재확인**

Run: `py -m pytest 블로그 블록 체커/tests/ -v`
Expected: 전체 PASS

- [ ] **Step 2: 진단 파일 삭제**

```bash
rm "순위체커/_diag_capture.py" "순위체커/_diag_tree.py" "순위체커/_diag_extract.py"
rm 순위체커/_diag_*.json 순위체커/_diag_*.html
```
(설계 근거는 이미 spec에 기록됨 — 임시 산출물만 제거)

- [ ] **Step 3: 커밋**

```bash
git add -A 순위체커/
git commit -m "chore(블로그 블록 체커): 진단 임시파일 정리"
```

---

## Self-Review 체크

- **Spec 커버리지:** 분류규칙(Task 4) / 날짜추출·환산(2,3) / 셀포맷·줄바꿈(5) / 캡처(6) / 블록 체커 탭·불가침(7) / 수동입력 트리거(8) / 기록(9) / 오케스트레이션(10) / 모드(11) — spec 전 항목 대응.
- **빌드 시 검증(spec §6):** Task 2.5(날짜 정규식), Task 6 Step2(분류 실데이터), Task 9(분야명·포맷) 으로 흡수.
- **타입 일관성:** `parse_keyword` 반환 구조 `{"인기글":[{header,dates}],...}` → `fmt_*`(blocks, today) → `build_row_values` → `write_result` 동일 키 사용. `classify(unit, n_posts)` 시그니처 Task 4·6 일치. `connect/read_targets/clear_checkboxes/write_result/write_error` main에서 호출 시그니처 일치.
