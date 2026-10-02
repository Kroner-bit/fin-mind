@echo off
chcp 65001 >nul
title FinMind Web Studio
cls
echo ====================================================================
echo   ⚡ FINMIND - WEB STUDIO (FASTAPI + WEBSOCKET)
echo ====================================================================
echo.
echo   Indítás alatt a FastAPI webszerver és a háttér workerek...
echo   Elérhető a böngészőben: http://localhost:8000
echo.
echo   [Tipp] Nyomj Ctrl+C billentyűt a szerver leállításához.
echo ====================================================================
echo.
cd /d "%~dp0pdf_processor"
python web_app.py
pause
