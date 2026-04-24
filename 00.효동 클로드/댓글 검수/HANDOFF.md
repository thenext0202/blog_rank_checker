# 댓글 검수 프로그램 — 전체 HANDOFF

## 기본 정보
- **프로그램 경로**: `C:\Users\iamhy\Desktop\프로그램 개발\댓글검수\main.py`
- **버전**: v2.1
- **최초 작성일**: 2026-03-20
- **최종 수정일**: 2026-03-20

## 목적
네이버 블로그 댓글을 구글 시트 기대값과 대조하여 **중복/누락/미등록** 댓글을 자동 검출

## 시트 구조
- **시트 ID**: `14IQ3of3Pe9TI-VNHAKNisxYLNub9DSSH7ZZx2Rnzbj8`
- **탭**: `댓글 비교`
- **서비스 계정**: `blog-checking@blog-chekcing-program.iam.gserviceaccount.com` (편집자 권한 필요)

### 입력 (사용자가 준비)
- 5개 블록 지원: A-E, F-J, K-O, P-T, U-Y (각 동일 구조)
- 데이터가 있는 블록만 자동 인식

| 열 (블록 기준) | 용도 | 비고 |
|---|---|---|
| 1열 (A/F/K/P/U) | 블로그 링크 목록 | 쭉 나열 |
| 2열 (B/G/L/Q/V) | 기대 댓글 목록 | 쭉 나열. 모든 링크에 공통 적용 |

### 출력 (프로그램이 자동 기록)
- 기존 데이터를 클리어하고 **묶음 형태로 재배치**하여 기록

| 열 (블록 기준) | 용도 | 비고 |
|---|---|---|
| 1열 | 블로그 링크 | 묶음 첫 행에만 기록 |
| 2열 | 기대 댓글 | 링크 아래에 댓글별 1행씩 |
| 3열 (C/H/M/R/W) | 중복 여부 | `중복(N회)` 또는 빈칸 |
| 4열 (D/I/N/S/X) | 누락 여부 | `○` 또는 빈칸 |
| 5열 (E/J/O/T/Y) | 미등록 댓글 | 댓글 내용 그대로 기록 |

## 핵심 아키텍처

### v2.1 변경점 (v1.0 → v2.1)
- **입력 방식**: 링크별 그룹 → 링크/댓글 독립 목록 (모든 링크 × 모든 댓글)
- **블록 구조**: 1블록(A-E) → 5블록(A-E, F-J, K-O, P-T, U-Y)
- **병렬 스크래핑**: 순차 1개 → 브라우저 4개 동시 (`ThreadPoolExecutor`)
- **자동 재배치**: 결과를 묶음 형태로 시트에 재정렬
- **시트 자동 확장**: 행 수 부족 시 자동 `ws.resize()`
- **URL 캐시**: 동일 URL 중복 스크래핑 방지
- **자동 클리어**: 기존 데이터 `batch_clear` 후 새 결과 기록

### 블록 파싱 (`parse_block`)
- 1행: 헤더 스킵
- col_offset 열: 링크 수집 (비어있으면 건너뜀)
- col_offset+1 열: 댓글 수집 (비어있으면 건너뜀)
- 반환: `(links: [str, ...], comments: [str, ...])`

### 병렬 스크래핑 (`scrape_all_urls_parallel`)
- 전체 블록에서 고유 URL 추출
- `ThreadPoolExecutor(max_workers=4)`로 브라우저 4개 동시 실행
- 각 워커: `create_driver()` → `scrape_comments()` → `driver.quit()`
- 결과: `{ url: [댓글텍스트, ...] }` 캐시

### 댓글 스크래핑 (`scrape_comments`)
1. URL 접속 → `mainFrame` iframe 전환
2. `a._cmtList` 클릭으로 댓글 목록 펼치기
3. `.u_cbox_comment_box` 로드 대기
4. `expand_all_comments()`: 더보기 버튼 최대 30회 반복 클릭
5. 댓글 텍스트 추출: `.u_cbox_contents` 등 다중 셀렉터 시도

### 매칭 로직
- **정규화**: 공백 전부 제거 (`re.sub(r'\s+', '', text)`)
- **10자 이상 연속 부분 일치** (`has_common_substring`): 슬라이딩 윈도우
- 10자 미만 댓글은 전체 일치로 판단
- **중복**: 매칭 2회 이상 → `중복(N회)`
- **누락**: 매칭 0회 → `○`
- **미등록**: 블로그 댓글 중 시트 어떤 기대 댓글과도 매칭 안 되는 것 → 내용 기록

### 결과 기록 (`build_block_output`)
- 링크별 묶음: 링크 → 댓글 결과(중복/누락) → 미등록 댓글 내용
- 시트 크기 자동 확장 후 `batch_clear` → `batch_update`

### Selenium 설정
- headless 모드, 안티디텍션 (webdriver 속성 숨김, automation 스위치 제거)
- `webdriver_manager`로 ChromeDriver 자동 관리
- credentials: `../manuscript_generator/credentials.json`

## 의존성
- `gspread`, `google-auth` (구글 시트)
- `selenium`, `webdriver_manager` (브라우저 자동화)
- `concurrent.futures` (병렬 처리, 내장)

## 실행 방법
```bash
cd "C:\Users\iamhy\Desktop\프로그램 개발\댓글검수"
python main.py
```

## 개발 이력
| 날짜 | 내용 |
|------|------|
| 2026-03-20 | v1.0 초기 개발: 중복/누락 검수 + 미등록 댓글 탐지 |
| 2026-03-20 | v2.0 입력 방식 변경: 독립 목록 + 5블록 + 자동 묶음 재배치 |
| 2026-03-20 | v2.1 병렬 스크래핑(브라우저 4개) + 시트 자동 확장 + 탭명 변경 |

## 알려진 이슈 / 개선 가능
- 대댓글은 일반 댓글과 함께 수집됨 (분리 미구현)
- 네이버 블로그만 지원 (카페/티스토리 미지원)
- 브라우저 풀 재사용으로 추가 속도 개선 가능 (현재 매 URL마다 생성/종료)
