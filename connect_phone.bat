@echo off
title SocialShield - Phone Sync & Launch
color 0b
echo ================================================================
echo    SOCIAL SHIELD - CONNECT PHONE OVER USB & RUN IN BOTH
echo ================================================================
echo.

set ADB="C:\Users\Aadar\AppData\Local\Android\Sdk\platform-tools\adb.exe"
if not exist %ADB% set ADB="c:\deepfake\tools\platform-tools\adb.exe"
if not exist %ADB% (
    echo [ERROR] ADB not found.
    pause
    exit /b 1
)

echo [1/5] Waiting for your Android phone to connect via USB...
echo.
echo  * Plug in your USB cable now.
echo  * Enable USB Debugging in Developer Options on your phone.
echo  * Tap "Allow USB Debugging" on your phone screen if prompted.
echo.

:wait_loop
%ADB% wait-for-device

for /f "tokens=*" %%i in ('%ADB% get-state 2^>nul') do set DEVSTATE=%%i
if not "%DEVSTATE%"=="device" (
    echo Current device state: %DEVSTATE%
    echo Please unlock your phone and tap 'Allow USB debugging'.
    timeout /t 2 >nul
    goto wait_loop
)

echo [2/5] Phone Connected!
%ADB% devices -l
echo.

echo [3/5] Setting up USB reverse proxy for real-time live sync...
%ADB% reverse tcp:5000 tcp:5000
%ADB% reverse tcp:8000 tcp:8000
%ADB% reverse tcp:5173 tcp:5173
echo  * Port 5000 (SocialShield Web) mapped over USB cable -^> Phone
echo  * Port 8000 (FastAPI Backend) mapped over USB cable -^> Phone
echo.

echo [4/5] Checking Android Native APK...
if exist "%~dp0app-debug.apk" (
    echo Installing SocialShield Native App to your phone...
    %ADB% install -r "%~dp0app-debug.apk"
    echo Launching Native App on your phone...
    %ADB% shell am start -n com.socialshield/.MainActivity
) else (
    echo APK not found in directory.
)
echo.

echo [5/5] Launching Web Application in browser on phone and laptop...
%ADB% shell am start -a android.intent.action.VIEW -d "http://localhost:5000"
start http://localhost:5000

echo.
echo ================================================================
echo   SUCCESS! SocialShield is now running on BOTH Laptop and Phone!
echo   Laptop URL : http://localhost:5000
echo   Phone URL  : http://localhost:5000 (routed over USB cable)
echo ================================================================
echo.
echo Streaming device logs (Press Ctrl+C to stop)...
%ADB% logcat -s SocialShield:V *:E
pause
