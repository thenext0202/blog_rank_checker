# 📋 이미지 기반 원고 제작기 — 전체 HANDOFF

> 📁 경로: `C:\Users\iamhy\Desktop\프로그램 개발\image_manuscript_generator\`
> 📁 v2 경로: `C:\Users\iamhy\Desktop\프로그램 개발\manuscript_generator_v2\` (이미지 변형 기능 추가)
> 📅 최종 업데이트: 2026-03-25
> 🏷️ 버전: v1.1 (image_manuscript_generator) + v2 (manuscript_generator + 이미지 변형)

---

## 🔎 프로그램 개요

### image_manuscript_generator (v1.1)
이미지를 **먼저 선택**하고, 선택된 이미지에 맞는 블로그 원고를 생성하는 tkinter GUI 프로그램.

```
이미지 메타데이터(시트) → 이미지 자동/수동 선택 → Claude가 이미지 설명 보고 원고 작성 → Word 출력
```

### manuscript_generator_v2 (신규 — 이미지 변형)
기존 원고 제작기(manuscript_generator)의 복사본에 **이미지 변형 기능** 추가.
원고 생성 후 이미지가 맥락과 안 맞으면 **AI로 변형**한다.

```
원고 생성 → Claude가 이미지 적합도 분석 → 안 맞는 이미지 표시
  → 사용자 확인/추가 지시 → OpenAI로 이미지 변형 → Word에 이미지 임베드
