# 🔧 개별 HANDOFF — v2.2 비공개 조치 감지

> **날짜:** 2026-03-23
> **버전:** v2.1 → v2.2
> **작업:** 비공개 조치 감지 + 댓글 누락 버그 수정

---

## 📋 작업 요약

| 항목 | 내용 |
|------|------|
| **요청** | 블로그 글이 비공개 조치되면 Slack 알림 |
| **패턴** | 정부기관 요청에 의한 비공개 조치 (식약처, 방통위 등) |
| **부수 수정** | 댓글 수 조회 실패 시 새 댓글 놓치는 버그 수정 |

---

## 🔨 변경 내용

### 1. 메서드 변경

| 변경 전 | 변경 후 | 역할 |
|---------|---------|------|
| `_fetch_comment_count_direct()` → `int or None` 반환 | `_fetch_comment_count_direct()` → `(int or None, private_info or None)` 반환 | 댓글 수 + 비공개 감지 동시 처리 |
| *(없음)* | `_fetch_private_detail()` 신규 | 데스크톱 PostView에서 요청기관/일자 상세 조회 |
| *(없음, v2.2 중간에 존재했다 제거)* | `_check_private_post()` → `_fetch_private_detail()`로 변경 | 네이밍 정리 |

### 2. `_fetch_comment_count_direct()` 변경

**모바일 페이지에서 2가지를 동시에 추출:**
```python
# 비공개 조치 감지 (모바일 패턴)
pm = re.search(r'(.+?)의\s*요청에\s*따라\s*비공개\s*조치', html)

# commentCount 추출 (기존)
cm = re.search(r'commentCount="(\d+)"', html)

return cc, private_info  # 튜플 반환으로 변경
```

**모바일 비공개 패턴:**
```
본 게시물은 정보통신서비스 제공자로서의 법적 의무를 준수하기 위해
식품의약품안전처의 요청에 따라 비공개 조치 되었음을 안내 드립니다.
```

### 3. `_fetch_private_detail()` 신규

**데스크톱 PostView 페이지** (`blog.naver.com/PostView.naver?blogId=...&logNo=...`)에서:
- 요청기관 추출
- 요청 일자 추출 (`YYYY.MM.DD` 형식)

**데스크톱 비공개 패턴:**
```html
<strong>이 게시물은 식품의약품안전처의 요청으로 비공개 조치 되었습니다.</strong>
...
<th>요청기관</th><td>식품의약품안전처</td>
<th>요청 일자</th><td>2026.03.12.</td>
```

### 4. `check_all()` 변경

```python
# 변경 전
cc = self._fetch_comment_count_direct(blog_id, log_no)

# 변경 후
cc, private_info = self._fetch_comment_count_direct(blog_id, log_no)

# 비공개 감지 시 → 데스크톱 상세 조회 → Slack 알림
if private_info and key not in alerted_private:
    detail = self._fetch_private_detail(blog_id, log_no)
    ...
    self.send_slack(msg)
    alerted_private[key] = {...}

# 댓글 수 조회 실패 + 비공개 아닌 글 → Selenium 강제 확인
if key in cc_failed_keys and key in seen:
    to_scrape.append((blog_id, log_no, url, 0))
```

### 5. state 변경

`comment_state.json`에 `alerted_private` 키 추가:
```json
{
  "seen": {...},
  "comment_counts": {...},
  "alerted_private": {
    "blogId_logNo": {
      "agency": "식품의약품안전처",
      "date": "2026.03.12",
      "detected_at": "2026-03-23 18:30:00"
    }
  }
}
```

모니터링 시작 시 `alerted_private = {}` 초기화.

---

## 🔑 핵심 발견

1. **모바일 vs 데스크톱 패턴이 다름**
   - 모바일: `"~의 요청에 따라 비공개 조치 되었음을 안내 드립니다"`
   - 데스크톱: `"이 게시물은 ~의 요청으로 비공개 조치 되었습니다"`
   - 요청 일자는 데스크톱에만 있음

2. **비공개 글 = commentCount 없음**
   - 비공개 조치된 글의 모바일 페이지에는 `commentCount` 속성이 존재하지 않음
   - 이것이 댓글 누락 버그의 원인이었음 (cc=None → 이전 값 대체 → 변동 없음 판정)

3. **참고 비공개 글:** `https://blog.naver.com/skyhealthinfo/224161198440`

---

## ⚠️ 주의사항

- 모바일 정규식 `(.+?)의\s*요청에\s*따라\s*비공개\s*조치` — 네이버가 문구 변경 시 수정 필요
- `alerted_private`는 모니터링 재시작 시 초기화됨 (의도된 동작)
- 댓글 수 조회 실패 글의 Selenium 강제 확인은 `seen`에 기록이 있는 글만 (첫 실행 제외)
