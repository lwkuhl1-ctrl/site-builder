@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File setup-keys.ps1
pause
