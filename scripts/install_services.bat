@echo off
setlocal EnableDelayedExpansion

REM ============================================================
REM install_services.bat - Instala los servicios NSSM
REM ============================================================

REM --- Detectar raiz ---
for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"

echo.
echo ============================================================
echo   Instalador de servicios Comfutech
echo ============================================================
echo   Raiz del proyecto: %PROJECT_ROOT%
echo.

REM --- Verificar permisos de admin ---
net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Este script debe ejecutarse como Administrador.
    echo         Clic derecho ^> Ejecutar como administrador.
    pause
    exit /b 1
)

REM --- Localizar NSSM (preferir el de bin\nssm, fallback a PATH) ---
set "NSSM_EXE="
if exist "%PROJECT_ROOT%\bin\nssm\win64\nssm.exe" (
    set "NSSM_EXE=%PROJECT_ROOT%\bin\nssm\win64\nssm.exe"
) else (
    where nssm >nul 2>&1
    if not errorlevel 1 (
        set "NSSM_EXE=nssm"
    )
)

if "!NSSM_EXE!"=="" (
    echo [ERROR] No se encontro nssm.exe.
    echo.
    echo         Ejecuta primero: scripts\installer.bat
    echo         (descarga NSSM en bin\nssm\win64)
    echo.
    pause
    exit /b 1
)

echo   NSSM:   !NSSM_EXE!
echo.

REM --- Detectar Python del venv ---
call "%PROJECT_ROOT%\scripts\_detect_venv.bat"
if errorlevel 1 (
    pause
    exit /b 1
)

echo   Python:  %PYTHON_EXE%
echo   Venv:    %VENV_NAME%
echo.

REM --- Verificar manage.py ---
if not exist "%PROJECT_ROOT%\manage.py" (
    echo [ERROR] No se encontro manage.py en:
    echo         %PROJECT_ROOT%
    pause
    exit /b 1
)

REM --- Crear carpeta de logs ---
if not exist "%PROJECT_ROOT%\logs" mkdir "%PROJECT_ROOT%\logs"

REM --- Eliminar servicios previos si existen ---
echo === Limpiando servicios previos ===
"!NSSM_EXE!" stop ComfutechDjango >nul 2>&1
"!NSSM_EXE!" stop ComfutechMonitor >nul 2>&1
"!NSSM_EXE!" remove ComfutechDjango confirm >nul 2>&1
"!NSSM_EXE!" remove ComfutechMonitor confirm >nul 2>&1

REM ============================================================
REM SERVICIO 1: ComfutechDjango (Waitress)
REM ============================================================
echo.
echo === Instalando ComfutechDjango ===

"!NSSM_EXE!" install ComfutechDjango "%PYTHON_EXE%"
"!NSSM_EXE!" set ComfutechDjango AppDirectory "%PROJECT_ROOT%"
"!NSSM_EXE!" set ComfutechDjango AppParameters "-m waitress --listen=0.0.0.0:8000 --threads=16 sistema.wsgi:application"
"!NSSM_EXE!" set ComfutechDjango DisplayName "Comfutech Django (Waitress)"
"!NSSM_EXE!" set ComfutechDjango Description "Servidor web Django para Comfutech Monitor"
"!NSSM_EXE!" set ComfutechDjango Start SERVICE_AUTO_START
"!NSSM_EXE!" set ComfutechDjango AppStdout "%PROJECT_ROOT%\logs\django_out.log"
"!NSSM_EXE!" set ComfutechDjango AppStderr "%PROJECT_ROOT%\logs\django_err.log"
"!NSSM_EXE!" set ComfutechDjango AppRotateFiles 1
"!NSSM_EXE!" set ComfutechDjango AppRotateBytes 10485760
"!NSSM_EXE!" set ComfutechDjango AppExit Default Restart
"!NSSM_EXE!" set ComfutechDjango AppRestartDelay 5000
"!NSSM_EXE!" set ComfutechDjango AppEnvironmentExtra PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1

REM ============================================================
REM SERVICIO 2: ComfutechMonitor
REM ============================================================
echo.
echo === Instalando ComfutechMonitor ===

"!NSSM_EXE!" install ComfutechMonitor "%PYTHON_EXE%"
"!NSSM_EXE!" set ComfutechMonitor AppDirectory "%PROJECT_ROOT%"
"!NSSM_EXE!" set ComfutechMonitor AppParameters "manage.py run_monitor"
"!NSSM_EXE!" set ComfutechMonitor DisplayName "Comfutech Monitor de Red"
"!NSSM_EXE!" set ComfutechMonitor Description "Monitor SNMP/ICMP/TCP de Comfutech"
"!NSSM_EXE!" set ComfutechMonitor Start SERVICE_AUTO_START
"!NSSM_EXE!" set ComfutechMonitor AppStdout "%PROJECT_ROOT%\logs\monitor_out.log"
"!NSSM_EXE!" set ComfutechMonitor AppStderr "%PROJECT_ROOT%\logs\monitor_err.log"
"!NSSM_EXE!" set ComfutechMonitor AppRotateFiles 1
"!NSSM_EXE!" set ComfutechMonitor AppRotateBytes 10485760
"!NSSM_EXE!" set ComfutechMonitor AppExit Default Restart
"!NSSM_EXE!" set ComfutechMonitor AppRestartDelay 10000
"!NSSM_EXE!" set ComfutechMonitor AppEnvironmentExtra PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1

REM ============================================================
REM Arrancar servicios
REM ============================================================
echo.
echo === Arrancando servicios ===
"!NSSM_EXE!" start ComfutechDjango
"!NSSM_EXE!" start ComfutechMonitor

REM --- Verificar despues de 3 segundos ---
timeout /t 3 /nobreak >nul

echo.
echo === Estado final ===
echo Django:  & "!NSSM_EXE!" status ComfutechDjango
echo Monitor: & "!NSSM_EXE!" status ComfutechMonitor

echo.
echo ============================================================
echo   Instalacion completa
echo.
echo   Accede a: http://localhost:8000/
echo   Logs en:  %PROJECT_ROOT%\logs\
echo ============================================================
pause