```

### 💡 세 프로그램 비교

| 항목 | 기존 (manuscript_generator) | image_manuscript_generator | manuscript_generator_v2 |
|------|---------------------------|--------------------------|------------------------|
| 순서 | 원고 먼저 → 이미지 번호만 | 이미지 먼저 → 이미지에 맞는 원고 | **원고 먼저 → 이미지 AI 변형** |
| 이미지 | 번호만 표시 | 메타데이터 기반 선택 | **선택 + AI 변형/생성** |
| Word 출력 | 이미지 번호만 | 이미지 번호만 | **실제 이미지 임베드** |
| API | Claude만 | Claude만 | **Claude + OpenAI** |

---

## 📁 파일 구조

### image_manuscript_generator/

```
image_manuscript_generator/
├── main.py              (48K) — GUI 앱 (4탭) + Word 출력 + 프롬프트 조립
├── lib_common.py        (33K) — 공용 함수 (시트/Drive/API/서식파싱/테마)
├── image_selector.py    (12K) — 이미지 선택 알고리즘 (AI추천+수동)
├── catalog_images.py     (9K) — Drive 스캔 + Claude Vision 자동 태깅
├── substitution.py      (10K) — 치환 모드 (파싱→장면추론→매칭→생성)
├── image_metadata.py     (6K) — 메타데이터 저장소 + 썸네일 캐시
├── requirements.txt
├── image_cache/          — 로컬 썸네일 캐시
└── output/              — 생성된 원고
```

### manuscript_generator_v2/ (신규 추가분)

```
manuscript_generator_v2/
├── (기존 manuscript_generator 전체 파일)
├── image_transformer.py  (7K) — ★ 신규: 이미지 변형 엔진
├── main.py              (수정) — 이미지 검토 다이얼로그 + save_as_docx 이미지 임베드
└── requirements.txt     (수정) — openai 추가
```

---

## 🧩 핵심 모듈 구조

### lib_common.py — 공용 함수 (기존 main.py에서 추출)

| 함수 | 역할 |
|------|------|
| `connect_sheet()` / `connect_drive()` | Google Sheets / Drive 연결 |
| `drive_list_files_recursive()` | Drive 폴더 재귀 탐색 |
| `drive_download_bytes()` | Drive 파일 → bytes (로컬 저장 없이) |
| `load_all_from_sheet()` | 기존 6탭 데이터 로딩 |
| `load_image_metadata_from_sheet()` | **이미지 메타데이터 탭** 로딩 |
| `call_claude_api()` | Claude API 스레드 호출 |
| `call_claude_vision_sync()` | **Claude Vision** 동기 호출 (이미지 분석, media_type 자동 감지) |
| `parse_annotation()` | ㄴ서식 파싱 |
| `build_persona_prompt()` / `build_title_prompt()` | 페르소나/제목 프롬프트 |

### image_metadata.py — 이미지 메타데이터 관리

| 클래스 | 역할 |
|--------|------|
| `ImageMetadataStore` | 시트에서 메타데이터 로딩, 필터링, 텍스트 검색 |
| `ThumbnailCache` | Drive 썸네일 로컬 캐시, tkinter PhotoImage 변환 |

### image_selector.py — 이미지 선택 엔진

| 클래스/메서드 | 역할 |
|--------------|------|
| `ImageSlot` | 이미지 슬롯 (번호, 역할, 메타데이터, 잠금 여부) |
| `ImageSelector.auto_select()` | **3단계 자동 선택**: 필수슬롯 → AI추천 → 폴백 |
| `ImageSelector.swap_image()` / `reorder()` | 수동 교체/순서 변경 |
| `build_image_sequence_prompt()` | **섹션 7-4** 프롬프트 생성 |
| `build_image_text_guidelines()` | **섹션 7-5** 프롬프트 생성 |

### substitution.py — 치환 모드

| 함수 | 역할 |
|------|------|
| `parse_original_manuscript()` | 원본 원고를 이미지 번호 기준으로 세그먼트 분리 |
| `get_context_around_images()` | 각 이미지 앞뒤 텍스트 50자 추출 |
| `infer_scenes()` | Claude로 각 이미지 위치의 장면 추론 |
| `match_images_for_substitution()` | 추론된 장면 → 대상 제품 메타데이터 매칭 |
| `build_substitution_prompt()` | 치환 프롬프트 생성 (7개 규칙 포함) |

### catalog_images.py — Drive 스캔 + AI 태깅

| 함수 | 역할 |
|------|------|
| `scan_drive_images()` | Drive 폴더 재귀 탐색 → 이미지 목록 |
| `infer_product_and_category()` | 폴더 경로에서 product/category 자동 추정 |
| `register_images()` | 시트에 신규 이미지 등록 (기존 ID 중복 제외, 시트 자동 확장) |
| `tag_images_with_vision()` | Claude Vision으로 scene/mood/tags 자동 생성 (맥락 프롬프트) |

### image_transformer.py — ★ 이미지 변형 엔진 (v2 신규)

| 함수 | 역할 |
|------|------|
| `extract_image_contexts()` | 원고에서 이미지 번호 앞뒤 150자 맥락 추출 |
| `analyze_image_fit()` | Claude로 원고 맥락 vs 이미지 메타데이터 적합도 판정 |
| `transform_image()` | OpenAI gpt-image-1로 참조 이미지 변형 |
| `generate_image()` | OpenAI로 새 이미지 생성 (참조 없이) |
| `build_transform_prompt()` | 원고 맥락 + AI 제안 + 사용자 지시 → 프롬프트 조합 |

---

## 📊 구글 시트 — 이미지 메타데이터 탭

기존 시트에 **"이미지 메타데이터"** 탭 추가:

| 컬럼 | 필드 | 설명 |
|------|------|------|
| A | `drive_file_id` | Drive 파일 고유 ID |
| B | `filename` | 표시용 파일명 |
| C | `product` | 제품명 또는 "공통" |
| D | `category` | 폴더 기반 자동 분류 (제품컷/논문/정보성/커뮤니티/타사제품/음식/인물 등) |
| E | `scene` | 장면 설명 (**AI 자동 생성**) |
| F | `mood` | 분위기 (따뜻한/불안한/밝은/일상적 등) |
| G | `position_hint` | hooking/opening/middle/closing/any |
| H | `tags` | 쉼표 구분 태그 |
| I | `drive_folder` | 원본 Drive 폴더명 |
| J | `thumbnail_url` | GUI 미리보기용 URL |

---

## 🖼️ 이미지 선택 알고리즘 (3단계)

```
1단계 — 필수 슬롯 (규칙 기반)
  ├─ 0번: 후킹 이미지 (position_hint=hooking)
  └─ 제품컷 2~3장 (category=제품컷, 중반~후반 배치)
       ↓
