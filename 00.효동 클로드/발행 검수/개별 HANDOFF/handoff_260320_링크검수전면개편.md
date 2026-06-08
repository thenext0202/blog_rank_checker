# 🔧 Handoff — 링크 검수 전면 개편 (v1.5)

> 📅 2026-03-20
> 📁 `발행검수\main.py`

---

## 🎯 요청 사항

기존 링크 검수가 부정확 → 각 MKT 링크마다 3가지를 알려달라:
1. **접속 가능 여부** (HTTP 접속 확인)
2. **원고 링크와 동일한 주소인지** (상품/광고 매칭)
3. **삽입 위치** (이미지 / 텍스트 / 배너)
4. MKT 링크는 **중복이더라도 전부** 표시

---

## 🛠️ 변경 내용

### 1. MKT 링크 전체 수집 — `scrape_blog()` step 6 추가

기존 step 1~3은 `seen` set으로 중복 제거 → MKT 링크 중복 표시 불가

**새 step 6**: JS로 블로그 내 모든 `<a>` 태그를 탐색, MKT 링크를 **중복 포함** 전부 수집

```javascript
// 삽입 위치를 DOM 구조로 자동 분류
a.closest('.se-module-oglink, .se-section-oglink')  → 배너
a.closest('.se-component.se-image')                  → 이미지 (N번째)
그 외                                                → 텍스트
```

반환: `blog_info["all_mkt_links"]` = `[{url, placement, image_index, image_total}, ...]`

### 2. 링크 접속 확인 — `_check_link_accessible()` 신규 함수

```python
def _check_link_accessible(url):
    """HEAD → 실패 시 GET → (accessible: bool, final_url: str)"""
```

### 3. 링크 매칭 3단계 — `check_publication()` 섹션 5 전면 교체

기존 `_link_found_in_blog()` 방식 (리다이렉트 URL 비교) → **부정확**

| 단계 | 비교 방식 | 용도 |
|------|----------|------|
| **1차** | 전체 URL 비교 (쿼리 파라미터 포함, `_mkt_full()`) | 상품/광고 **정확 구분** |
| **2차** | MKT ID만 비교 (`/link/ABC123` 경로) | 블로거가 파라미터 변경한 경우 |
| **3차** | 최종 리다이렉트 URL 비교 (`_normalize_url()`) | non-mkt 기대 링크용 |

```python
def _mkt_full(url):
    """percent-decode → 쿼리 파라미터 정렬 → 정규화"""

def _mkt_id(url):
    """mkt.shopping.naver.com/link/[ID] 에서 ID 추출"""
```

**핵심 수정**: `if/elif` → 독립 `if/if` 구조
- 상품/광고 링크가 같은 MKT ID를 공유하는 경우가 실제로 있음
- 기존: 상품이 먼저 매칭되면 광고는 절대 매칭 안 됨
- 수정: 둘 다 독립적으로 매칭 → `상품/광고` 표시

### 4. 링크 목록 표시 — `_show_detail()` 업데이트

**기존**: `[위젯] https://mkt...` (중복 제거)

**변경**: `[이미지 3/15번째] [접속OK] [상품링크] https://mkt...` (중복 포함, 3가지 정보)

하단에 원고 기대 링크(시트)도 함께 표시:
```
── 원고 링크 (시트) ──
  상품: https://mkt...
  광고: https://mkt...
```

### 5. 모바일 URL 대응 — `scrape_blog()` URL 패턴

```python
# 수정 전: m.blog.naver.com 미인식
re.match(r"https?://blog\.naver\.com/...")
# 수정 후:
re.match(r"https?://(?:m\.)?blog\.naver\.com/...")
```

---

## 🐛 디버깅 과정에서 발견한 이슈들

| 이슈 | 원인 | 해결 |
|------|------|------|
| `m.blog.naver.com` URL에서 링크 수집 0건 | PostView 변환 regex가 모바일 URL 미인식 | `(?:m\.)?` 추가 |
| 리다이렉트 URL 비교 불일치 | mkt 리다이렉트 결과가 환경에 따라 다름 | MKT ID 직접 비교로 전환 |
| 상품/광고 같은 MKT ID → 광고 미삽입 | `if/elif` 구조에서 상품이 먼저 매칭 | 독립 `if/if`로 변경 |
| 쿼리 파라미터 `_hc` vs `_hc01` 구분 필요 | MKT ID만으로는 상품/광고 구분 불가 | 전체 URL 비교를 1차로, MKT ID를 2차 fallback으로 |

---

## 📦 관련 파일 변경

- `main.py` import: `parse_qsl`, `urlencode` 추가
- `EMPTY_BLOG` dict: `all_mkt_links`, `link_results` 필드 추가
- `blog_info["link_results"]`: `check_publication()`에서 생성 → `_show_detail()`에서 표시

---

## ⚠️ 남은 사항

| 우선순위 | 내용 |
|---------|------|
| 🟡 중간 | `_check_link_accessible()` 캐싱은 건 단위 — 전체 검수 건에 걸친 글로벌 캐시 없음 |
| 🟡 중간 | 기존 step 1~3 링크 수집 로직 (dedup) 은 아직 남아있음 (미사용 but 잔존) |
| 🟢 낮음 | `_link_found_in_blog()`, `_is_shop_candidate()` 등 미사용 함수 정리 |
