# 🔗 개별 HANDOFF — 자동 연쇄 실행 (2026-03-20)

> **작업 요약**: Step 1/2/4에서 불필요한 클릭을 줄이기 위해 자동 연쇄 실행 추가

---

<br>

## 📝 변경 파일

| 파일 | 변경 |
|:-----|:-----|
| `원고배정\main.py` | 3곳 수정 + 1개 메서드 추가 |

---

<br>

## 🔧 변경 내용

### 1. Step 1 — 시트 기입 후 자동 발행리스트 불러오기

**위치**: `_write_plan_to_sheet` → worker 완료 부분 (기존 ~738행)

```python
# 기입 완료 후 자동으로 발행리스트 불러오기
self.root.after(500, self._load_publish_data)
```

- 기입 성공 시에만 실행 (오류/경고 시 실행 안 됨)
- 0.5초 딜레이로 시트 반영 여유

---

### 2. Step 2 — 진입 시 자동 매칭+검수

**위치**: `_build_step2` 마지막 (기존 ~873행)

```python
# Step 2 진입 시 자동으로 매칭+검수 실행
self.root.after(100, self._match_and_review)
```

- UI 렌더링 완료 후 100ms 뒤 실행
- 수동 재실행 버튼 유지

---

### 3. Step 4 — 배정 실행 후 자동 시트 기입

**위치**: `_execute_assignment` → worker 완료 부분 (기존 ~1552행)

```python
# 배정 완료 후 자동으로 시트 파라미터 + 키워드 시트 기입
if param_updates:
    self.root.after(500, lambda: self._auto_update_sheets())
```

### 4. 신규 메서드 `_auto_update_sheets`

**위치**: `_update_sheet_dates` 바로 위에 추가

- 확인 팝업 없이 순차 실행:
  1. `update_publish_parameters()` — 시트 파라미터
  2. `time.sleep(3)` — 수식 반영 대기
  3. `update_keyword_sheet()` — 키워드 시트 기입
- 각 단계 로그 출력, 오류 시 개별 처리
- 완료 후 `exec_progress_var` = "모든 작업 완료"

---

<br>

## ⚠️ 주의사항

- `_auto_update_sheets`는 확인 팝업 **없음** — 배정 실행 확인에서 이미 승인된 것으로 간주
- 기존 `_update_sheet_dates`, `_update_keyword_sheet` 메서드는 **수동 버튼용으로 유지** (확인 팝업 있음)
- `param_updates`가 비어있으면 자동 시트 기입 자체를 건너뜀