2단계 — AI 추천 + 메타데이터 매칭
  ├─ Claude에게 장면 추천 요청 (제품/키워드/유형 기반)
  └─ 추천 장면 → scene+tags 텍스트 매칭 → mood 가산점
       ↓
3단계 — 폴백
  └─ 매칭 실패 슬롯 → 공통 이미지 또는 빈 슬롯 (수동 선택)
```

---

## 🔄 생성 워크플로우

### 신규 생성 (5단계) — image_manuscript_generator

```
STEP 0: 입력 (제품/키워드/유형/스타일/톤/서식)
    ↓
STEP 1: 이미지 선택 (자동추천 + 수동브라우징, 수량 자유)
    ↓
STEP 2: 페르소나 생성 (Claude → 3개 → 자동선택)
    ↓
STEP 3: 제목 생성 (Claude → 3개 → 자동선택)
    ↓
STEP 4: 원고 생성 (이미지 시퀀스 포함 프롬프트)
```

### 치환 모드 (4단계)

```
STEP 0: 원본 입력 (DOCX/텍스트) + 대상 제품 선택
    ↓
STEP 1: 원본 분석 → 장면 추론 → 새 이미지 매칭
    ↓
STEP 2: 치환 생성 (Claude → 7개 규칙 적용)
    ↓
STEP 3: 후처리 + Word 저장
```

### 이미지 변형 워크플로우 (v2 신규)

```
원고 생성 완료 → [이미지 검토] 클릭
    ↓
[자동] Claude가 원고 맥락 vs 이미지 메타데이터 비교
    → 적합✅ / 불일치⚠️ 판정 + 변형 제안
    ↓
[수동] 사용자가 확인 + 추가 지시 입력
    예: "3개월차 컷 다시 만들어" / "클로즈업 2장 추가"
    ↓
OpenAI gpt-image-1로 이미지 변형/생성
    → 참조 이미지(Drive) + 프롬프트 → 새 이미지
    ↓
Word 저장 시 변형된 이미지 임베드 (doc.add_picture)
```

---

## 🖥️ GUI 구조

### image_manuscript_generator (4탭)

| 탭 | 기능 |
|----|------|
| 신규 생성 | 좌: 설정 패널 / 우: 이미지 프리뷰 그리드 / 하: 결과+저장 |
| 치환 모드 | 좌: 원본 입력 / 우: 치환 설정+이미지 매칭 / 하: 결과 |
| 설정 | API Key, Sheet ID, Drive 폴더 ID |
| 이력 | 생성 이력 (generation_log.json) |

### manuscript_generator_v2 (기존 + 추가)

| 추가 요소 | 위치 | 설명 |
|----------|------|------|
| OpenAI API Key | 설정 탭 | Claude Key 아래에 추가 |
| [이미지 검토] 버튼 | 버튼 바 | 원고 생성 후 활성화 |
| 이미지 검토 다이얼로그 | Toplevel 900x700 | 적합도 분석 + 변형 + Word 저장 |

---

## 📂 이미지 Drive 폴더 구조

```
이미지_라이브러리/
├── 제품컷/              — 8개 제품별 폴더 (자사제품 사진)
├── 공통/               — 11개 카테고리 (건물/동물/병원/음식/인물 등)
└── [제품별]/            — 논문/정보성/타사제품/커뮤니티/혈당측정 등
    ├── 글루코컷/        ├── 판토오틴/
    ├── 멜라토닌/        ├── 퓨어톤부스트/
    ├── 블러드싸이클/     ├── 헬리컷/
    ├── 상어연골환/       └── 활성엽산/
