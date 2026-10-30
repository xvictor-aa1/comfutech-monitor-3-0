@echo off
setlocal EnableDelayedExpansion

REM ============================================================
REM run_monitor.bat - Arranca el monitor (auto-detecta rutas)
REM ============================================================

REM --- Detectar raiz del proyecto ---
for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"
cd /d "%PROJECT_ROOT%"

REM --- Detectar entorno virtual ---
call "%PROJECT_ROOT%\scripts\_detect_venv.bat"
if errorlevel 1 exit /b 1

REM --- Arrancar monitor ---
"%PYTHON_EXE%" manage.py run_monitor