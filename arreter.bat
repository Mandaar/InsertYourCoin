@echo off
rem Arret double-clic InsertYourCoin : stoppe paper + monitor. ASCII pur.
cd /d "%~dp0"
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
"%PY%" lancer.py --stop
pause