```

> 정리 완료: 12,208장 (원본 13,136장 - 휴지통 1,899장)
> 공통/병원에서 제품 관련 이미지 80장을 제품별 폴더로 재분류
> Drive 업로드 폴더 ID: `1n0VvYdwWw0xdEJV9tWyMtng5fEi7TXEG`
> 시트 ID: `1aBL2RsoiQhvUMhMNhdSc4qNtANIO8wwdJUZQynaz8Y4`

---

## 🛠️ 프롬프트 변경점 (기존 14섹션 대비)

| 변경 | 내용 |
|------|------|
| 삭제 | 섹션 7-3 (이미지 개수) — 이미지 목록에서 암묵적 결정 |
| **추가** | **섹션 7-4: 이미지 시퀀스** — 15장 이미지 설명 + 배치 순서 |
| **추가** | **섹션 7-5: 이미지-텍스트 연결 지침** — 5개 규칙 |

### 핵심 결정: 멀티모달(이미지 전송) ❌ → 메타데이터 텍스트 전송 ✅

- 이유: 15장 이미지 전송 시 ~24,000 토큰 ($0.12/건) vs 메타데이터 ~300 토큰 ($0.05/건)
- 건강 블로그 이미지는 텍스트 설명으로 충분히 표현 가능

---

## ⚙️ 기술 스택

```
Python 3 + tkinter GUI
├── anthropic (Claude Sonnet 4 API + Vision)
├── openai (gpt-image-1 — 이미지 변형/생성) ← v2 추가
├── python-docx (Word 파일 생성 + 이미지 임베드)
├── gspread + google-auth (Google Sheets)
├── googleapiclient (Google Drive)
├── Pillow (이미지 썸네일)
└── threading (비동기 API/Drive 호출)
```

---

## 📌 현재 상태 + 남은 작업

### ✅ 완료

- [x] 프로젝트 설계 (9섹션 상세 설계)
- [x] lib_common.py (기존 main.py에서 공용 함수 추출)
- [x] catalog_images.py (Drive 스캔 + AI 태깅)
- [x] image_metadata.py (메타데이터 저장소 + 썸네일 캐시)
- [x] image_selector.py (3단계 선택 알고리즘)
- [x] substitution.py (치환 모드)
- [x] main.py (4탭 GUI + 생성 워크플로우)
- [x] 이미지 폴더 정리 (12,208장 → Drive 업로드용 구조)
- [x] 공통/병원 제품별 재분류 (80장)
- [x] **save_as_docx 완전판** — manuscript_generator에서 완전판 이식 (v1.1)
- [x] **배치 모드 구현** — 키워드별 연속 생성 + 이미지 자동 선택 (v1.1)
- [x] **Drive 이미지 업로드 + 시트 등록** — 7,843개 등록 완료 (v1.1)
- [x] **catalog_images.py 개선** (v1.1)
- [x] **이미지 변형 기능** — manuscript_generator_v2에 구현 (2026-03-25):
  - `image_transformer.py` 신규 작성 (분석/변형/생성/프롬프트)
  - main.py에 이미지 검토 다이얼로그 추가
  - save_as_docx에 이미지 임베드 기능 추가
  - 설정 탭에 OpenAI API Key 입력 추가

### 🔲 남은 작업

- [ ] **이미지 변형 실제 테스트** — OpenAI API 호출 + 결과 품질 확인
- [ ] 이미지 변형 프롬프트 튜닝 (건강/의학 블로그 맞춤)
- [ ] AI 태깅 실행 (Sonnet 4, 7,843개, ~$60) — 5개 테스트 완료, 정확도 확인됨
- [ ] 태깅 결과 수동 보정 (제품명/논문 주제 등 AI 한계 부분)
- [ ] 테스트 원고 생성 → 프롬프트 튜닝
- [ ] EXE 빌드

---

## 🔧 v1.1 주요 변경 상세

### save_as_docx 완전판

manuscript_generator의 검증된 Word 저장 로직을 이식:

| 추가된 기능 | 설명 |
|------------|------|
| `pending_fmts` | ㄴ이 텍스트 위에 있는 경우에도 대기 후 적용 |
| 중간 ㄴ 서식 | `"텍스트 ㄴ '단어' 파란색"` 한 줄에 섞인 경우 처리 |
| `recent` 버퍼 | 다중 라인 서식을 정확한 문단에 적용 (최근 15개 추적) |
| `_add_blogger_request_box` | 빨간 테두리 + 노란 배경 테이블 박스 |
| `_apply_quote_border` | 인용구 왼쪽 컬러 테두리 |
| `_build_styled_segments` | 마크다운 + 색상 동시 처리 |

### 배치 모드

기존 원고 제작기와 동일한 UX + 이미지 자동 선택 추가:

```
[배치] 버튼 → 키워드 목록 입력 (| 구분자)
  → 키워드별: 이미지 자동 선택 → 페르소나(A) → 제목(A) → 원고 생성 → 자동 저장
  → 오류 시 건너뛰고 다음 키워드로 진행
