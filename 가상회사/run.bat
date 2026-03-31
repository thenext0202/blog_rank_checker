@echo off
chcp 65001 >nul
title 🏢 꼭지네 마케팅 인하우스

cd /d "%~dp0"

echo.
echo   패키지 확인 중...
pip install -q anthropic ddgs 2>nul

echo.
python main.py

pause
