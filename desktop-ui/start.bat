@echo off
echo ============================================
echo  Hivenance Desktop UI - Quick Launcher
echo ============================================
echo.

REM Check if node_modules exists
if not exist "node_modules\" (
    echo Installing dependencies...
    call npm install
    if errorlevel 1 (
        echo Failed to install dependencies!
        pause
        exit /b 1
    )
    echo.
)

echo Starting Hivenance Desktop UI...
echo.
echo Make sure your backend is running at http://127.0.0.1:5000
echo.

call npm start

pause
