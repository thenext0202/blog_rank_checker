# 발행검수 프로그램 작업 인수인계

> 파일: `C:\Users\iamhy\Desktop\health_marketing\발행검수\main.py`
> 날짜: 2026-03-19
> 버전: v1.1 기반 수정 중

---

## 프로그램 개요

네이버 블로그에 발행된 원고를 자동 검수하는 tkinter GUI 프로그램.
구글 시트(자사 발행리스트 + 원고리스트) → DOCX 원본 다운로드 → 블로그 크롤링 → 대조 검수 → 수정 요청 메시지 생성.

---

## 이번 세션에서 시도한 것

### 성공한 변경사항 (현재 코드에 반영됨)

1. **링크 없음 표시** — 시트 M열(발행 링크)이 비어있으면 트리뷰에 "링크 없음" 상태 표시
2. **원고 비교 팝업** — 트리 더블클릭 시 DOCX 전문을 보여주는 팝업 창 + "블로그 열기" 버튼(webbrowser.open)
3. **블로그 열기 버튼** — 상단 컨트롤 바에 "블로그 열기" 버튼 추가, 트리 선택 항목의 블로그를 브라우저로 열기
4. **키보드 네비게이션** — 위/아래 화살표로 상세 정보 갱신, 엔터로 블로그 열기
5. **블로그 내 링크 목록 패널** — 상세 정보 아래에 블로그에서 수집한 링크 목록 표시, 더블클릭으로 브라우저 열기
6. **URL 한글 디코딩** — `unquote()`로 URL 인코딩된 한글 표시, `NaPm=` 추적 파라미터 제거
7. **블로그 자체 링크 필터** — `blog.naver.com/`, `shopping.naver.com/ns/`, `#` 앵커 링크 수집 제외
8. **원고 내용 누락 검수 제거** — 7번 검수(본문 텍스트 비교)가 부정확하여 삭제
9. **링크 실접속 검증** — `requests`로 원고 링크와 블로그 링크를 실제 접속하여 최종 리다이렉트 URL 비교 (`_resolve_url` + `_normalize_url`)
10. **링크 삽입 위치 3단 구분** — `image`(이미지에 걸림) / `widget`(링크 도구) / `text`(텍스트 링크) / `missing`(없음)
11. **링크 수집 강화** — `<a>` 태그 외에 `se-oglink`, `se-module-oglink`, `data-linkdata` 등 네이버 블로그 위젯에서도 링크 추출
12. **page_source 폴백 제거** — HTML 전체를 regex로 뒤지던 로직 제거. 실제 클릭 가능한 `<a>` 태그와 위젯에서만 링크 수집

### 시도했으나 효과 없는 것 (고질적 문제)

1. **DOCX 전문이 비어있음** — `parse_docx()`에 `full_text` 필드를 추가했으나, 팝업에서 "(원고 없음)"으로 표시됨. `find_and_download()`가 파일을 못 찾거나, 다운로드 실패 후 `EMPTY_DOCX`로 폴백되는 것으로 추정. 콘솔에 `[DOCX 오류]` 로그를 추가했지만 사용자가 아직 확인하지 못함.

2. **이미지 링크 검수가 작동 안 함** — 원고에 "ㄴ 이미지에 상품 링크 삽입" 지시가 있는데, 이미지에 링크가 안 걸려있어도 "통과"로 판정됨.
   - **근본 원인**: DOCX 다운로드 실패 → `instructions` 빈 리스트 → `require_image = False` → 이미지 삽입 검증 스킵
   - 현재 코드는 `instructions_text`에서 "이미지"+"링크" 키워드로 `require_image`를 판단하는데, DOCX가 없으면 무조건 통과

3. **블로그 내 mkt 링크 수집 누락** — 사용자가 "동일한 것만 두 개 나온다"고 보고. 위젯 셀렉터를 추가했지만 네이버 블로그 SE3 에디터의 실제 DOM 구조를 확인하지 못한 상태. 실제 블로그 페이지의 HTML을 직접 확인하여 정확한 셀렉터를 잡아야 함.

