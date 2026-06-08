@echo off
REM ═══════════════════════════════════════════════════════
REM  블로그 관리 허브 EXE 빌드 스크립트
REM  - pyinstaller가 build.spec을 읽어 dist/블로그관리허브/ 생성
REM  - 빌드 후 credentials.json, config.json 등을 같은 폴더로 복사
REM ═══════════════════════════════════════════════════════

cd /d "%~dp0"
chcp 65001 >nul

echo.
echo [1/4] 이전 빌드 폴더 정리
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo.
echo [2/4] PyInstaller 빌드 시작 (5~10분 소요)
python -m PyInstaller build.spec --noconfirm
if errorlevel 1 (
    echo.
    echo [!] 빌드 실패. requirements.txt 설치 확인:  python -m pip install -r requirements.txt
    pause
    exit /b 1
)

echo.
echo [3/4] 데이터 파일 복사 (credentials, config)
copy /Y "credentials.json" "dist\블로그관리허브\credentials.json" >nul
copy /Y "config.json" "dist\블로그관리허브\config.json" >nul
if exist "comment_config.json" copy /Y "comment_config.json" "dist\블로그관리허브\comment_config.json" >nul
if exist "comment_state.json" copy /Y "comment_state.json" "dist\블로그관리허브\comment_state.json" >nul
if exist "README.md" copy /Y "README.md" "dist\블로그관리허브\README.md" >nul

echo.
echo [4/4] 완료
echo.
echo 배포 폴더: dist\블로그관리허브\
echo 실행 파일: dist\블로그관리허브\블로그관리허브.exe
echo.
echo 이 폴더 전체를 zip으로 압축해서 다른 사람에게 보내면 됩니다.
echo.
pause
