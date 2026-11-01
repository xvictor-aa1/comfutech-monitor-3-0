@echo off
setlocal EnableDelayedExpansion

REM ============================================================
REM instalador.bat - Instalador completo de Comfutech Monitor
REM
REM Ubicacion: raiz del proyecto (junto a manage.py y requirements.txt)
REM
REM Pasos:
REM   1. Verificar permisos de administrador.
REM   2. Detectar Python (3.15+). Si no esta, descargarlo e instalarlo.
REM   3. Crear el entorno virtual en bin\python_local.
REM   4. Instalar las dependencias de requirements.txt.
REM   5. Descargar NSSM y descomprimirlo en bin\nssm.
REM   6. Instalar los servicios de Windows con NSSM.
REM ============================================================

REM --- Detectar raiz del proyecto (el propio script esta en la raiz) ---
for %%I in ("%~dp0.") do set "PROJECT_ROOT=%%~fI"
cd /d "%PROJECT_ROOT%"

echo.
echo ============================================================
echo   INSTALADOR DE COMFUTECH MONITOR
echo ============================================================
echo   Raiz del proyecto: %PROJECT_ROOT%
echo.

REM ============================================================
REM 1. Verificar permisos de administrador
REM ============================================================
net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Este script debe ejecutarse como Administrador.
    echo         Clic derecho ^> Ejecutar como administrador.
    echo.
    pause
    exit /b 1
)

REM ============================================================
REM 2. Detectar Python
REM ============================================================
set "PYTHON_CMD="
set "PYTHON_VERSION="

REM Intentar con "py" (lanzador oficial de Python en Windows)
where py >nul 2>&1
if not errorlevel 1 (
    for /f "tokens=2" %%V in ('py --version 2^>^&1') do set "PYTHON_VERSION=%%V"
    if defined PYTHON_VERSION (
        set "PYTHON_CMD=py -3"
        goto :python_found
    )
)

REM Intentar con "python" directamente
where python >nul 2>&1
if not errorlevel 1 (
    for /f "tokens=2" %%V in ('python --version 2^>^&1') do set "PYTHON_VERSION=%%V"
    if defined PYTHON_VERSION (
        set "PYTHON_CMD=python"
        goto :python_found
    )
)

:python_found
if defined PYTHON_CMD (
    echo   Python detectado: %PYTHON_VERSION% (comando: %PYTHON_CMD%)
    goto :create_venv
)

REM ============================================================
REM 2b. Python no encontrado: descargar e instalar Python 3.15.1
REM ============================================================
echo.
echo   Python no encontrado. Descargando Python 3.15.1...
echo.

set "PYTHON_INSTALLER=%TEMP%\python-3.15.1-amd64.exe"
set "PYTHON_URL=https://www.python.org/ftp/python/3.15.1/python-3.15.1-amd64.exe"

REM Descargar con PowerShell (mas fiable que bitsadmin/curl)
powershell -NoProfile -Command ^
    "Write-Host 'Descargando Python...';" ^
    "Invoke-WebRequest -Uri '%PYTHON_URL%' -OutFile '%PYTHON_INSTALLER%' -UseBasicParsing"

if not exist "%PYTHON_INSTALLER%" (
    echo [ERROR] No se pudo descargar Python.
    echo         Verifica tu conexion a internet.
    pause
    exit /b 1
)

echo   Instalando Python (silencioso)...
"%PYTHON_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0

if errorlevel 1 (
    echo [ERROR] La instalacion de Python fallo.
    pause
    exit /b 1
)

REM Refrescar variables de entorno para detectar Python recien instalado
call :refresh_env

REM Volver a detectar Python
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python se instalo pero no se detecta en PATH.
    echo         Reinicia el equipo o agrega Python manualmente al PATH.
    pause
    exit /b 1
)
set "PYTHON_CMD=python"

echo   Python 3.15.1 instalado correctamente.
echo.

REM ============================================================
REM 3. Crear entorno virtual en bin\python_local
REM ============================================================
:create_venv
echo.
echo === Creando entorno virtual en bin\python_local ===

if not exist "%PROJECT_ROOT%\bin" mkdir "%PROJECT_ROOT%\bin"

