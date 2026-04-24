@echo off
chcp 65001 >nul 2>&1
echo ==================================================
echo   매출 데이터 - 구글 스프레드시트 업로더
echo ==================================================
echo.
python "%~dp0sales_uploader.py"
echo.
pause
