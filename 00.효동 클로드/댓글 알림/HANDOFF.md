# 📢 네이버 블로그 댓글 알림 프로그램 — HANDOFF

> **날짜:** 2026-03-23
> **상태:** ✅ 핵심 기능 완성 (v2.2)
> **경로:** `C:\Users\iamhy\Desktop\프로그램 개발\댓글알림\main.py`

---

## 📋 프로그램 개요

| 항목 | 내용 |
|------|------|
| **목적** | 등록한 네이버 블로그 개별 글 URL에 새 댓글 달리면 Slack 알림 |
| **비공개 감지** | 정부기관 요청에 의한 비공개 조치 감지 → Slack 알림 |
| **입력** | 개별 글 URL (대량 추가 지원) |
| **체크 주기** | 30분 (`config.json`에서 변경) |
| **즉시 체크** | `⚡ 즉시 체크` 버튼으로 즉시 실행 가능 |
| **GUI** | tkinter — URL 관리(추가/대량추가/삭제), 시작/중지, 즉시 체크, 로그 |
| **Slack Webhook** | `hooks.slack.com/services/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` |

---

## ✅ 완료된 작업

### 1. 비공개 조치 감지 — 완료 (v2.2)
- 모바일 페이지에서 비공개 패턴 1차 감지 (`~의 요청에 따라 비공개 조치`)
- 데스크톱 PostView에서 요청기관 + 요청 일자 상세 조회
- 모니터링 세션당 1번만 알림 (`alerted_private`), 재시작 시 초기화
- 댓글 수 조회 실패 + 비공개 아닌 글 → Selenium 강제 확인 (댓글 누락 방지)

### 2. 2단계 최적화 체계 — 완료 (v2.1 개선)
- **1단계 (모바일 페이지):** 개별 글 `m.blog.naver.com` 페이지에서 `commentCount` 실시간 조회 + 비공개 감지
- **2단계 (Selenium):** 댓글 수 증가한 글만 headless Chrome 스크래핑
- 변동 없으면 Selenium 안 씀

> ⚠️ v2.0까지 사용하던 `PostTitleListAsync` API는 **일부 글이 목록에서 누락되는 문제**가 있어 v2.1에서 모바일 페이지 방식으로 전환

### 3. 즉시 체크 기능 — 완료 (v2.1)
- `⚡ 즉시 체크` 버튼 (모니터링 시작 버튼 옆)
- 모니터링 ON: 대기 타이머 취소 → 즉시 체크 → 다시 30분 타이머
- 모니터링 OFF: 1회만 체크하고 끝
- 중복 실행 방지 (체크 진행 중 클릭 무시)

### 4. 개별 글 URL 모니터링 — 완료 (v2.0)
- 블로그 전체 → 개별 글 URL 단위로 변경
- URL 파싱 (`parse_post_url`)

### 5. 대량 URL 추가 — 완료
- 팝업 창에서 여러 줄로 URL 붙여넣기
- 자동 URL 추출, 중복 제거

### 6. 기준점 저장 방식 — 완료
- `▶ 모니터링 시작` 클릭 → 그 시점 commentCount를 기준점 저장
- 이후 체크에서 기준점 대비 증가분만 감지

### 7. 탭 크래시 해결 — 완료
- `page_load_timeout(15)` 추가
- 10개마다 드라이버 자동 재시작
- `--single-process` 제거 (불안정 유발)
- Chrome 안정성 옵션 추가

### 8. 기존 기능 (v1.0에서 유지)
- 댓글 스크래핑 (Selenium, mainFrame iframe, 더보기 확장)
- Slack 알림 (webhook POST)
- GUI (시작/중지, 로그, URL 관리)
- 상태 저장 (`config.json`, `comment_state.json`)
- 에러 처리 (삭제된 글 alert, 탭 크래시 자동 복구)

---

## 🏗️ 아키텍처

```
댓글알림/
├── main.py              # 전체 코드 (단일 파일)
├── config.json          # 글 URL 목록, Slack webhook, 간격 (자동 저장)
├── comment_state.json   # 댓글 수 기준점 + seen ID + alerted_private (자동 저장)
└── memory/
    └── HANDOFF.md
```

### 주요 클래스/함수

| 이름 | 역할 |
|------|------|
| `parse_post_url(url)` | URL → blog_id, log_no 파싱 |
| `create_driver()` | headless Chrome 드라이버 (안정성 옵션) |
| `BlogMonitor._fetch_comment_count_direct(blog_id, log_no)` | 모바일 페이지에서 commentCount + 비공개 감지 (튜플 반환) |
| `BlogMonitor._fetch_private_detail(blog_id, log_no)` | 데스크톱 PostView에서 요청기관/일자 상세 조회 |
| `BlogMonitor.get_comments(blog_id, log_no)` | Selenium 댓글 스크래핑 |
| `BlogMonitor.check_all()` | 댓글 수 변동감지 + 비공개 감지 → Selenium 스크래핑 → Slack 알림 |
| `App._run_now()` | 즉시 체크 (ON: 타이머 리셋, OFF: 1회 실행) |
| `App._run_once()` | 모니터링 OFF 상태 1회 체크 |
| `App` | tkinter GUI |

