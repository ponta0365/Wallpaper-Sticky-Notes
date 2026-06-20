@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" launch.py
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Write-Error 'Virtual environment not found. Please run setup.bat first.'; Read-Host 'Press Enter to exit...'"
)
