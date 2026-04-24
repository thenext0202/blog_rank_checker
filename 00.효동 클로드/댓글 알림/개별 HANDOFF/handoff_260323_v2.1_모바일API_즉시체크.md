# 🔧 v2.1 — 모바일 API 전환 + 즉시 체크 버튼

> **날짜:** 2026-03-23
> **작업:** 댓글 수 조회 API 전환 + 즉시 체크 기능 추가 + 기본 주기 30분

---

## 📌 문제 상황

| 문제 | 원인 |
|------|------|
| 댓글 달아도 감지 안 됨 (정기/즉시 모두) | `PostTitleListAsync` API에 **해당 글이 목록에 아예 없음** |
| cbox API 시도 실패 | `"Wrong ticket"` 에러 — 네이버가 ticket 값 변경/차단 |
| 즉시 체크 기능 없음 | 30분 대기해야만 체크 가능 |

### 🔍 핵심 발견: PostTitleListAsync의 한계

```
블로그 eunji_unni의 PostTitleListAsync 결과:
- totalCount: 97개
- logNo 범위: 224222245417 ~ 224223232383
- 문제의 글: 224195180317 ← 이 범위 밖! 목록에 없음!
```

> **이 API는 블로그의 모든 글을 반환하지 않음.** 특정 글(오래된 글, 특수 카테고리 등)이 누락됨.
> 결과적으로 commentCount 자체를 조회할 수 없어서 변동 감지 불가.

---

## ✅ 해결: 모바일 페이지 commentCount 추출

### Before (PostTitleListAsync)
```
blog_id별 → PostTitleListAsync API (30개씩 페이지네이션)
→ 전체 글 목록의 commentCount 비교
→ 문제: 일부 글이 목록에서 누락됨
```

### After (모바일 페이지)
```
글 1개당 → m.blog.naver.com/{blogId}/{logNo} GET 요청
→ HTML에서 commentCount="숫자" 추출
→ 모든 글을 정확하게 조회 가능
```

### 모바일 페이지 응답 예시
```html
commentCount="22"
```

### 성능 비교

| 방식 | 49개 글 기준 | 장점 | 단점 |
|------|-------------|------|------|
| PostTitleListAsync | ~2초 (2~3회 호출) | 빠름 | **일부 글 누락** |
| 모바일 페이지 | ~25초 (49회 호출) | 모든 글 정확 | 상대적으로 느림 |
| cbox API | 실패 | - | ticket 에러 |

---

## ✅ 즉시 체크 버튼 추가

| 항목 | 내용 |
|------|------|
| **버튼** | `⚡ 즉시 체크` (모니터링 시작 버튼 옆) |
| **모니터링 ON** | 대기 중 타이머 취소 → 즉시 체크 → 다시 30분 타이머 |
| **모니터링 OFF** | 1회만 체크하고 끝 (반복 없음) |
| **중복 방지** | 체크 진행 중이면 클릭 무시 |

---

## ✅ 기본 주기 변경

| 항목 | Before | After |
|------|--------|-------|
| `interval_minutes` 기본값 | 15분 | **30분** |
| `config.json` 값 | 15 | **30** |

---

## 🔀 코드 변경 요약

| 파일 | 변경 |
|------|------|
| `main.py` | `_fetch_comment_counts()` 삭제 (PostTitleListAsync) |
| `main.py` | `_fetch_comment_count_direct()` 추가 (모바일 페이지) |
| `main.py` | `check_all()` — cbox/PostTitleList → 모바일 페이지 방식 |
| `main.py` | `_run_now()`, `_run_once()`, `btn_now` — 즉시 체크 UI/로직 |
| `main.py` | `interval_minutes` 기본값 15 → 30 |
| `config.json` | `interval_minutes` 15 → 30 |

### 삭제된 코드
- `_fetch_comment_counts(blog_id)` — PostTitleListAsync 호출 메서드
- `from collections import defaultdict` — blog_groups 그룹핑용 (불필요)
- `blog_groups` 변수 — blog별 그룹핑 로직

### 추가된 코드
```python
def _fetch_comment_count_direct(self, blog_id, log_no):
    """모바일 블로그 페이지에서 commentCount를 실시간 조회."""
    url = f"https://m.blog.naver.com/{blog_id}/{log_no}"
    # → HTML에서 commentCount="숫자" 추출
```

---

## 🔑 시도한 API 목록 (실패)

| API | 결과 |
|------|------|
| `apis.naver.com/commentBox/cbox/web_naver_list_jsonp.json` | `"Wrong ticket"` |
| `apis.naver.com/commentBox/cbox9/*` | `"API does not exist"` |
| `apis.naver.com/commentBox/blogid/*` | `"API does not exist"` |
| `blog.naver.com/NBlogRpcGetCommentList.naver` | HTML 리다이렉트 |
| `blog.naver.com/CommentCountAsync.naver` | HTML 리다이렉트 |
| `m.blog.naver.com/api/blogs/{id}/post/{logNo}` | 빈 응답 |
| **`m.blog.naver.com/{blogId}/{logNo}`** | ✅ **commentCount="숫자" 발견** |
