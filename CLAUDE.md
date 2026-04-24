# 프로그램 개발 프로젝트

## 환경
- Python 3.14, Windows 11
- GUI: tkinter (B.모던라이트 테마)
- EXE 배포: PyInstaller → 비개발자 배포
- 간단한 자동화: bat 파일로 더블클릭 실행

## 인증 & 시트
- Google 서비스 계정: `manuscript_generator/credentials.json` 기준
- 공통 시트 ID: `1jflcdbmBjQsY4hp8rNULXGGVqb64fGno4kudlTJoqM4` (바이럴 마케팅_2026)
- **시트 테스트 시 반드시 해당 프로그램의 config/코드에서 SHEET_ID를 확인하고 사용할 것. 공통 시트 ID를 무조건 쓰지 말 것** — 프로그램마다 자체 시트를 사용하는 경우가 있음
- 네이버 검색광고 API: CUSTOMER_ID `2120690`

## 프로젝트 구조
```
프로그램 개발/
├── manuscript_generator/      # 원고 제작기 (v8.3+)
├── manuscript_generator_v2/   # 이미지 변형 추가 버전
├── manuscript_checker/        # 원고 검수
├── 원고배정/                  # 원고 배정 (v1.4)
├── 발행검수/                  # 발행 원고 검수 (v1.9)
├── 댓글검수/                  # 댓글 중복/누락 검수
├── 댓글알림/                  # 댓글 변동 모니터링
├── keyword_research_assign/   # 키워드 리서치 배정
├── 사용자 정의 자동복사/      # 매출 업로더
├── 00.효동 클로드/            # 문서화 (HANDOFF, 사용자 MD, 개별 HANDOFF)
```

## 코드 규칙
- 새 프로그램은 처음부터 모듈 분리 (3,482줄 단일 파일의 교훈)
- 프로그램 간 검증된 코드 재사용 (save_as_docx 등)
- EXE 경로 자동 감지: `sys.frozen` 분기 → EXE 옆 파일 우선 → fallback
- 설정은 시트 기반 (비개발자 수정 가능) + JSON 영구 저장 (config.json, exclude_keywords.json 등)
- config.json 기존 값이 코드 기본값보다 우선 — 코드만 수정하면 반영 안 됨

## 검증된 패턴
- 2단계 최적화: 가벼운 감지(API/HTTP) → 무거운 처리(Selenium)만 선별 실행
- 링크 매칭 3단계: 전체 URL → MKT ID → 리다이렉트 URL
- 네이버 DOM: `a.href`보다 `data-linkdata` 속성이 신뢰도 높음
- URL 비교 시 반드시 정규화 (percent-decode + 쿼리 정렬 + scheme 제거)
- 텍스트 비교 시 유니코드 정규화 (따옴표→ASCII, 공백 정리, 소문자)
- 검수 로직: `if/elif` 아닌 독립 `if/if` (같은 MKT ID 공유 시 하나만 잡히는 문제 방지)

## 네이버 관련 교훈
- JS가 `a.href`를 동적 수정 → `data-*` 속성에서 원본 추출
- `PostTitleListAsync` API: 일부 글 누락 가능 → 모바일 페이지 fallback
- cbox API: "Wrong ticket" 에러 발생 → 모바일 페이지 방식으로 전환
- `find_elements` 사용 (`find_element`는 implicit wait 병목)

## 문서화 위치
- 각 프로그램별 문서: `00.효동 클로드/{프로그램명}/`
  - HANDOFF.md: 전체 현황
  - 개별 HANDOFF/: 버전별 변경 기록
  - 사용자 MD 파일/: 비개발자용 설명서
