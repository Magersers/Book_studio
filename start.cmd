@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Please run setup.cmd first.
  pause
  exit /b 1
)
start "Book Studio" ".venv\Scripts\pythonw.exe" -X utf8 "desktop_app.py"
