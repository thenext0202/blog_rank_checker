# 📋 개별 Handoff — 원고 폴더 열기 + 시트 기입 취소

> **날짜**: 2026-03-24
> **프로그램**: 원고 배정 프로그램 (`원고배정\main.py`)

---

<br>

## 🎯 작업 목표

1. Step 2에서 파일명 더블클릭 → 원고 폴더를 탐색기로 열기
2. Step 1 시트 기입 후 ~ Step 4 실행 전까지 시트 기입을 취소할 수 있는 버튼 추가

---

<br>

## 🔧 변경 내역

### 1. 원고 폴더 열기 (`_open_manuscript_folder`)

| 항목 | 내용 |
|:-----|:-----|
| 이벤트 | `<Double-1>` on `self.step2_tree` |
| 위치 | `_build_step2()` 내 바인딩 추가 |
| 로직 | `vals[4]` (파일명 컬럼) → `UNASSIGNED_PATH / folder_name` → `os.startfile()` |
| 폴더 없음 | `messagebox.showwarning` 팝업 |

### 2. 시트 기입 취소 (`_cancel_written_rows`)

| 항목 | 내용 |
|:-----|:-----|
| 버튼 | `self.cancel_write_btn` — 하단 nav bar (이전/다음 사이) |
| 초기 상태 | `disabled` |
| 활성화 | `_write_plan_and_load()` 기입 완료 시 |
| 비활성화 | 취소 완료 시 / Step 4 "작업 모두 취소" 완료 시 |

**취소 로직:**
```
1. self.written_rows (기입한 행 번호 리스트)
2. 역순 정렬 후 ws.delete_rows() (행 번호 밀림 방지)
3. written_rows = [], publish_data = {} 초기화
```

---

<br>

## 📝 변경한 코드 위치

| 변경 | 위치 |
|:-----|:-----|
| `self.written_rows = []` 초기화 | `__init__` |
| `cancel_write_btn` 생성 | `_build_ui()` 하단 nav bar |
| `written_rows` 기록 | `_write_plan_and_load()` worker 내 |
| `_open_manuscript_folder()` 메서드 | `_show_review_detail()` 바로 위 |
| `<Double-1>` 바인딩 | `_build_step2()` 내 |
| `_cancel_written_rows()` 메서드 | `_load_publish_data()` 바로 위 |
| `written_rows` 초기화 | `_rollback_assignment()` worker 내 |
