@echo off
echo === 원고 검수 프로그램 빌드 ===
echo.

echo 1. 패키지 설치 중...
pip install -r requirements.txt
echo.

echo 2. 설정 엑셀 파일 생성 중...
python create_config_excel.py
echo.

echo 3. exe 파일 빌드 중...
pyinstaller --onefile --windowed --name "원고검수기" --add-data "검수설정.xlsx;." main.py
echo.

echo === 빌드 완료 ===
echo exe 파일 위치: dist\원고검수기.exe
echo dist 폴더에 검수설정.xlsx 파일도 함께 복사하세요!
pause
