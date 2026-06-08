# 🔗 블로그 MKT 링크 대조 — HANDOFF

> **프로그램 경로**: `프로그램 개발\블로그 mkt 링크 대조\blog_link_extractor.py`
> **최종 업데이트**: 2026-03-20

---

## 📌 프로그램 개요

블로그에 삽입된 MKT 상품 링크를 추출하고, 구글 시트의 찐링크(F열)와 자동 대조하는 CLI 프로그램.

| 항목 | 값 |
|---|---|
| 메인 파일 | `blog_link_extractor.py` (280줄) |
| 스프레드시트 | `1jflcdbmBjQsY4hp8rNULXGGVqb64fGno4kudlTJoqM4` (바이럴 마케팅_2026) |
| 시트 탭 | `시트34` |
| 인증 | `manuscript_generator/credentials.json` (상대경로 `../`) |
| 의존성 | gspread, google-auth, selenium, webdriver-manager, requests |

---

## 🏗️ 아키텍처

```
main()
 ├─ get_gsheet()              # 구글 시트 연결 (서비스 계정)
 ├─ 데이터 읽기               # G열(블로그 링크), F열(찐링크)
 ├─ create_driver()            # Selenium headless Chrome
 ├─ extract_mkt_links()        # 블로그별 MKT 링크 추출
 │    ├─ switch_to_blog_frame()  # mainFrame iframe 전환
 │    ├─ DOM <a> href 탐색       # 8개 CSS 셀렉터
 │    ├─ data-linkdata 속성 파싱
 │    └─ 페이지 소스 정규식
 ├─ check_match()              # MKT ↔ 찐링크 일치 판정
 │    ├─ resolve_mkt_link()      # 리다이렉트 추적 (HEAD→GET)
 │    └─ normalize_product_url() # URL 정규화
 └─ ws.update()                # H~K열 결과 기입
```

---

## 📊 시트 컬럼 매핑

| 열 | 용도 | 방향 |
|---|---|---|
| F | 찐링크 (실제 상품 URL) | 읽기 |
| G | 블로그 링크 | 읽기 |
| H | 첫 번째 MKT 링크 | 쓰기 |
| I | 첫 번째 일치 여부 | 쓰기 |
| J | 두 번째 MKT 링크 | 쓰기 |
| K | 두 번째 일치 여부 | 쓰기 |

---

## 🔑 핵심 로직

### MKT 링크 추출 (`extract_mkt_links`)

1. 블로그 URL → PostView 형식 변환
2. 3가지 방식으로 `mkt.shopping.naver.com` 링크 수집 (중복 허용)
3. NaPm 추적 파라미터 제거

### 일치 판정 (`check_match`)

```
resolve_mkt_link() → 리다이렉트 최종 URL
normalize_product_url() → 프로토콜/쿼리/www/m 제거
비교: 전체 URL 일치 OR products/{ID} 일치
결과: "일치" | "불일치" | "확인불가"
```

---

## 📝 변경 이력

| 날짜 | 버전 | 내용 |
|---|---|---|
| 2026-03-20 | v1.0 | 초기 구현 — 120개 블로그 처리 성공 |
| 2026-03-20 | v1.0.1 | 중복 제거 해제 — 동일 링크도 2개 수집하도록 변경 |

---

## ⚠️ 알려진 문제

| 문제 | 상태 | 설명 |
|---|---|---|
| 34개 중복 수집 | 미해결 | 3가지 추출 방식이 같은 링크를 여러 번 잡음 (실제 2개) |
| ws.update() 경고 | 미해결 | gspread 인자 순서 DeprecationWarning |
| 시트/탭 하드코딩 | 미해결 | 코드 수정 없이 다른 탭 사용 불가 |
| 순차 처리 느림 | 미해결 | 120개에 ~10분 소요 |

---

## 🚀 TODO

- [ ] 중복 수집 정제 — 추출 방식 간 dedup (위치 기반)
- [ ] ws.update() 인자 순서 수정
- [ ] 병렬 처리 (Selenium 2~4개)
- [ ] 시트/탭 설정 외부화
- [ ] 처리 완료 행 스킵 기능
- [ ] GUI (tkinter)
