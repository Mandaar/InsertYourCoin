@echo off
rem Lanceur InsertYourCoin (PAPER-ONLY). ASCII pur (PowerShell 5.1 / cp1252).
rem
rem SANS argument (double-clic direct sur ce fichier) : demarre en ARRIERE-PLAN,
rem sans fenetre console -- delegue a pythonw.exe (sous-systeme GUI, ne cree
rem JAMAIS de console). Diagnostic + erreurs : logs\lancer.log, et une boite de
rem dialogue Windows si le diagnostic Kraken echoue (cf. lancer.py _notify_failure).
rem Le raccourci bureau (scripts\install_shortcut.ps1) cible pythonw.exe
rem DIRECTEMENT (encore plus sur : zero flash de console, meme bref).
rem
rem AVEC un argument (--status / --stop / --dry-run) : reste interactif dans
rem CETTE console, comme avant -- usage manuel en terminal, sortie attendue.
cd /d "%~dp0"
set "PY=python"
set "PYW=pythonw"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if exist ".venv\Scripts\pythonw.exe" set "PYW=.venv\Scripts\pythonw.exe"
if "%~1"=="" (
  start "" "%PYW%" lancer.py
  goto :eof
)
"%PY%" lancer.py %*
if errorlevel 1 (
  echo.
  echo Le lanceur a signale une erreur. Lis les messages ci-dessus.
  pause
)
