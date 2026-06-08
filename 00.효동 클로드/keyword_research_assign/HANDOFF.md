# 키워드 리서치 & 배정 프로그램 — 전체 HANDOFF

## 기본 정보
- **프로그램 경로**: `C:\Users\iamhy\Desktop\프로그램 개발\keyword_research_assign\`
- **버전**: v1.0 (3개 프로그램)
- **최초 작성일**: 2026-03-18
- **최종 수정일**: 2026-03-26

## 목적
건강/의학 블로그 마케팅을 위한 **키워드 리서치 → 배정** 파이프라인.
시드 키워드에서 연관검색어를 수집하고, 작가별 역량에 맞춰 키워드를 자동 배정한다.

## 프로그램 구성 (3개)

| 파일 | 역할 | 실행 방법 |
|------|------|-----------|
| `main.py` | 키워드 리서치 (연관검색어 수집) | `python main.py` |
| `keyword_assign.py` | 창고 기반 배정 (전환 70% + 잠재 30%) | `python keyword_assign.py` |
| `assign.py` | 전광판 기반 배정 (순위/경과일 우선순위) | `python assign.py` |

## 시트 연동

| 프로그램 | Sheet ID | 탭 |
|----------|----------|----|
| main.py | `1_rytQ5eGEui7R-P8aq_7OmNulix-SxDxF3yIcOWmumU` | 시트1 |
| keyword_assign.py | 동일 | 전환 키워드, 키워드 창고, 원고 작성 건수, 키워드 배정 |
| assign.py | `1xJAogt0alaQ8A5OctxltPaF3kg_0PFSF5Z0ePxMw3tY` | 키워드 전광판, 원고 작성 건수, 원고 배정, 전환 키워드 |

- **서비스 계정**: `keyword-research@keyword-research-488106.iam.gserviceaccount.com`
- **인증 파일**: `credentials.json` (폴더 내)

## 핵심 아키텍처

### 1. 키워드 리서치 (main.py)
```
시드 키워드 → Google/Naver/Daum 연관검색어 수집
           → Naver 검색광고 API 검색량 조회
           → 검색량 500+ 필터링 → 시트 기록
```

### 2. 창고 기반 배정 (keyword_assign.py)
```
전환 키워드 탭 + 시트1 → 키워드 창고 갱신
→ 작가별 quota 로드 → 사전 확정 입력
→ PASS 0(사전확정) → PASS 1(전환 70%) → PASS 2(잠재 30%)
→ 미리보기/수정 → 네이버 스마트블록 체크 → 시트 기록 (11열)
```
- **전환점수**: 검색량(30) + 구매의도(50) + 카테고리(15) + 전환금액(20) = 최대 115점
- **중복 방지**: 2주 이내 동일 키워드 제외

### 3. 전광판 기반 배정 (assign.py)
```
키워드 전광판 → 5단계 우선순위 분류
→ 작가별 제품 효율 분석 → 최적 작가 매칭
→ 네이버 스마트블록/인기글/브랜드 체크 → 시트 기록 (8열)
```
- **데이터 컬럼**: C(기존전환금액) / D(순위) / I(경과일) / J(전환금액=현재링크)
- **우선순위** (2026-03-26 변경):
  - 1차: 기존전환금액(C) ≥ 50만 AND 순위밖
  - 2차: 기존전환금액(C) ≥ 50만 AND 경과일(I) ≥ 10 AND 전환금액(J) = 0
  - 3차: 전환금액(J) > 0 AND 순위밖
  - 4차: 기존전환금액(C) > 0 AND 경과일(I) ≥ 10
  - 5차: 순위밖
  - 모든 우선순위 내 C열 내림차순 정렬
- **작가 매칭**: 제품 전환금액 - 분산 페널티 + 남은 quota
- **중복 방지**: 5일 이내 제외, 부족 시 4일로 완화

### 공통 유틸리티
```python
clean_keyword(kw)   # (1), (2) 등 접미사 제거
norm_keyword(kw)    # 공백 제거 + 소문자 → 중복 비교용
parse_amount(s)     # "12,345원" → 12345
parse_days(s)       # "3일" → 3
```

### Naver 검색광고 API
- Endpoint: `https://api.searchad.naver.com/keywordstool`
- 인증: HMAC-SHA256 서명 (timestamp + method + path)
- 배치: 5개씩, 0.3초 간격

## 의존성
- `gspread`, `google-auth` (구글 시트)
- `urllib`, `hmac`, `hashlib`, `base64` (HTTP, API 서명)
- `re` (HTML 파싱)
- **외부 라이브러리**: `gspread`, `google-auth`만 pip install 필요

## 실행 방법
```bash
cd "C:\Users\iamhy\Desktop\프로그램 개발\keyword_research_assign"
python main.py                        # 리서치: 시트에서 시드 읽기
python main.py 고혈압 혈당관리         # 리서치: CLI 직접 입력
python keyword_assign.py              # 창고 기반 배정 (CLI 대화형)
python assign.py                      # 전광판 기반 배정 (CLI 대화형)
```

## 개발 이력

| 날짜 | 내용 |
|------|------|
| 2026-03-18 | 폴더명 변경: `keyword_research` → `keyword_research_assign` |
| 2026-03-18 | 파일명 변경: `board_assign.py` → `keyword_assign.py` |
| 2026-03-19 | MECE 분석 문서 작성 (00_개요~03_전광판기반_배정) |
| 2026-03-26 | 전광판 배정(assign.py) 우선순위 3→5단계 변경, J열(전환금액) 읽기 추가 |
| 2026-03-26 | 두 배정 프로그램 모두 작가별 개별 건수 설정 옵션 추가 |

## 알려진 이슈 / 개선 가능

| 항목 | 설명 |
|------|------|
| CLI 전용 | 다른 프로그램과 달리 GUI 없음 |
| 배정 프로그램 2개 | 창고 기반 vs 전광판 기반 — 사용 기준 불명확 |
| HTML regex 파싱 | 네이버/구글/다음 UI 변경 시 깨짐 |
| API 키 하드코딩 | 환경변수 fallback 있으나 기본값은 하드코딩 |
| 순차 처리 | 네이버 검색 체크가 병렬화 미구현 |
| 실패 복구 없음 | 중간 실패 시 롤백/재시도 없음 |
