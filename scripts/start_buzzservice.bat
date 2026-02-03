@echo off
setlocal
set PORT=%1
if "%PORT%"=="" set PORT=49152
powershell -ExecutionPolicy Bypass -File "%~dp0start_buzzservice.ps1" -Port %PORT%
