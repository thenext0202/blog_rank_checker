# 🔧 Handoff — 위젯/이미지 링크 분류 수정 (v1.4)

> 📅 2026-03-20
> 📁 `발행검수\main.py`

---

## 🐛 문제 현상

mkt 링크의 삽입 위치 표시가 **반대로** 나옴:

| 표시 결과 | 실제 위치 |
|-----------|----------|
| `[이미지]` | ❌ 실제로는 **위젯**(oglink) |
| `[위젯]` | ❌ 실제로는 **이미지** |

---

## 🔍 원인

> oglink 위젯의 `<a>` 태그 안에 **썸네일 `<img>`** 가 포함되어 있음

```
step 1: 블로그 전체 <a> 태그 스캔
  → oglink 위젯의 <a> 안에 <img> 발견
  → has_img = True
  → image_links에 잘못 추가됨

_show_detail()에서:
  → image_links(2순위) > widget_links(3순위)
  → 위젯 링크가 [이미지]로 표시됨
```

---

## 🛠️ 수정 내용 (3곳)

### 1. `_add_link()` — 오분류 제거

```python
# widget으로 확인되면 image_links에서 제거
elif link_type == "widget":
    if href not in widget_links:
        widget_links.append(href)
    if href in image_links:        # ← 핵심
        image_links.remove(href)
```

### 2. `_show_detail()` — 우선순위 변경

```
수정 전: image_link_map → image_links → widget_links → 텍스트
수정 후: image_link_map → widget_links → image_links → 텍스트
```

### 3. `_link_found_in_blog()` — 반환 우선순위 변경

```
수정 전: image → widget → text → missing
수정 후: widget → image → text → missing
```

---

## ✅ 결과

- 위젯(oglink) 링크 → `[위젯]` 정확 표시
- 이미지 컴포넌트 링크 → `[이미지 N/M번째]` 정확 표시

---

## ⚠️ 남은 리스크

- `image_links.remove(href)`는 정확한 URL 문자열 매칭 의존 — URL 인코딩 차이 시 제거 실패 가능
- 근본 해결: step 1에서 oglink 영역 `<a>`를 아예 수집하지 않는 것이 더 견고
