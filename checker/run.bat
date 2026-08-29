@echo off
echo ===================================================
echo  VisionMart Standalone Desktop App - Khoi dong...
echo ===================================================
cd /d "%~dp0"

REM Kiem tra Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [LOI] Khong tim thay Python. Cai Python 3.9+ truoc.
    pause
    exit /b 1
)

REM Cai thu vien neu chua co
echo Dang kiem tra va cai dat cac thu vien (Tkinter Desktop GUI)...
python -m pip install -q -r requirements.txt

REM Chay Desktop App
echo.
echo [OK] Dang khoi dong ung dung cua so Desktop (Tkinter)...
echo.
python main.py
pause
