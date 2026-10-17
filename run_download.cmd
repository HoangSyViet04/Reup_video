@echo off
setlocal
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0scripts\download_nguonc.py" %*
) else (
    python "%~dp0scripts\download_nguonc.py" %*
)
exit /b %errorlevel%