### check_all() 흐름
```
URL 파싱
→ 글마다 m.blog.naver.com 모바일 페이지에서:
    ├─ commentCount 조회
    └─ 비공개 패턴 감지
→ 비공개 감지 시 → 데스크톱 PostView 상세 조회 → Slack 알림
→ 첫 실행? → 기준점 저장, 종료
→ 이전 기준점과 비교 → 증가한 글 필터링
→ 댓글 수 조회 실패 + 비공개 아닌 글 → Selenium 강제 확인 대상에 추가
→ Selenium 스크래핑 (증가 글 + 강제 확인 대상)
→ seen과 비교 → 새 댓글 Slack 알림
→ state 저장
```

---

## 🔑 핵심 발견 (디버깅 과정)

1. **`PostTitleListAsync` 글 누락 문제:** 이 API는 블로그의 모든 글을 반환하지 않음. 특정 글(오래된 글, 특수 유형)이 목록에서 빠져서 commentCount 조회 자체가 불가능 → 모바일 페이지 방식으로 해결
2. **cbox API 사용 불가:** `"Wrong ticket"` 에러 — 네이버가 ticket 값 변경/차단
3. **모바일 페이지 `commentCount`:** `m.blog.naver.com/{blogId}/{logNo}` HTML에 `commentCount="숫자"` 속성이 있음 → 실시간 반영, Selenium 불필요
4. **네이버 댓글 내용 API 없음:** 댓글 내용은 Selenium이 유일한 방법
5. **`find_elements` 사용 필수:** `find_element`는 implicit wait 병목 유발
6. **삭제된 게시글 alert:** `switch_to.alert.accept()` 먼저 처리
7. **`--single-process` 옵션:** 오히려 불안정 유발 → 제거
8. **비공개 글 = commentCount 없음:** 비공개 조치된 글의 모바일 페이지에는 `commentCount` 속성 자체가 없음 → 댓글 수 조회 실패로 이어져 댓글 누락 버그 유발
9. **모바일 vs 데스크톱 비공개 패턴이 다름:**
   - 모바일: `"~의 요청에 따라 비공개 조치 되었음을 안내 드립니다"`
   - 데스크톱: `"이 게시물은 ~의 요청으로 비공개 조치 되었습니다"` + 요청기관/일자 테이블

---

## 📝 버전 히스토리

| 버전 | 날짜 | 변경 |
|------|------|------|
| v1.0 | 2026-03-20 | 블로그 단위 모니터링, 전체 Selenium 스크래핑 |
| v1.1 | 2026-03-23 | commentCount API(PostTitleListAsync) 최적화 |
| v1.2 | 2026-03-23 | 첫 실행 API만 (Selenium X) |
| v2.0 | 2026-03-23 | 개별 글 URL, 대량 추가, 15분 주기 |
| v2.1 | 2026-03-23 | 모바일 페이지 API 전환, 즉시 체크 버튼, 30분 주기 |
| **v2.2** | **2026-03-23** | **비공개 조치 감지 (모바일+데스크톱), 댓글 누락 수정** |

---

## 🔴 남은 작업

| 작업 | 우선순위 | 상세 |
|------|----------|------|
| **EXE 빌드** | 높음 | PyInstaller → 상시 가동 PC 배포 |
| Windows 시작프로그램 등록 | 중간 | PC 재시작 시 자동 실행 |
| 삭제된 글 감지 | 중간 | "삭제되었거나 존재하지 않는 게시물" 패턴 알림 |
| 체크 간격 GUI 설정 | 낮음 | 현재 config.json 직접 수정 |
| 글 수 증가 대응 | 낮음 | 200개+ 시 병렬 요청 또는 간격 자동 조정 |

---

## 📂 관련 문서

| 구분 | 경로 |
|------|------|
| **전체 HANDOFF** | `00.효동 클로드\댓글 알림\HANDOFF.md` (이 파일) |
| **개별 HANDOFF** | `00.효동 클로드\댓글 알림\개별 HANDOFF\` |
| **사용자 MD** | `00.효동 클로드\댓글 알림\사용자 MD\` |
| **프로그램 HANDOFF** | `댓글알림\memory\HANDOFF.md` |

### 개별 HANDOFF 목록
- `handoff_260323_v2.0_개별글URL_최적화.md` — 블로그→개별URL, 2단계 최적화, 대량추가, 크래시 해결
- `handoff_260323_v2.1_모바일API_즉시체크.md` — PostTitleListAsync→모바일페이지, 즉시체크, 30분주기
- `handoff_260323_v2.2_비공개조치감지.md` — 비공개 조치 감지(모바일+데스크톱), 댓글 누락 수정

### 사용자 MD 목록
- `v2.0_개별글URL_대량추가_260323.md` — v2.0 사용법 + 동작 원리 + GUI 설명
- `v2.1_모바일API_즉시체크_260323.md` — v2.1 모바일 API 전환 + 즉시 체크 사용법
- `v2.2_비공개조치감지_260323.md` — 비공개 조치 감지 사용법 + 구현 방법 + 댓글 누락 수정
