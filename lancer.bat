@echo off
rem Lanceur double-clic InsertYourCoin (PAPER-ONLY). ASCII pur (PowerShell 5.1 / cp1252).
cd /d "%~dp0"
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
"%PY%" lancer.py %*
if errorlevel 1 (
  echo.
  echo Le lanceur a signale une erreur. Lis les messages ci-dessus.
  pause
)