if exist "%PROJECT_ROOT%\bin\python_local\Scripts\python.exe" (
    echo   El entorno virtual ya existe. Se omite la creacion.
) else (
    %PYTHON_CMD% -m venv "%PROJECT_ROOT%\bin\python_local"
    if errorlevel 1 (
        echo [ERROR] No se pudo crear el entorno virtual.
        pause
        exit /b 1
    )
    echo   Entorno virtual creado.
)

REM ============================================================
REM 4. Instalar dependencias
REM ============================================================
echo.
echo === Instalando dependencias de requirements.txt ===

set "VENV_PYTHON=%PROJECT_ROOT%\bin\python_local\Scripts\python.exe"

if not exist "%PROJECT_ROOT%\requirements.txt" (
    echo [ERROR] No se encontro requirements.txt en la raiz del proyecto.
    pause
    exit /b 1
)

"%VENV_PYTHON%" -m pip install --upgrade pip
if errorlevel 1 (
    echo [ERROR] No se pudo actualizar pip.
    pause
    exit /b 1
)

"%VENV_PYTHON%" -m pip install -r "%PROJECT_ROOT%\requirements.txt"
if errorlevel 1 (
    echo [ERROR] Fallo la instalacion de dependencias.
    pause
    exit /b 1
)

echo   Dependencias instaladas correctamente.
echo.

REM ============================================================
REM 5. Descargar y descomprimir NSSM en bin\nssm
REM ============================================================
echo === Descargando NSSM ===

if not exist "%PROJECT_ROOT%\bin\nssm" mkdir "%PROJECT_ROOT%\bin\nssm"

set "NSSM_ZIP=%TEMP%\nssm-2.24.zip"
set "NSSM_URL=https://nssm.cc/release/nssm-2.24.zip"

powershell -NoProfile -Command ^
    "Write-Host 'Descargando NSSM...';" ^
    "Invoke-WebRequest -Uri '%NSSM_URL%' -OutFile '%NSSM_ZIP%' -UseBasicParsing"

if not exist "%NSSM_ZIP%" (
    echo [ERROR] No se pudo descargar NSSM.
    pause
    exit /b 1
)

echo   Descomprimiendo NSSM...
powershell -NoProfile -Command ^
    "Expand-Archive -Path '%NSSM_ZIP%' -DestinationPath '%PROJECT_ROOT%\bin\nssm' -Force"

REM El zip extrae una carpeta nssm-2.24; mover su contenido a bin\nssm
if exist "%PROJECT_ROOT%\bin\nssm\nssm-2.24" (
    xcopy /E /I /Y "%PROJECT_ROOT%\bin\nssm\nssm-2.24\*" "%PROJECT_ROOT%\bin\nssm\" >nul
    rmdir /S /Q "%PROJECT_ROOT%\bin\nssm\nssm-2.24"
)

if not exist "%PROJECT_ROOT%\bin\nssm\win64\nssm.exe" (
    echo [ERROR] No se encontro nssm.exe despues de descomprimir.
    pause
    exit /b 1
)

echo   NSSM 2.24 descomprimido en bin\nssm\win64\nssm.exe
echo.

REM ============================================================
REM 6. Instalar servicios con NSSM
REM ============================================================
echo === Instalando servicios de Windows ===

call "%PROJECT_ROOT%\scripts\install_services.bat"
if errorlevel 1 (
    echo [ERROR] Fallo la instalacion de servicios.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   INSTALACION COMPLETA
echo.
echo   Servicios instalados:
echo     - ComfutechDjango  (Waitress en :8000)
echo     - ComfutechMonitor (Scheduler de polling)
echo.
echo   Accede a: http://localhost:8000/
echo   Logs en:  %PROJECT_ROOT%\logs\
echo ============================================================
pause
exit /b 0

REM ============================================================
REM Subrutina: refrescar variables de entorno
REM ============================================================
:refresh_env
REM Recarga el PATH desde el registro para detectar Python recien instalado
for /f "tokens=2*" %%A in ('reg query "HKCU\Environment" /v PATH 2^>nul ^| findstr /i "PATH"') do set "USER_PATH=%%B"
for /f "tokens=2*" %%A in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v PATH 2^>nul ^| findstr /i "PATH"') do set "SYS_PATH=%%B"
set "PATH=%SYS_PATH%;%USER_PATH%"
exit /b 0