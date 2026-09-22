@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_backend.ps1" -OpenBrowser
if errorlevel 1 pause
