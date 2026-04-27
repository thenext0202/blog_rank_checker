@echo off
chcp 65001 >nul
title 효하 가계부
echo.
echo   ==========================================
echo       효하 가계부를 시작합니다...
echo   ==========================================
echo.
cd /d "C:\Users\iamhy\Desktop\프로그램 개발\효하 가계부"
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8501.*LISTENING"') do taskkill /PID %%a /F >nul 2>&1
py -m streamlit run app.py --server.port 8501
pause