```

### Vision 태깅 프롬프트 개선

```
이전: "이 이미지를 분석하여..." (이미지만 보고 판단)
변경: "이 이미지는 '{product}/{category}' 폴더, 파일명 '{filename}'입니다.
       이 맥락을 참고하여 분석하세요." (폴더/파일명 맥락 제공)
```

> Haiku Vision 테스트 → 정확도 매우 낮음 (모자이크 이미지도 추측으로 채움)
> Sonnet 4 + 맥락 프롬프트 → 정확도 대폭 향상 (5개 테스트 확인)
> Claude 3 Haiku는 Vision 미지원 (404 에러), Claude 3 Haiku(20240307)는 지원하나 품질 부족

### 이미지 시트 등록 현황

| 항목 | 수량 |
|------|------|
| 총 등록 | 7,843개 |
| 제품별 | 공통 2,964 / 판토오틴 1,807 / 활성엽산 764 / 상어연골환 619 / 글루코컷 514 / 블러드싸이클 361 / 헬리컷 238 / 퓨어톤부스트 170 / 멜라토닌 121 |
| product/category | 폴더 구조 기반 정확 분류 완료 |
| scene/mood/tags | 5개만 Sonnet으로 테스트 완료, 나머지 미실행 |

---

## 🔧 v2 이미지 변형 상세 (2026-03-25)

### 배경
- 기존 문제: 원고 생성 후 이미지가 원고 맥락과 맞지 않음
- 해결: 원고 생성 → 이미지 적합도 분석 → 안 맞는 이미지 AI 변형
- 기존 manuscript_generator를 `manuscript_generator_v2`로 복사하여 작업 (원본 보호)

### 구현 내용

| 항목 | 설명 |
|------|------|
| **자동 분석** | Claude가 원고 앞뒤 맥락 vs 이미지 메타데이터 비교 → 적합/불일치 판정 |
| **수동 지시** | 사용자가 프롬프트로 직접 지시 (예: "여자가 체중계 재는 모습") |
| **이미지 변형** | OpenAI gpt-image-1 API, 참조 이미지 + 프롬프트 → 새 이미지 |
| **이미지 생성** | 참조 없이 프롬프트만으로 새 이미지 생성도 가능 |
| **Word 임베드** | save_as_docx에서 변형된 이미지를 실제 doc.add_picture()로 삽입 |

### 비용

| 품질 | 1장당 | 비고 |
|------|-------|------|
| medium (기본) | ~$0.04 | 권장 |
| low | ~$0.01 | 대량 작업 시 |

---

## 📝 이력

| 날짜 | 변경 |
|------|------|
| 2026-03-25 | v2 — manuscript_generator_v2에 이미지 변형 기능 추가 (image_transformer.py + GUI + Word 임베드) |
| 2026-03-23 | v1.1 — save_as_docx 완전판, 배치 모드, 이미지 등록 7,843개, Vision 태깅 개선 |
| 2026-03-23 | v1.0 — 초기 개발 완료 (설계 + 6개 모듈 + 이미지 정리) |
