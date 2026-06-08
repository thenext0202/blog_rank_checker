# 🔧 이미지번호 30 제한 + 기인정 기능

> **날짜**: 2026-03-24
> **파일**: `원고배정\main.py`

---

<br>

## 📋 작업 내용

### 1. 이미지 번호 오인식 수정
- **문제**: 원고 본문에 "2024", "100" 등 큰 숫자가 있으면 이미지 번호로 인식
- **해결**: `review_manuscript()` 내 `referenced_nums` 수집 시 `int(text) <= 30` 조건 추가
- **적용 위치**: 단독 숫자 매칭(`^\d+$`)과 나열 숫자 매칭(`^\d+[\s,、]+\d+`) 모두

### 2. 기인정 (수동 통과 영구 저장)
- **파일**: `MANUAL_PASS_FILE = manual_pass.json`
- **함수 추가**: `load_manual_pass()`, `save_manual_pass()`
- **저장 시점**: `_manual_pass()` → 수동 통과 시 폴더명 JSON 추가
- **복원 시점**: Step 2 `_review()` 내부 → 검수 실패 + JSON 존재 → `passed=True`, `pre_approved=True`
- **표시**: `_display_step2()` → `pre_approved` 시 "기인정", 아니면 "통과"

---

<br>

## 🔀 변경된 코드 위치

| 위치 | 변경 |
|:-----|:-----|
| 상수 선언부 | `MANUAL_PASS_FILE` 추가 |
| `review_manuscript()` | 이미지 번호 수집 시 `<= 30` 조건 |
| 함수 추가 | `load_manual_pass()`, `save_manual_pass()` |
| `_run_step2()` worker | `saved_pass` 로드 → 검수 후 기인정 적용 |
| `_display_step2()` | `pre_approved` → "기인정" 표시 |
| `_manual_pass()` | 통과 시 JSON 저장 추가 |

---

<br>

## ⚠️ 참고
- `manual_pass.json`은 배정 완료 후에도 항목이 남음 (매칭 안 되므로 무해)
- 정리 필요 시 사용자가 요청하면 수동 정리 또는 자동 정리 기능 추가
- 이미지 상한 30은 하드코딩 — 변경 필요 시 `review_manuscript()` 내 수정
