@echo off
rem Supprime le raccourci InsertYourCoin du bureau Windows.
rem ASCII pur (PowerShell 5.1 / cp1252 safe).
cd /d "%~dp0"
powershell.exe -ExecutionPolicy Bypass -File "%~dp0scripts\install_shortcut.ps1" -Uninstall
if errorlevel 1 (
    echo.
    echo Erreur lors de la suppression du raccourci. Lis les messages ci-dessus.
    pause
) else (
    pause
)
