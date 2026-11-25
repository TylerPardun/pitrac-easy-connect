@echo off
rem Builds the Windows installer on this computer. Nothing is uploaded anywhere.
setlocal
title PiTrac Easy-Connect
cd /d "%~dp0"

if not exist "packaging\make_installer.py" (
    echo.
    echo Unpack the whole source zip first, then run this from inside it.
    goto failed
)

py -3.13 -c "import sys" >nul 2>nul
if not errorlevel 1 goto build

echo.
echo This needs Python 3.13, which is not on this computer.
choice /C YN /N /M "Install it now with Windows' own package manager? [Y/N] "
if errorlevel 2 goto failed
winget install --id Python.Python.3.13 -e
echo.
echo When that has finished, close this window and run this again.
pause
exit /b 1

:build
py -3.13 "packaging\make_installer.py" %*
if errorlevel 1 goto failed
echo.
echo The installer is in the dist folder here.
pause
exit /b 0

:failed
echo.
echo The installer was not built.
pause
exit /b 1
