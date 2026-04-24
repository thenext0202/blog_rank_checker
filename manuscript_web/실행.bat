@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  Block Manuscript Generator - Local Server
echo ============================================
echo.
echo Starting server on http://localhost:5000 ...
echo.
start "" http://localhost:5000
python app.py
echo.
echo ----- Server stopped. Press any key to close -----
pause >nul
