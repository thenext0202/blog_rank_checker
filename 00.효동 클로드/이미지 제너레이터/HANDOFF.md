# 🖼️ 이미지 제너레이터 — HANDOFF

> **날짜:** 2026-03-26
> **상태:** ✅ v1.0 기본 기능 완성
> **경로:** `C:\Users\iamhy\Desktop\프로그램 개발\image_generator\main.py`

---

## 📋 프로그램 개요

| 항목 | 내용 |
|------|------|
| **목적** | 완성된 원고를 기반으로 이미지를 자동 제안/선택/변형 |
| **핵심 원칙** | 원고 먼저 → 이미지는 원고에 맞춰 (이미지가 원고를 제한하지 않도록) |
| **입력** | 원고 텍스트 (직접 입력 / .txt / .docx 불러오기) |
| **출력** | 폴더에 원고.txt + 이미지 파일 (1.png, 2.png...) |
| **GUI** | tkinter — 좌우 분할 (왼쪽: 원고, 오른쪽: 이미지 카드) |
| **API** | Claude (장면 추천/적합도 분석) + OpenAI gpt-image-1 (이미지 변형/생성) |

---

## 📁 폴더 구조

```
image_generator/
├── main.py              ← 메인 GUI (v1.0)
├── lib_common.py        ← API/시트/드라이브 연결
├── image_metadata.py    ← 메타데이터 저장소/썸네일 캐시
├── image_selector.py    ← 이미지 선택 엔진
├── image_transformer.py ← AI 적합도 분석/이미지 변형/생성
├── credentials.json     ← Google 서비스 계정
├── image_cache/         ← 썸네일 로컬 캐시
└── output/              ← 기본 출력 폴더
```

---

## 🔄 이미지 선택 흐름

```
원고 입력 → 제품 선택 → "이미지 자동 제안" 클릭
                ↓
    Claude가 각 이미지 위치(1번~) 맥락 분석
                ↓
    메타데이터 시트에서 장면/분위기 매칭 → 카드 표시
                ↓
    ┌─── 수락 → 확정 (Drive에서 원본 다운로드)
    │
    └─── 다른 이미지 보기
              ↓
         대체 이미지 5장 표시
              ├── 5장 중 선택 → 바로 교체
              └── 프롬프트 직접 입력 → AI 변형 (OpenAI)
                ↓
    "최종 저장" → 폴더에 1.png, 2.png... + 원고.txt
```

---

## ✅ 완료된 작업

### 1. 독립 프로그램 생성 — 완료 (v1.0, 2026-03-26)
- `manuscript_generator_v2`에서 이미지 관련 코드를 분리하여 독립 프로그램으로 구성
- 기존 모듈 재사용: `lib_common.py`, `image_metadata.py`, `image_selector.py`, `image_transformer.py`
- 원고 제작기(main.py)와 완전 독립 — 별도 실행

### 2. 원고 기반 이미지 제안 — 완료
- 원고에서 이미지 번호 자동 감지 (1번부터, 0번 대표이미지 제외)
- Claude API로 각 위치의 앞뒤 맥락 분석 → 장면/분위기 추천
- 이미지 메타데이터 시트에서 매칭 (키워드 점수 + mood 가산점)
- 중복 방지: `used_ids` 세트로 같은 이미지 재사용 차단

### 3. 대체 이미지 + AI 변형 — 완료
- 거절 시 대체 이미지 5장 표시 (장면 매칭 → 제품 폴백 → 공통 폴백)
- 대체 이미지 선택 시 바로 교체 + 수락 처리
- 프롬프트 직접 입력 → OpenAI gpt-image-1으로 변형/생성
- 참조 이미지 있으면 `transform_image()`, 없으면 `generate_image()`

### 4. 파일 입출력 — 완료
- 입력: .txt / .docx 불러오기 + 직접 입력
- 출력: 폴더에 이미지 파일 (번호.확장자) + 원고.txt
- 미확정 이미지는 저장 시 확인 후 자동 저장

---

## 🔗 의존성

| 모듈 | 출처 | 역할 |
|------|------|------|
| `lib_common.py` | manuscript_generator에서 복사 | 시트/드라이브/Claude API 연결 |
| `image_metadata.py` | manuscript_generator에서 복사 | 이미지 메타데이터 로딩/검색/썸네일 |
| `image_selector.py` | manuscript_generator에서 복사 | 이미지 선택 엔진 (현재 직접 사용 안 함, 향후 확장용) |
| `image_transformer.py` | manuscript_generator에서 복사 | 맥락 추출/적합도 분석/이미지 변형 |
| `credentials.json` | manuscript_generator에서 복사 | Google 서비스 계정 |

### 외부 패키지
- `anthropic` — Claude API
- `openai` — OpenAI 이미지 API
- `gspread`, `google-auth` — Google Sheets
- `google-api-python-client` — Google Drive
- `python-docx` — DOCX 읽기
- `Pillow` — 썸네일 리사이즈

---

## 🔮 향후 작업 (미정)

- 전체 수락/거절 일괄 버튼
- 이미지 미리보기 (변형 결과 카드에 표시)
- EXE 빌드/배포
- 이미지 시트 자동 연결 (원고 제작기와 시트 ID 공유)
