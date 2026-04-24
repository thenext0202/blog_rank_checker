# 🔧 개별 HANDOFF — v1.0 초기 개발 + 이미지 폴더 정리

> 📅 작업일: 2026-03-23
> 🏷️ 작업 범위: 프로젝트 설계 → 6개 모듈 개발 → 이미지 12,208장 정리

---

## 📌 이번 작업 요약

1. **상세 설계** (9섹션) — 이미지 메타데이터, 선택 알고리즘, 프롬프트 구조, 치환 모드, GUI 등
2. **6개 모듈 개발** — lib_common / image_metadata / image_selector / substitution / catalog_images / main
3. **이미지 폴더 정리** — 원본 13,136장 → 12,208장 (휴지통 제외) → Drive 업로드용 구조
4. **병원 이미지 재분류** — 공통/병원에서 제품별 키워드 매칭으로 80장 분류

---

## 🏗️ 설계 결정 사항

### 이미지 전송 방식
- ❌ 멀티모달 (실제 이미지 전송) → 15장 = ~24,000 토큰, $0.12/건
- ✅ **메타데이터 텍스트 전송** → 15장 = ~300 토큰, $0.05/건

### 이미지 메타데이터
- ✅ **Claude Vision AI 자동 태깅** → 사용자는 검토/수정만
- 구글 시트 "이미지 메타데이터" 탭으로 관리 (A~J 10개 컬럼)

### 이미지 선택
- ✅ **AI 자동 추천 + 수동 브라우징 둘 다 지원**
- 이미지 수량은 사용자가 자유 설정 (고정 15장 아님)

### 치환 모드 입력
- ✅ **DOCX + 텍스트 붙여넣기 둘 다 지원**

### Word 출력
- ✅ **이미지 번호만 표시** (기존 방식 유지, 이미지 직접 삽입 안 함)

---

## 📁 생성된 파일

```
image_manuscript_generator/
├── main.py              — GUI + Word출력 + 프롬프트 조립 (build_prompt_with_images)
├── lib_common.py        — 공용 함수 추출 (기존 main.py에서)
│   ├── connect_sheet/drive, drive_list_files_recursive, drive_download_bytes
│   ├── load_all_from_sheet, load_image_metadata_from_sheet
│   ├── call_claude_api, call_claude_vision_sync
│   ├── parse_annotation, is_format_annotation
│   └── build_persona_prompt, build_title_prompt, THEME, setup_styles
├── image_metadata.py    — ImageMetadataStore (필터/검색), ThumbnailCache
├── image_selector.py    — ImageSlot, ImageSelector (auto_select, 3단계 파이프라인)
├── substitution.py      — parse_original_manuscript, infer_scenes, match_images
├── catalog_images.py    — scan_drive_images, register_images, tag_images_with_vision
└── requirements.txt     — anthropic, gspread, google-auth, python-docx, Pillow 등
```

---

## 🖼️ 이미지 정리 내역

### 원본 → 정리

```
C:\Users\iamhy\Desktop\이미지\           (13,136장)
    ↓ 정리
C:\Users\iamhy\Desktop\이미지_정리\이미지_라이브러리\  (12,208장)
```

### 매핑 규칙

| 원본 폴더 | 정리 후 |
|----------|---------|
| `{제품}/자사제품/` | → `제품컷/{제품명}/` |
| `{제품}/논문/` | → `{제품명}/논문/` |
| `{제품}/정보성/` | → `{제품명}/정보성/` (하위 폴더 flatten) |
| `{제품}/타사제품/` | → `{제품명}/타사제품/` |
| `{제품}/커뮤니티/` | → `{제품명}/커뮤니티/` |
| `기타 이미지/{카테고리}/` | → `공통/{카테고리}/` |
| `판토오틴/휴지통_사용X/` | → **제외** (1,899장) |

### 병원 이미지 재분류 (파일명 키워드 매칭)

| 키워드 패턴 | 이동 대상 | 수 |
|------------|----------|-----|
| 위 처방, 위염, 역류성, 소화, 이비인후과 | 헬리컷/병원_위장 | 29 |
| 난임, 산부인과, 폐경 | 활성엽산/병원_산부인과 | 16 |
| 혈압, 콜레스테롤 | 블러드싸이클/병원_혈압 | 12 |
| 정형외과, 체외충격 | 상어연골환/병원_정형외과 | 11 |
| 탈모, 피나온 | 판토오틴/병원_탈모 | 7 |
| 피부과, 여드름 | 퓨어톤부스트/병원_피부 | 4 |
| 혈당, 당뇨 | 글루코컷/병원_혈당 | 1 |

---

## ⏭️ 다음 작업

1. Drive에 `이미지_라이브러리` 폴더 업로드
2. `catalog_images.py` 실행 → 메타데이터 시트 등록 + AI 태깅
3. 테스트 원고 생성 → 이미지-텍스트 연결 품질 확인
4. 프롬프트 튜닝 (섹션 7-4, 7-5 조정)
