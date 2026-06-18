@echo off
rem Installe le raccourci InsertYourCoin sur le bureau Windows.
rem ASCII pur (PowerShell 5.1 / cp1252 safe).
cd /d "%~dp0"
powershell.exe -ExecutionPolicy Bypass -File "%~dp0scripts\install_shortcut.ps1"
if errorlevel 1 (
    echo.
    echo Erreur lors de la creation du raccourci. Lis les messages ci-dessus.
    pause
) else (
    pause
)
