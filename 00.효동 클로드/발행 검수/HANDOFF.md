# 📋 발행검수 프로그램 — 전체 HANDOFF

> 📁 파일: `C:\Users\iamhy\Desktop\프로그램 개발\발행검수\main.py`
> 📅 최종 업데이트: 2026-03-25
> 🏷️ 버전: v1.9

---

## 🔎 프로그램 개요

네이버 블로그에 발행된 원고를 **자동 검수**하는 tkinter GUI 프로그램.

```
구글 시트 → DOCX 원본 다운로드 → 블로그 크롤링 → 대조 검수 → 수정 요청 메시지 생성 → 임시파일 자동 정리
```

### 📦 EXE 배포 (v1.7~)

```
발행검수\dist\
  ├─ 발행검수.exe       (47MB, Python 불필요)
  └─ credentials.json   (Google 서비스 계정)
```

- `sys.frozen` 분기로 EXE/Python 양쪽 호환
- EXE 옆 `credentials.json` 우선 → 없으면 기존 `manuscript_generator/` 경로 fallback

---

## 🧩 핵심 함수 구조

| 함수 | 역할 |
|------|------|
| `fetch_items()` | 시트에서 발행 건 조회 (자사 발행리스트 + 원고리스트 조인) |
| `_strip_pub_date()` | 파일명에서 발행일(`_YYMMDD_`) 제거 후보 생성 |
| `find_and_download()` | Drive에서 DOCX/ZIP 검색 및 다운로드 → `(path, tmp_dir)` 튜플 반환 |
| `parse_docx()` | DOCX 파싱 → instructions, image_numbers, ad_links, format_reqs, link_reqs |
| `_parse_format_info()` | `ㄴ` 지시에서 인용구/글자크기/볼드/색상 추출 |
| `setup_driver()` | Selenium headless Chrome 생성 |
| `scrape_blog()` | 블로그 크롤링 → title, body, links, format_info, **all_mkt_links** |
| `_check_link_accessible()` | URL 접속 확인 → `(accessible, final_url)` |
| `_normalize_url()` | 비교용 URL 정규화 (netloc + path) |
| `_color_matches()` | 색상명 ↔ RGB 매칭 |
| `check_publication()` | 7가지 검수 실행 + `blog_info["link_results"]` 생성 |
| `generate_message()` | 발행처별 수정 요청 메시지 생성 |
| `_cleanup_tmp()` | 검수 완료/중단 시 임시 다운로드 폴더 일괄 삭제 |

---

## ✅ 검수 항목 (7가지)

| # | 항목 | 설명 |
|---|------|------|
| 1 | 제목 불일치 | 시트 vs 블로그 제목 비교 |
| 2 | 요청 문구 노출 | DOCX 지시사항이 블로그 본문에 그대로 노출 |
| 3 | 서식 키워드 노출 | "인용구", "글자크기" 등이 블로그에 노출 |
| 4 | 이미지 번호 노출 | DOCX의 이미지 번호가 블로그에 노출 |
| 5 | **링크 검수** | 상품+광고 통합, 각 MKT 링크별 접속/매칭/위치 확인 |
| 6 | *(5번에 통합)* | — |
| 7 | **서식 검수** | 인용구/글자크기/볼드/색상 — 점수 기반 매칭 |

---

## 🔗 링크 검수 체계 (v1.6 기준)

### MKT 링크 수집 (`scrape_blog` step 6)

JS로 블로그 내 모든 `<a>` 태그 탐색, **oglink 컴포넌트 단위 중복 제거**

| DOM 위치 | 분류 | 비고 |
|----------|------|------|
| `.se-module-oglink`, `.se-section-oglink`, `[data-linkdata]` | **배너** | `data-linkdata`에서 원본 URL 우선 추출 |
| `.se-component.se-image`, `.se-component.se-imageStrip` | **이미지** (N/M번째) | |
| 그 외 | **텍스트** | |

> ⚠️ **v1.6 핵심:** 배너 `<a>`의 `href`는 네이버 JS가 수정할 수 있으므로, `data-linkdata` 속성에서 원본 MKT URL을 우선 추출. `_bc05` 등 쿼리 파라미터 보존.

