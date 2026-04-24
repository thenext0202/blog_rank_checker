# 🔧 개별 HANDOFF — v1.0 이미지 제너레이터 초기 구축

> **날짜:** 2026-03-26
> **버전:** v1.0 (신규)
> **작업:** manuscript_generator_v2에서 이미지 기능 분리 → 독립 프로그램

---

## 📋 작업 요약

| 항목 | 내용 |
|------|------|
| **배경** | v2에서 이미지를 먼저 선택 → 원고가 이미지에 맞춰져 부자연스러움 |
| **결정** | 원고 먼저 생성 → 원고 기반 이미지 선택/변형으로 흐름 변경 |
| **방법** | v2에서 이미지 관련 모듈만 분리하여 독립 프로그램 구축 |

---

## 🔨 변경 내용

### 1. 새 폴더 생성: `image_generator/`

v2에서 복사한 모듈:
| 파일 | 역할 | 수정 여부 |
|------|------|-----------|
| `lib_common.py` | API/시트/드라이브 | 그대로 |
| `image_metadata.py` | 메타데이터 저장소 | 그대로 |
| `image_selector.py` | 이미지 선택 엔진 | 그대로 (향후 확장용) |
| `image_transformer.py` | 맥락 추출/변형 | 그대로 |
| `credentials.json` | 서비스 계정 | manuscript_generator에서 복사 |

### 2. 신규 작성: `main.py` (560줄)

**GUI 구조 (tkinter):**
- 상단 바: Claude/OpenAI API Key + 이미지 시트 연결
- 좌측: 원고 입력 (직접 입력 / .txt / .docx) + 제품 드롭다운
- 우측: 이미지 카드 스크롤 리스트

**핵심 로직:**

| 메서드 | 역할 |
|--------|------|
| `extract_image_numbers()` | 원고에서 이미지 번호 추출 (1번부터, 0번 제외) |
| `_analyze_bg()` | Claude 장면 추천 → 메타데이터 매칭 → 슬롯 구성 |
| `_render_cards()` | 이미지 카드 UI 전체 갱신 |
| `_build_card()` | 개별 카드 (썸네일 + 정보 + 수락/거절 버튼) |
| `_show_alternatives()` | 대체 이미지 5장 다이얼로그 + 프롬프트 변형 |
| `_accept_image()` | Drive에서 원본 다운로드 + 상태 확정 |
| `_save_all_bg()` | 폴더에 이미지 파일 + 원고.txt 저장 |

### 3. 이미지 중복 방지

```python
# 다른 슬롯에서 사용 중인 이미지 ID 수집
used_ids = set()
for n, s in self.image_slots.items():
    if s["entry"] and s["entry"].get("drive_file_id") and n != img_num:
        used_ids.add(s["entry"]["drive_file_id"])
```

자동 제안, 대체 이미지 검색 모두 `used_ids`로 중복 차단.

### 4. 파일 입력 지원

| 형식 | 처리 |
|------|------|
| `.txt` | `open()` + UTF-8 읽기 |
| `.docx` | `python-docx`로 `para.text` 추출 |
| 직접 입력 | 텍스트 영역에 붙여넣기 |

---

## ⚠️ 주의사항

- `image_selector.py`는 복사했지만 현재 `main.py`에서 직접 import하지 않음 (자체 매칭 로직 사용)
- v2의 `main.py`는 수정하지 않음 — 기존 이미지 선택 기능 그대로 유지
- `lib_common.py`의 Claude 모델이 `claude-sonnet-4-20250514`로 고정됨

---

## 🧪 테스트

- [x] 프로그램 실행 정상 확인
- [ ] 실제 원고로 이미지 자동 제안 테스트 (이미지 시트 연결 필요)
- [ ] 대체 이미지 선택 + 프롬프트 변형 테스트
- [ ] 최종 저장 (폴더 출력) 테스트
