# 🔧 Handoff — v2.0 개별 글 URL + 2단계 최적화 (2026-03-23)

---

## 📋 작업 요약

| 항목 | 내용 |
|------|------|
| 버전 | v1.0 → v2.0 |
| 파일 | `댓글알림\main.py` |
| 목적 | 블로그 전체 → 개별 글 URL 모니터링으로 변경, 속도 최적화 |

---

## 🔨 변경 사항

### 1. 블로그 전체 → 개별 글 URL 모니터링

**Before (v1.0):**
```python
config = {"blogs": ["hea1thyman", "eunji_unni"], ...}
# 블로그의 모든 글을 매번 전체 스크래핑 → 1500개 글 = 100분+
```

**After (v2.0):**
```python
config = {"posts": ["https://blog.naver.com/hea1thyman/224195244604", ...], ...}
# 개별 글 URL 등록, blog_id별 그룹핑하여 API 최적화
```

- `parse_post_url(url)` 함수 추가: URL → blog_id, log_no 파싱
- config 키: `blogs` → `posts`

### 2. 2단계 최적화 (API → Selenium)

**Before:** 모든 글을 매번 Selenium으로 스크래핑

**After:**
```
1단계: PostTitleListAsync API → commentCount 조회 (수 초)
2단계: 댓글 수 증가한 글만 Selenium 스크래핑 (필요할 때만)
```

- `_fetch_comment_counts(blog_id)` 메서드 추가
- `check_all()` 전면 재작성: API 변동 감지 → 변동 글만 스크래핑

### 3. 첫 실행 시 API만으로 기준점 저장

**Before:** 첫 실행에 전체 글 Selenium 스크래핑 (31분+)

**After:** API commentCount만 저장, Selenium 안 씀 (8초)

- `▶ 모니터링 시작` 클릭 시 `comment_counts`와 `seen` 초기화
- 첫 check_all()에서 API 기준점만 저장 후 종료

### 4. 대량 URL 추가 기능

- `대량 추가` 버튼 → 팝업(ScrolledText)에서 여러 줄 URL 붙여넣기
- `re.findall(r'https?://blog\.naver\.com/[^\s,]+', raw)` 로 URL 자동 추출
- 중복 자동 제거

### 5. Chrome 탭 크래시 해결

- `driver.set_page_load_timeout(15)` 추가
- sleep 시간 단축: 2초→1초, 1초→0.5초
- 10개마다 드라이버 자동 재시작
- `--single-process` 제거 (불안정 유발)
- 안정성 옵션 추가: `--disable-background-networking`, `--disable-renderer-backgrounding`

### 6. 체크 간격 변경

- 30분 → **15분** (`config.json`의 `interval_minutes`)

### 7. GUI 변경

- 블로그 목록 → 글 URL 목록으로 변경
- 버튼 추가: `대량 추가`, `전체 삭제`
- 리스트 `selectmode="extended"` (다중 선택 삭제)
- 등록 개수 표시 라벨 추가

---

## ⚠️ 주의사항

- `config.json`에 이미 저장된 값은 코드 기본값보다 우선됨
  - 예: 코드에서 15분으로 바꿔도 기존 config가 30분이면 30분 적용
  - config.json을 직접 수정하거나 삭제 후 재생성 필요

---

## 📊 성능 비교

| 시나리오 | v1.0 | v2.0 |
|----------|------|------|
| 첫 실행 (1500개 글) | 100분+ | **8초** |
| 이후 (변동 없음) | 100분+ | **~2초** |
| 이후 (변동 3개) | 100분+ | **~20초** |