> ⚠️ **배너 중복 방지:** `processedBanners` 배열로 같은 oglink 내 여러 `<a>` 태그 → 1건만 수집

### 매칭 3단계 (`check_publication`)

| 단계 | 비교 방식 | 용도 |
|------|----------|------|
| **1차** | 전체 URL (쿼리 포함, percent-decode + 정렬) | 상품/광고 정확 구분 (`_hc` vs `_hc01`) |
| **2차** | MKT ID만 (`/link/ABC123` 경로) | 블로거가 파라미터 변경한 경우 fallback |
| **3차** | 최종 리다이렉트 URL | non-mkt 기대 링크용 |

> ⚠️ 상품/광고가 같은 MKT ID를 공유하는 경우가 있음 → 독립 `if/if` 구조로 둘 다 매칭

### 링크 목록 표시 (`_show_detail`)

```
[이미지 3/15번째] [접속OK] [상품링크] https://mkt...
[배너] [접속OK] [광고링크] https://mkt...
[텍스트] [접속불가] [불일치] https://mkt...

── 원고 링크 (시트) ──
  상품: https://mkt...
  광고: https://mkt...
```

---

## 📊 데이터 흐름

```
시트 → items[] → 각 item에 대해:
  ├─ find_and_download(filename) → (path, tmp_dir) → parse_docx() → docx_info
  │     ├─ instructions, image_numbers, ad_links, content, full_text
  │     ├─ format_reqs: [{text, quote, font_size, bold, color}, ...]
  │     └─ link_reqs: [{label, instruction}, ...]
  ├─ scrape_blog(link) → blog_info
  │     ├─ title, body, links, image_links, widget_links
  │     ├─ format_info: [{text, in_quote, font_size, bold, colors}, ...]
  │     ├─ image_link_map: {url → N번째 이미지}
  │     ├─ image_total: 전체 이미지 수
  │     └─ all_mkt_links: [{url, placement, image_index, image_total}, ...]
  └─ check_publication(item, docx_info, blog_info) → issues[]
        └─ blog_info["link_results"] 에 각 링크 상세 결과 저장

tree_data[iid] = (item, issues, docx_info, blog_info)

→ _cleanup_tmp(tmp_dirs)  # 검수 완료/중단 시 임시 폴더 삭제
```

---

## 📌 시트 컬럼 매핑

**자사 발행리스트** (ws_pub)

| 컬럼 | 인덱스 | 내용 |
|------|--------|------|
| A열 | 0 | 날짜 |
| H열 | 7 | 파라미터 |
| L열 | 11 | 제목 |
| M열 | 12 | 링크 |
| N열 | 13 | 발행처 |

**원고리스트** (ws_man)

| 컬럼 | 인덱스 | 내용 |
|------|--------|------|
| J열 | 9 | 파라미터 (조인키) |
| AB열 | 27 | 상품링크 |
| AC열 | 28 | 광고링크 |
| AG열 | 32 | 파일명 |

---

## 🏗️ 버전 히스토리

| 버전 | 날짜 | 주요 변경 |
|------|------|----------|
| **v1.9** | **2026-03-25** | **검수 결과 중복 보고 수정 — 요청문구 중복 제거 + 서식키워드↔요청문구 겹침 방지** |
| v1.8 | 2026-03-25 | `parse_docx` 요청사항 섹션(`in_req`) 종료 로직 개선 — 본문이 instructions로 잡히는 오탐 수정 |
| v1.7 | 2026-03-23 | EXE 빌드 (PyInstaller onefile), credentials.json 경로 자동 감지, 임시 DOCX 다운로드 폴더 자동 정리 |
| v1.6 | 2026-03-20 | 배너 `data-linkdata`에서 원본 MKT URL 추출 (파라미터 보존), oglink 컴포넌트 단위 중복 제거 |
| v1.5 | 2026-03-20 | 링크 검수 전면 개편: MKT 링크 전체 수집(중복 포함), 접속/매칭/위치 3가지 표시, 3단계 매칭(전체URL→ID→리다이렉트), 모바일 URL 대응 |
| v1.4 | 2026-03-20 | 위젯/이미지 링크 분류 뒤바뀜 수정 (oglink 썸네일 오분류 방지) |
| v1.3 | 2026-03-19 | mkt 링크만 표시, HTML 엔티티 중복 제거, 링크 삽입 위치 상세 표시 |
| v1.2 | 2026-03-19 | 글자크기 추출 확장, 서식 매칭 점수 기반 변경 |
| v1.1 | 2026-03-19 | DOCX 다운로드 실패 해결, 서식 검수(7번) 추가 |
| v1.0 | 이전 | 기본 검수 6종 + GUI + 메시지 생성 |

