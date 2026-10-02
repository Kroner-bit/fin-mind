@echo off
chcp 65001 >nul
title FinMind - arXiv Research Collector
cls
echo ====================================================================
echo   📥 FinMind - arXiv Research Collector
echo ====================================================================
echo.
echo   [1] Teszt mód (--test: 1 kulcsszó, max 5 tanulmány letöltése)
echo   [2] Teljes mód (--full: mind a 100 kulcsszó feldolgozása)
echo   [3] Interaktív mód (részletes prompt)
echo.
echo ====================================================================
set /p choice="Válassz menüpontot [1, 2 vagy 3] (Enter = 1): "

cd /d "%~dp0arxiv_collector"
if "%choice%"=="2" (
    echo.
    echo [*] Teljes gyűjtési mód indítása...
    python main.py --full
) else if "%choice%"=="3" (
    echo.
    echo [*] Interaktív gyűjtés indítása...
    python main.py
) else (
    echo.
    echo [*] Teszt gyűjtési mód indítása...
    python main.py --test
)

echo.
echo ====================================================================
echo Folyamat befejeződött. Nyomj meg egy billentyűt a kilépéshez...
pause >nul
