# 🔧 개별 HANDOFF — 이미지 변형 기능 추가

> 📅 2026-03-25
> 📁 작업 대상: `manuscript_generator_v2/` (manuscript_generator 복사본)

---

## 📋 작업 요약

기존 원고 제작기에 **이미지 변형 기능**을 추가.
원고 생성 후 이미지가 맥락과 맞지 않는 문제를 해결하기 위해,
Claude로 적합도 분석 → OpenAI로 이미지 변형/생성하는 파이프라인 구현.

---

## 📁 변경 파일

### 신규
| 파일 | 크기 | 역할 |
|------|------|------|
| `image_transformer.py` | ~7K | 이미지 변형 엔진 (분석+변형+프롬프트) |

### 수정
| 파일 | 변경 내용 |
|------|----------|
| `main.py` | OpenAI API Key 설정, [이미지 검토] 버튼, 검토 다이얼로그, save_as_docx 이미지 임베드 |
| `requirements.txt` | `openai` 추가 |

---

## 🔍 main.py 수정 상세

### 1. 상수/import 추가
- `OPENAI_KEY_FILE` — OpenAI API 키 저장 경로
- `HAS_TRANSFORMER` — image_transformer import 성공 여부
- `load_openai_key()` / `save_openai_key()` — 키 저장/로드

### 2. __init__ 수정
- `self.transformed_images = {}` 초기화 추가

### 3. 설정 탭 (탭2)
- "OpenAI API Key (이미지 변형)" LabelFrame 추가

### 4. 버튼 바
- `[이미지 검토]` 버튼 추가 (초기 disabled, 원고 생성 완료 시 활성화)

### 5. _on_review_images() — 이미지 검토 다이얼로그
- Toplevel 900x700 다이얼로그
- 상단: 분석 상태
- 중앙: 스크롤 가능 이미지 리스트 (썸네일 + 적합도 뱃지 + AI 제안)
- 하단: 사용자 추가 지시 입력 + [이미지 생성/변형] / [Word 저장] / [닫기]
- 백그라운드 스레드로 Claude 분석 + OpenAI 변형 실행

### 6. save_as_docx() 수정
- 시그니처: `save_as_docx(text, filepath, transformed_images=None)`
- 이미지 번호 처리 시 `transformed_images`에 해당 번호가 있으면 `doc.add_picture()` 임베드
- 없으면 기존대로 파란 숫자 표시

### 7. _on_save_docx() 수정
- `self.transformed_images` 전달

---

## 🔍 image_transformer.py 구조

```python
# 1. extract_image_contexts(manuscript_text, context_chars=150)
#    → [{index, before, after}, ...]

# 2. analyze_image_fit(api_key, manuscript_text, image_slots)
#    → [{slot_index, fit, reason, suggestion}, ...]
#    Claude에 JSON 형식 응답 요청

# 3. transform_image(openai_api_key, reference_image_bytes, prompt, size, quality)
#    → bytes (PNG)
#    OpenAI gpt-image-1 images.edit API

# 4. generate_image(openai_api_key, prompt, size, quality)
#    → bytes (PNG)
#    OpenAI gpt-image-1 images.generate API

# 5. build_transform_prompt(context_before, context_after, image_metadata,
#                           ai_suggestion, user_instruction)
#    → str (OpenAI 프롬프트)
```

---

## ⚠️ 미완료 / 알려진 이슈

1. **실제 API 테스트 미완료** — OpenAI 호출 검증 필요
2. **이미지 미리보기 미구현** — 변형 결과를 다이얼로그에서 바로 보여주는 기능 없음
3. **배치 모드 미연동** — 연속 생성 시 이미지 변형은 수동으로만 가능
4. **에러 핸들링 기본** — API 실패 시 간단한 오류 표시만

---

## 🔗 의존성

| 패키지 | 버전 | 용도 |
|--------|------|------|
| `openai` | latest | OpenAI gpt-image-1 API |
| `anthropic` | 기존 | Claude API (적합도 분석) |
| `python-docx` | 기존 | Word 이미지 임베드 |
