@echo off
chcp 65001 >nul
title Virtual Company

cd /d "%~dp0"

pip install -q anthropic ddgs pygame-ce 2>nul

python gui_app.py 2> error_log.txt

echo.
if exist error_log.txt (
    for %%A in (error_log.txt) do if %%~zA gtr 0 (
        echo [ERROR]
        type error_log.txt
    )
)
echo.
pause
