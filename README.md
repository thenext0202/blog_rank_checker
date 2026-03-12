# 📊 네이버 블로그 순위 체커

구글 스프레드시트에 키워드와 블로그 URL을 등록하면, 네이버 검색 순위를 자동으로 체크해서 기록해주는 도구입니다.

---

## ✨ 주요 기능

- **네이버 통합검색** 순위 체크 (블로그/카페/지식인 섹션 기준, 광고 제외)
- **네이버 블로그탭** 순위 체크
- 순위 기록을 **최대 3회** 누적 저장 (순위1 → 순위2 → 순위3)
- 순위 **상승 시 노란색** 하이라이트 자동 표시
- **구글 시트 K열 체크박스** 하나로 실행 트리거
- Railway 클라우드에서 **24시간 무인 운영** (PC 꺼도 동작)
- 운영 시간: **10:00 ~ 20:00 KST**

---

## 📋 구글 시트 구조

| 열 | 내용 |
|----|------|
| A | 날짜 |
| B | 발행처 |
| C | 키워드 |
| D | 블로그 포스트 URL |
| E | 메인 순위 1차 |
| F | 블로그탭 순위 1차 |
| G | 메인 순위 2차 |
| H | 블로그탭 순위 2차 |
| I | 메인 순위 3차 |
| J | 블로그탭 순위 3차 |
| K | ✅ **실행 (체크박스)** |

---

## 🚀 사용 방법

1. 구글 시트에 키워드(C열)와 블로그 URL(D열) 입력
2. **K열 체크박스를 체크**
3. 자동으로 순위 검색 시작 → 완료되면 E~J열에 결과 기록
4. 체크박스는 실행 시작과 동시에 자동 해제됨 (중복 실행 방지)

> 💡 순위1(E,F)이 이미 있으면 → 순위2(G,H)에 기록  
> 💡 순위2(G,H)까지 있으면 → 순위3(I,J)에 기록  
> 💡 순위2, 3 기록 시 이전 순위보다 **상승 + 10위 이내**면 노란색 표시

---

## ⚙️ 기술 스택

- **Python 3.12**
- **Playwright** (headless Chromium) — 네이버 검색 결과 크롤링
- **gspread + google-auth** — 구글 시트 연동
- **Railway** — 클라우드 배포 (24시간 상시 운영)

---

## 🛠️ 로컬 실행

### 1. 의존성 설치
```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. 인증 설정
Google Cloud 서비스 계정 키 파일을 `credentials.json`으로 저장  
(또는 환경변수 `GOOGLE_CREDENTIALS_BASE64`에 base64 인코딩된 JSON 설정)

### 3. 실행
```bash
# 감시 모드 (권장) - 60초마다 시트 체크
python rank.py watch

# 1회 실행
python rank.py
```

---

## ☁️ Railway 배포

### 환경변수 설정
| 변수명 | 내용 |
|--------|------|
| `GOOGLE_CREDENTIALS_BASE64` | 서비스 계정 키 JSON을 base64 인코딩한 값 |

### 배포 흐름
1. `startup.py` 실행
2. Playwright Chromium 자동 설치
3. `credentials.json` 생성
4. `rank.py watch` 시작 → 상시 대기

---

## 📁 파일 구조

```
├── rank.py          # 메인 로직 (순위 검색 + 시트 기록)
├── startup.py       # Railway 시작 스크립트
├── requirements.txt # Python 의존성
├── Procfile         # Railway 프로세스 설정
└── README.md        # 이 파일
```

---

## ⚠️ 주의사항

- `credentials.json`은 절대 GitHub에 올리지 마세요 (`.gitignore`에 등록됨)
- 운영 시간 외(20:00~10:00)에는 자동으로 대기 모드
- Railway 무료 플랜 메모리 제한으로 `--no-sandbox`, `--disable-dev-shm-usage` 옵션 필수
