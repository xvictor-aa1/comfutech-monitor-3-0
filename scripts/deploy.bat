@echo off
setlocal EnableDelayedExpansion

REM ============================================================
REM deploy.bat - Detiene servicios, migra, recolecta estaticos
REM              y reinicia
REM ============================================================

for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"
cd /d "%PROJECT_ROOT%"

REM --- Detectar venv ---
call "%PROJECT_ROOT%\scripts\_detect_venv.bat"
if errorlevel 1 exit /b 1

REM --- Localizar NSSM ---
call "%PROJECT_ROOT%\scripts\_find_nssm.bat"
if errorlevel 1 exit /b 1

echo === Deteniendo servicios ===
"!NSSM_EXE!" stop ComfutechDjango
"!NSSM_EXE!" stop ComfutechMonitor

echo === Aplicando migraciones ===
"%PYTHON_EXE%" manage.py migrate
if errorlevel 1 (
    echo [ERROR] Fallo la migracion. Los servicios quedan detenidos.
    pause
    exit /b 1
)

echo === Recolectando estaticos ===
"%PYTHON_EXE%" manage.py collectstatic --no-input
if errorlevel 1 (
    echo [ERROR] Fallo collectstatic. Los servicios quedan detenidos.
    pause
    exit /b 1
)

echo === Reiniciando servicios ===
"!NSSM_EXE!" start ComfutechDjango
"!NSSM_EXE!" start ComfutechMonitor

timeout /t 2 /nobreak >nul

echo.
echo === Estado ===
call :print_status "Django " ComfutechDjango
call :print_status "Monitor" ComfutechMonitor
pause
exit /b 0

:print_status
set "STATUS_LABEL=%~1"
set "STATUS_SVC=%~2"
set "STATUS_VALUE=(desconocido)"
for /f "delims=" %%S in ('"!NSSM_EXE!" status %STATUS_SVC% 2^>nul') do (
    set "STATUS_VALUE=%%S"
)
echo   %STATUS_LABEL%: !STATUS_VALUE!
exit /b 0