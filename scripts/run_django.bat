@echo off
setlocal EnableDelayedExpansion

REM ============================================================
REM run_django.bat - Arranca Django con Waitress (auto-detecta rutas)
REM ============================================================

REM --- Detectar raiz del proyecto ---
for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"
cd /d "%PROJECT_ROOT%"

REM --- Detectar entorno virtual ---
call "%PROJECT_ROOT%\scripts\_detect_venv.bat"
if errorlevel 1 exit /b 1

REM --- Arrancar Waitress ---
"%PYTHON_EXE%" -m waitress ^
    --listen=0.0.0.0:8000 ^
    --threads=16 ^
    --channel-timeout=120 ^
    sistema.wsgi:application