---

## 🔧 v1.9 변경 상세 (2026-03-25)

### 문제

`check_publication()`에서 같은 문제가 여러 번 보고되는 중복 버그 2건:

1. **요청 문구 중복**: `instructions` 리스트에 같은 텍스트가 2번 이상 존재하면 동일 이슈가 반복 보고
   - 예: `"bc3(<- 폴더 내 이미지 있음)"` → 2번 보고됨
2. **서식 키워드 ↔ 요청 문구 겹침**: 블로그에 노출된 서식 지시 `"인용구 6, 글자 크기 24"`가 요청문구(check 2)와 서식키워드(check 3) 양쪽에서 잡힘
   - 요청 문구 노출 1건 + 서식 키워드 노출 2건 = 같은 문제 3번 보고

### 수정 내용

| 변경 | 내용 |
|------|------|
| `req_seen` set 추가 | 동일 요청 문구 텍스트 중복 보고 방지 |
| `req_exposed` 리스트 추가 | 요청 문구로 이미 잡힌 텍스트 기록 |
| 서식 키워드 스킵 조건 | `any(req in ctx for req in req_exposed)` — 이미 요청문구에서 잡힌 내용이 서식키워드 컨텍스트에 포함되면 스킵 |

---

## 🔧 v1.8 변경 상세 (2026-03-25)

### 문제

`parse_docx()`에서 `★요청사항★` 이후 `in_req = True`가 설정되면, `---` 구분선이 없는 원고에서 **본문 전체가 instructions에 추가**되는 버그.

- 본문 줄이 모두 "요청 문구"로 분류 → 블로그에 당연히 존재 → **200건+ "요청 문구 노출" 오탐**
- 빈 줄은 `in_req` 체크 전에 `continue`로 넘어가 종료 조건을 만나지 못함

### 수정 내용

`in_req` 모드에서 **지시사항 특성이 있는 줄만** 캡처하고, 아니면 즉시 `in_req = False` 후 일반 파싱으로 넘김:

```python
is_instr_like = (
    text.startswith(("ㄴ", "-", "·", "*", "•"))
    or any(kw in text for kw in INSTRUCTION_KEYWORDS)
    or "★" in text
    or "부탁" in text or "요청" in text
    or text.startswith(("제목", "해시태그"))
    or re.match(r"^https?://", text)
)
```

| 줄 유형 | 처리 |
|---------|------|
| `- 글자크기 15/...` | `-`로 시작 → instructions ✓ |
| `ㄴ 인용구 3번...` | `ㄴ`으로 시작 → instructions ✓ |
| `제목 : 식후...` | `제목`으로 시작 → instructions ✓ |
| `0` (이미지 번호) | 해당 없음 → `in_req=False` → 일반 파싱 → image_numbers ✓ |
| `식후2시간혈당을 낮추려면` | 일반 파싱 → content ✓ |
| `2. 혈당 관리의 기본` | 일반 파싱 → content ✓ |

> ⚠️ `in_req` 종료 후에도 `ㄴ` 서식 지시줄은 일반 파싱의 `ㄴ` 처리 블록(242행~)에서 정상 캡처됨

---

## 🚀 다음 단계

| 우선순위 | 내용 |
|---------|------|
| 🟡 중간 | `_check_link_accessible()` 글로벌 캐시 (전체 검수 건에 걸쳐 동일 URL 중복 요청 방지) |
| 🟡 중간 | 서식 검수 점수 기반 매칭 추가 검증 |
| 🟢 낮음 | 미사용 함수 정리 (`_link_found_in_blog`, `_is_shop_candidate`, `_extract_link_id`) |
| 🟢 낮음 | 기존 step 1~3 링크 수집 (dedup 방식) 잔존 코드 정리 |
