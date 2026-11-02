@echo off
setlocal EnableDelayedExpansion

REM ============================================================
REM restart_services.bat - Reinicia ambos servicios
REM ============================================================

for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"

REM --- Verificar admin ---
net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Ejecutar como Administrador.
    pause
    exit /b 1
)

REM --- Localizar NSSM ---
call "%PROJECT_ROOT%\scripts\_find_nssm.bat"
if errorlevel 1 (
    pause
    exit /b 1
)

echo === Reiniciando servicios ===
"!NSSM_EXE!" restart ComfutechDjango
"!NSSM_EXE!" restart ComfutechMonitor

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