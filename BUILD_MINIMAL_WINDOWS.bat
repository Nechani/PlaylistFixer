@echo off
setlocal
cd /d "%~dp0"

echo [1/5] Checking Python 3.12...
py -3.12 --version >nul 2>&1
if errorlevel 1 (
  echo Python 3.12 was not found.
  echo Install Python 3.12 and make sure the Python launcher is available.
  pause
  exit /b 1
)

echo [2/5] Creating a clean build environment...
if exist ".venv-build" rmdir /s /q ".venv-build"
py -3.12 -m venv ".venv-build"
if errorlevel 1 goto :failed

echo [3/5] Installing only required packages...
call ".venv-build\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed
call ".venv-build\Scripts\python.exe" -m pip install -r requirements-build-minimal.txt
if errorlevel 1 goto :failed

echo [4/5] Removing previous build output...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

echo [5/5] Building minimal distribution...
call ".venv-build\Scripts\python.exe" -m PyInstaller --clean --noconfirm PlaylistFixer.spec
if errorlevel 1 goto :failed

echo.
echo Build completed:
echo   %CD%\dist\PlaylistFixer
for /f "tokens=3" %%A in ('dir /s /-c "dist\PlaylistFixer" ^| findstr /c:"File(s)"') do set BYTES=%%A
echo Test PlaylistFixer.exe before publishing it.
pause
exit /b 0

:failed
echo.
echo Build failed. Review the error messages above.
pause
exit /b 1
