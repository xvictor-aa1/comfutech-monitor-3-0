@echo off
REM ============================================================
REM _detect_venv.bat - Detecta el entorno virtual del proyecto
REM Uso: call _detect_venv.bat
REM Exporta: PYTHON_EXE, VENV_NAME
REM Devuelve errorlevel 1 si no lo encuentra.
REM ============================================================

set "PYTHON_EXE="
set "VENV_NAME="

if not defined PROJECT_ROOT (
    for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"
)

for %%V in (python_local venv_django venv .venv env) do (
    if exist "%PROJECT_ROOT%\%%V\Scripts\python.exe" (
        set "PYTHON_EXE=%PROJECT_ROOT%\%%V\Scripts\python.exe"
        set "VENV_NAME=%%V"
        goto :found
    )
)

:found
if "%PYTHON_EXE%"=="" (
    echo.
    echo [ERROR] No se encontro el entorno virtual en:
    echo         %PROJECT_ROOT%
    echo.
    echo         Buscado en: python_local, venv_django, venv, .venv, env
    echo.
    exit /b 1
)
exit /b 0