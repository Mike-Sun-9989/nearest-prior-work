@echo off
setlocal
cd /d "%~dp0"
if not exist "setup_local.py" goto not_extracted
rem Private Python, used only when no supported copy is installed. Keep in step with start.sh.
set "PY_RELEASE=20261013"
set "PY_VERSION=3.13.16"
set "PY_SHA256=7aba3985d4cee1c7cacb963ca6aa08a5d3e695d7f9609d9fabc56f22ddcf5a06"
set "PY_FILE=cpython-%PY_VERSION%+%PY_RELEASE%-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
set "PY_URL=https://github.com/astral-sh/python-build-standalone/releases/download/%PY_RELEASE%/%PY_FILE%"
set "CHECK=import sys;sys.exit(not ((3,11)<=sys.version_info[:2]<=(3,13) and sys.maxsize>2**32))"
rem The Python install manager must not download a runtime or ask a question during these checks.
set "PYTHON_MANAGER_AUTOMATIC_INSTALL=false"
set "PYTHON_MANAGER_CONFIRM=false"
set "PY="
call :try ".runtime\python\python.exe"
call :try "py -3.13"
call :try "py -3.12"
call :try "py -3.11"
call :try "python"
if defined PY goto run

set "ARCH=%PROCESSOR_ARCHITEW6432%"
if not defined ARCH set "ARCH=%PROCESSOR_ARCHITECTURE%"
if /i not "%ARCH%"=="AMD64" goto unsupported
set "TOOLS=%SystemRoot%\System32"
if not exist "%TOOLS%\curl.exe" goto manual
if not exist "%TOOLS%\tar.exe" goto manual
if not exist "%TOOLS%\certutil.exe" goto manual

echo Setting up a private copy of Python for this app, about 25 MB. Nothing else on your computer changes.
if not exist ".runtime" mkdir ".runtime"
"%TOOLS%\curl.exe" -fL --retry 3 --retry-delay 3 --connect-timeout 30 --progress-bar -o ".runtime\python.tar.gz" "%PY_URL%"
if errorlevel 1 goto manual
"%TOOLS%\certutil.exe" -hashfile ".runtime\python.tar.gz" SHA256 | "%TOOLS%\findstr.exe" /i "%PY_SHA256%" >nul
if errorlevel 1 goto bad_download
if exist ".runtime\incoming" rd /s /q ".runtime\incoming"
mkdir ".runtime\incoming"
"%TOOLS%\tar.exe" -xzf ".runtime\python.tar.gz" -C ".runtime\incoming"
if errorlevel 1 goto manual
".runtime\incoming\python\python.exe" -c "%CHECK%"
if errorlevel 1 goto manual
move ".runtime\incoming\python" ".runtime\python" >nul
if errorlevel 1 goto manual
rd /s /q ".runtime\incoming"
del ".runtime\python.tar.gz"
set "PY=.runtime\python\python.exe"

:run
set "PYTHON_MANAGER_AUTOMATIC_INSTALL="
set "PYTHON_MANAGER_CONFIRM="
call %PY% setup_local.py %*
if errorlevel 1 goto stop
exit /b 0

:try
if defined PY exit /b 0
rem call also handles a python.cmd or python.bat shim, which would otherwise end this script.
call %~1 -c "%CHECK%" >nul 2>nul <nul
if not errorlevel 1 set "PY=%~1"
exit /b 0

:not_extracted
echo Extract the whole ZIP into a normal folder first, then open start.bat from that folder.
goto stop

:unsupported
echo This release requires Windows 10 or 11 on an x64 computer. Windows on ARM is not supported.
goto stop

:bad_download
del ".runtime\python.tar.gz"
echo The Python download was damaged or incomplete. Run start.bat again to retry.
goto stop

:manual
echo Python could not be set up automatically. Check your internet connection and run start.bat again.
echo If it still stops here, install Python 3.13 from https://www.python.org/downloads/release/python-31317/
echo using the Windows installer 64-bit and the Install Now button, then run start.bat again.

:stop
pause
exit /b 1
