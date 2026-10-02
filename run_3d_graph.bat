@echo off
chcp 65001 >nul
title FinMind 3D Knowledge Graph Studio
cls
echo ====================================================================
echo   🌌 FINMIND - 3D COSMIC KNOWLEDGE GRAPH STUDIO (GPU ACCELERATED)
echo ====================================================================
echo.
echo   Indítás alatt a 3D WebGL Tudásgráf szerver a 8050-es porton...
echo   Elérhető a böngészőben: http://localhost:8050
echo.
echo   [Tipp] A meglévő PDF feldolgozó (port 8000) zavartalanul futhat mellette!
echo   [Tipp] Nyomj Ctrl+C billentyűt a 3D szerver leállításához.
echo ====================================================================
echo.

cd /d "%~dp0graph_3d"

REM Nyissuk meg a böngészőt 2 másodperc múlva a háttérben
start "" cmd /c "timeout /t 2 /nobreak >nul & start http://localhost:8050"

python server.py --port 8050
pause
