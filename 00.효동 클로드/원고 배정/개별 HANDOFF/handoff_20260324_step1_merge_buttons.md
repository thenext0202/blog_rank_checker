# 🔧 개별 HANDOFF — Step 1 버튼 통합 + Step 4 자동 시트 기입

> **날짜**: 2026-03-24
> **파일**: `원고배정\main.py`

---

## 📝 작업 내용

### 1. Step 1: "시트에 기입" + "발행리스트 불러오기" → 하나로 통합

**변경한 함수/UI:**

| 항목 | 이전 | 이후 |
|:-----|:-----|:-----|
| 버튼 | "시트에 기입", "발행리스트 불러오기" 2개 | "시트 기입 + 불러오기" 1개 |
| 메서드 | `_write_plan_to_sheet()` | `_write_plan_and_load()` |
| 건수 0 동작 | "1건 이상 입력하세요" 팝업 | `_load_publish_data()` 바로 호출 |
| 기존 데이터 | 경고 팝업 → 중단 | `askyesno` 확인 → "예" 시 불러오기 |

**코드 위치:**
- `_build_step1()` — 버튼 UI 변경 (plan_btn_frame)
- `_write_plan_and_load()` — 새 메서드 (기존 `_write_plan_to_sheet` 대체)

### 2. Step 4: 배정 실행 후 항상 시트 자동 기입

**변경:**
```python
# _execute_assignment() 내부, worker 끝부분
# 이전:
if param_updates:
    self.root.after(500, lambda: self._auto_update_sheets())

# 이후:
self.root.after(500, lambda: self._auto_update_sheets())
```

→ `param_updates`가 비어있어도 `_auto_update_sheets()`가 호출되어 키워드 시트 기입까지 진행.

---

## ⚠️ 주의사항

- `_write_plan_to_sheet()` 메서드는 삭제됨 → `_write_plan_and_load()`로 완전 대체
- 기존 데이터가 있을 때 `askyesno`에서 "아니오" 누르면 아무 동작 없이 멈춤
- `_auto_update_sheets()`는 내부에서 `if param_updates:` 조건이 있어 param 없으면 파라미터 업데이트 스킵, 키워드 시트만 진행