---

## 현재 코드 구조 (핵심 함수)

```
fetch_items()          시트에서 발행 건 조회 (자사 발행리스트 + 원고리스트 조인)
find_and_download()    Drive에서 DOCX/ZIP 검색 및 다운로드
parse_docx()           DOCX 파싱 → instructions, image_numbers, ad_links, content, full_text
setup_driver()         Selenium headless Chrome 생성
scrape_blog()          블로그 크롤링 → title, body, links, image_links, widget_links
_link_found_in_blog()  링크 검증 → "image" | "widget" | "text" | "missing"
_resolve_url()         URL 실접속 → 최종 리다이렉트 URL
check_publication()    6가지 검수 실행
generate_message()     발행처별 수정 요청 메시지 생성
```

### 데이터 흐름

```
시트 → items[] → 각 item에 대해:
  ├─ find_and_download(filename) → parse_docx() → docx_info
  ├─ scrape_blog(link) → blog_info
  └─ check_publication(item, docx_info, blog_info) → issues[]

tree_data[iid] = (item, issues, docx_info, blog_info)  ← 4-tuple
```

### 검수 항목 (check_publication)

1. 제목 불일치 (시트 vs 블로그)
2. 요청 문구 노출 (DOCX 지시사항이 블로그 본문에 그대로 노출)
3. 서식 키워드 노출 ("인용구", "글자크기" 등이 블로그에 노출)
4. 이미지 번호 노출 (DOCX의 이미지 번호가 블로그에 노출)
5. 상품 링크 검수 (삽입 여부 + 위치)
6. 광고 링크 검수 (삽입 여부 + 위치)

---

## 다음 단계 (우선순위순)

### 1. DOCX 다운로드 실패 원인 해결 (최우선)
- `find_and_download()`를 디버깅해야 함
- 가능한 원인: 파일명 불일치, Drive API 권한, 공유 드라이브 접근, ZIP 내부 구조
- **테스트 방법**: 특정 `filename` 값으로 `find_and_download()`를 단독 실행하여 반환값 확인
- 이 문제가 해결되면 검수 2~4번(요청문구/서식키워드/이미지번호)과 이미지 링크 삽입 검증이 모두 작동함

### 2. DOCX 없이도 링크 삽입 위치 표시 (DOCX 문제 우회)
- 사용자와 마지막 합의: DOCX 의존 없이, 각 링크가 `image`/`widget`/`text`/`missing` 중 어디에 있는지 **무조건 상세 정보에 표시**
- 현재는 `require_image`가 False이면 `widget`도 통과시키고 아무것도 안 보여줌
- **구현 방향**: 통과/실패와 별개로, 상세 정보에 "상품링크: image에 삽입됨" / "광고링크: widget에 삽입됨" 식으로 항상 표시하여 사용자가 눈으로 판단 가능하게

### 3. 블로그 링크 수집 정확도 개선
- 실제 네이버 블로그 페이지의 HTML(특히 SE3 에디터)을 DevTools로 확인하여 정확한 셀렉터 파악
- 현재 추가한 위젯 셀렉터(`se-oglink-info`, `se-module-oglink` 등)가 실제로 맞는지 검증 필요
- `image_links` 판정도 실제 DOM에서 `<a><img></a>` 구조가 맞는지 확인 필요

### 4. 링크 실접속 성능 최적화
- 현재 매 링크마다 `requests.head()` → 실패 시 `requests.get()` 수행
- 건수가 많으면 검수 시간이 크게 증가할 수 있음
- 캐싱 또는 병렬 처리 고려

---

## 참고: 시트 컬럼 매핑

**자사 발행리스트** (ws_pub)
- A열(0): 날짜, H열(7): 파라미터, L열(11): 제목, M열(12): 링크, N열(13): 발행처

**원고리스트** (ws_man)
- J열(9): 파라미터(조인키), AB열(27): 상품링크, AC열(28): 광고링크, AG열(32): 파일명
