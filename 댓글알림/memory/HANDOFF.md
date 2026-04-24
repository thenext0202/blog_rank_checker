# 📢 네이버 블로그 댓글 알림 프로그램 — HANDOFF

> **날짜:** 2026-03-23
> **상태:** ✅ 핵심 기능 완성 (v2.1)
> **경로:** `C:\Users\iamhy\Desktop\프로그램 개발\댓글알림\main.py`

---

## 📋 프로그램 개요

| 항목 | 내용 |
|------|------|
| **목적** | 등록한 네이버 블로그 개별 글 URL에 새 댓글 달리면 Slack 알림 |
| **입력** | 개별 글 URL (대량 추가 지원) |
| **체크 주기** | 30분 (`config.json`에서 변경) |
| **즉시 체크** | `⚡ 즉시 체크` 버튼 |
| **댓글 수 조회** | 모바일 페이지 (`m.blog.naver.com`) — 실시간 반영 |
| **GUI** | tkinter — URL 관리, 시작/중지, 즉시 체크, 로그 |
| **Slack Webhook** | `hooks.slack.com/services/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` |

---

## 🏗️ 아키텍처

```
댓글알림/
├── main.py              # 전체 코드 (단일 파일)
├── config.json          # 글 URL 목록, Slack webhook, 간격 (자동 저장)
├── comment_state.json   # 댓글 수 기준점 + seen ID (자동 저장)
└── memory/
    └── HANDOFF.md       # 이 파일
```

### check_all() 흐름
```
URL 파싱
→ 글마다 m.blog.naver.com 모바일 페이지에서 commentCount 조회
→ 첫 실행? → 기준점 저장, 종료
→ 이전 기준점과 비교 → 증가한 글 필터링
→ Selenium 스크래핑 (증가 글만)
→ seen과 비교 → 새 댓글 Slack 알림
→ state 저장
```

---

## 🔑 핵심 발견

1. **`PostTitleListAsync` 글 누락:** 블로그의 모든 글을 반환하지 않음 → 모바일 페이지로 해결
2. **cbox API 사용 불가:** `"Wrong ticket"` 에러
3. **모바일 페이지 `commentCount`:** HTML 속성으로 실시간 반영됨
4. **댓글 내용은 Selenium만 가능**

---

## 📝 버전 히스토리

| 버전 | 날짜 | 변경 |
|------|------|------|
| v1.0 | 2026-03-20 | 블로그 단위 모니터링, 전체 Selenium 스크래핑 |
| v1.1 | 2026-03-23 | commentCount API 최적화 |
| v1.2 | 2026-03-23 | 첫 실행 API만 (Selenium X) |
| v2.0 | 2026-03-23 | 개별 글 URL, 대량 추가, 15분 주기 |
| **v2.1** | **2026-03-23** | **모바일 페이지 API 전환, 즉시 체크, 30분 주기** |

---

## 📂 상세 문서

| 구분 | 경로 |
|------|------|
| **전체 HANDOFF** | `00.효동 클로드\댓글 알림\HANDOFF.md` |
| **개별 HANDOFF** | `00.효동 클로드\댓글 알림\개별 HANDOFF\` |
| **사용자 MD** | `00.효동 클로드\댓글 알림\사용자 MD\` |
