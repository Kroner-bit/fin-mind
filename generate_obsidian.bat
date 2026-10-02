@echo off
chcp 65001 >nul
title FinMind - Obsidian Brain Generátor
cls
echo ====================================================================
echo   🧠 FINMIND - OBSIDIAN BRAIN KNOWLEDGE GRAPH GENERÁTOR
echo ====================================================================
echo.
echo   [1] Csak az ÚJ JSON fájlok feldolgozása (Inkrementális - Ajánlott)
echo       - Csak az újonnan letöltött/feldolgozott tanulmányokat adja hozzá
echo       - A meglévő jegyzeteket és saját módosításaidat NEM írja felül!
echo       - Villámgyors (0.1 másodperc ha nincs új tanulmány)
echo.
echo   [2] Teljes újragenerálás (--force)
echo       - Minden jegyzetet újraépít a JSON fájlok alapján
echo.
echo ====================================================================
set /p choice="Válassz menüpontot [1 vagy 2] (Enter = 1): "

cd /d "%~dp0obsidian"
if "%choice%"=="2" (
    echo.
    echo [!] Teljes újragenerálás indítása...
    python generate_obsidian_vault.py --force
) else (
    echo.
    echo [*] Inkrementális futtatás (Csak új JSON fájlok)...
    python generate_obsidian_vault.py
)

echo.
echo ====================================================================
echo Kész! Nyomj meg egy billentyűt a bezáráshoz...
pause >nul
