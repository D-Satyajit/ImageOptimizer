@echo off
rem Launches Image Optimizer Pro, installing its Python packages on first run.
setlocal
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
    echo Python 3 was not found on PATH.
    echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
    pause
    exit /b 1
)

python -c "import customtkinter, PIL" >nul 2>&1
if errorlevel 1 (
    echo Installing required packages...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo Package installation failed. See the messages above.
        pause
        exit /b 1
    )
)

rem Run with the windowless interpreter from the same Python install, so no console stays open
for /f "usebackq delims=" %%P in (`python -c "import os, sys; print(os.path.join(os.path.dirname(sys.executable), 'pythonw.exe'))"`) do set "PYTHONW=%%P"
if not exist "%PYTHONW%" set "PYTHONW=python"

start "" "%PYTHONW%" "%~dp0image_optimizer.pyw"
