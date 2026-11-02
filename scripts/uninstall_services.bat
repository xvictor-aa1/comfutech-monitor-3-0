@echo off
setlocal EnableDelayedExpansion

REM ============================================================
REM uninstall_services.bat - Desinstala los servicios NSSM
REM ============================================================

for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"

echo.
echo ============================================================
echo   Desinstalador de servicios Comfutech
echo ============================================================
echo.

REM --- Verificar admin ---
net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Este script debe ejecutarse como Administrador.
    pause
    exit /b 1
)

REM --- Localizar NSSM ---
call "%PROJECT_ROOT%\scripts\_find_nssm.bat"
if errorlevel 1 (
    pause
    exit /b 1
)

REM --- Confirmar ---
set /p CONFIRM="Eliminar los servicios Comfutech? [s/N]: "
if /i not "!CONFIRM!"=="s" (
    echo Cancelado.
    pause
    exit /b 0
)

echo.
echo === Deteniendo servicios ===
"!NSSM_EXE!" stop ComfutechDjango  >nul 2>&1
"!NSSM_EXE!" stop ComfutechMonitor >nul 2>&1

echo.
echo === Eliminando servicios ===
"!NSSM_EXE!" remove ComfutechDjango  confirm
"!NSSM_EXE!" remove ComfutechMonitor confirm

echo.
echo === Verificacion ===
sc query ComfutechDjango >nul 2>&1
if errorlevel 1 (
    echo   ComfutechDjango:  ELIMINADO
) else (
    echo   ComfutechDjango:  AUN EXISTE ^(revisa manualmente^)
)
sc query ComfutechMonitor >nul 2>&1
if errorlevel 1 (
    echo   ComfutechMonitor: ELIMINADO
) else (
    echo   ComfutechMonitor: AUN EXISTE ^(revisa manualmente^)
)

echo.
echo Desinstalacion completa.
pause
exit /b 0