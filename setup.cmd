@echo off
setlocal
pushd "%~dp0"
python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 goto python_error
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -B scripts\check_environment.py
if errorlevel 1 goto failed
echo Setup complete. Run: run_download.cmd --episode 3
popd
exit /b 0
:python_error
echo Install Python 3.10+ and enable Add Python to PATH first.
:failed
echo Setup incomplete. Resolve the errors above, then rerun setup.cmd.
popd
exit /b 1
