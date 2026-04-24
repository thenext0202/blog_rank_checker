# 블로그 관리 허브

네이버 블로그 자동화 도구 5종 통합 — 대댓글 봇, 댓글 알림, 링크 대조, 템플릿 자동발행, 댓글 검수.

<br>

## 🧍 받은 사람용 (EXE 실행)

### 준비물
- **Google Chrome 브라우저** (최신 버전) — [다운로드](https://www.google.com/chrome/)
- 받은 `블로그관리허브` 폴더 통째 (압축 풀어두기)

### 실행
폴더 안의 **`블로그관리허브.exe`** 를 더블클릭하면 끝.

처음 실행 시 Chrome 드라이버를 자동 다운로드하므로 **인터넷 연결 + 몇 초 대기** 필요합니다.

### 폴더 안에 있어야 할 파일들
| 파일 | 용도 |
|------|------|
| `블로그관리허브.exe` | 실행 파일 |
| `credentials.json` | 구글 시트 인증 키 (건드리지 말 것) |
| `config.json` | 시트 ID, 탭 이름 설정 |
| `comment_config.json` | 댓글 알림 탭 설정 (자동 생성됨) |
| `_internal/` | EXE가 참조하는 라이브러리들 (건드리지 말 것) |
| `chrome_profile/` | 네이버 로그인 세션 (자동 생성됨) |

> ⚠️ **주의**: `credentials.json` 파일이 없거나 이름이 다르면 시트 연결이 실패합니다.

<br>

## 👩‍💻 개발자용 (빌드 방법)

### 1. 파이썬 환경 준비
```bash
python -m pip install -r requirements.txt
```

### 2. 빌드
`build.bat` 더블클릭, 또는:
```bash
pyinstaller build.spec --noconfirm
```

### 3. 결과
- `dist/블로그관리허브/` 폴더가 생성됨
- 이 폴더 통째 zip으로 압축해 배포

### 4. 코드 수정 후 재빌드
- `.py` 파일 고친 뒤 다시 `build.bat` 실행
- 5~10분 소요

<br>

## 📁 프로젝트 구조
```
blog_management_hub/
├── main.py                    # 진입점
├── build.spec                 # PyInstaller 설정
├── build.bat                  # 빌드 스크립트
├── requirements.txt           # 파이썬 패키지 목록
├── config.json                # 시트 설정
├── credentials.json           # 구글 서비스 계정 키
├── shared/                    # 공통 모듈 (경로, 시트, 브라우저, GUI)
├── tabs/                      # 5개 탭 (대댓글, 알림, 링크, 자동발행, 검수)
└── vendor/                    # 외부에서 가져와 번들한 모듈 (자동발행)
```

<br>

## 🔧 문제 해결

| 증상 | 원인 | 해결 |
|------|------|------|
| "인증 파일이 없습니다" | `credentials.json` 없음 | 파일 위치 확인 |
| Chrome 창이 안 열림 | Chrome 미설치 | Chrome 설치 |
| 시트 연결 실패 | 시트 공유 안 됨 | `credentials.json` 안의 `client_email`을 시트에 공유 |
| EXE 실행 시 콘솔 창이 잠깐 뜸 | webdriver 자동 다운로드 중 | 정상. 첫 실행만 그럼 |
