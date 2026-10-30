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

REM --- Verificar NSSM ---
where nssm >nul 2>&1
if errorlevel 1 (
    echo [ERROR] NSSM no esta en PATH.
    echo.
    echo         Descarga: https://nssm.cc/download
    echo         Descomprime y copia nssm.exe a C:\Windows\System32\
    echo.
    pause
    exit /b 1
)

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
nssm stop ComfutechDjango >nul 2>&1
nssm stop ComfutechMonitor >nul 2>&1
nssm remove ComfutechDjango confirm >nul 2>&1
nssm remove ComfutechMonitor confirm >nul 2>&1

REM ============================================================
REM SERVICIO 1: ComfutechDjango (Waitress)
REM ============================================================
echo.
echo === Instalando ComfutechDjango ===

nssm install ComfutechDjango "%PYTHON_EXE%"
nssm set ComfutechDjango AppDirectory "%PROJECT_ROOT%"
nssm set ComfutechDjango AppParameters "-m waitress --listen=0.0.0.0:8000 --threads=16 sistema.wsgi:application"
nssm set ComfutechDjango DisplayName "Comfutech Django (Waitress)"
nssm set ComfutechDjango Description "Servidor web Django para Comfutech Monitor"
nssm set ComfutechDjango Start SERVICE_AUTO_START
nssm set ComfutechDjango AppStdout "%PROJECT_ROOT%\logs\django_out.log"
nssm set ComfutechDjango AppStderr "%PROJECT_ROOT%\logs\django_err.log"
nssm set ComfutechDjango AppRotateFiles 1
nssm set ComfutechDjango AppRotateBytes 10485760
nssm set ComfutechDjango AppExit Default Restart
nssm set ComfutechDjango AppRestartDelay 5000
nssm set ComfutechDjango AppEnvironmentExtra PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1

REM ============================================================
REM SERVICIO 2: ComfutechMonitor
REM ============================================================
echo.
echo === Instalando ComfutechMonitor ===

nssm install ComfutechMonitor "%PYTHON_EXE%"
nssm set ComfutechMonitor AppDirectory "%PROJECT_ROOT%"
nssm set ComfutechMonitor AppParameters "manage.py run_monitor"
nssm set ComfutechMonitor DisplayName "Comfutech Monitor de Red"
nssm set ComfutechMonitor Description "Monitor SNMP/ICMP/TCP de Comfutech"
nssm set ComfutechMonitor Start SERVICE_AUTO_START
nssm set ComfutechMonitor AppStdout "%PROJECT_ROOT%\logs\monitor_out.log"
nssm set ComfutechMonitor AppStderr "%PROJECT_ROOT%\logs\monitor_err.log"
nssm set ComfutechMonitor AppRotateFiles 1
nssm set ComfutechMonitor AppRotateBytes 10485760
nssm set ComfutechMonitor AppExit Default Restart
nssm set ComfutechMonitor AppRestartDelay 10000
nssm set ComfutechMonitor AppEnvironmentExtra PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1

REM ============================================================
REM Arrancar servicios
REM ============================================================
echo.
echo === Arrancando servicios ===
nssm start ComfutechDjango
nssm start ComfutechMonitor

REM --- Verificar despues de 3 segundos ---
timeout /t 3 /nobreak >nul

echo.
echo === Estado final ===
echo Django:  & nssm status ComfutechDjango
echo Monitor: & nssm status ComfutechMonitor

echo.
echo ============================================================
echo   Instalacion completa
echo.
echo   Accede a: http://localhost:8000/
echo   Logs en:  %PROJECT_ROOT%\logs\
echo ============================================================
pause