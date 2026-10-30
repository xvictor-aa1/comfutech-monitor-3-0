@echo off
setlocal

REM ============================================================
REM uninstall_services.bat - Desinstala los servicios NSSM
REM ============================================================

echo.
echo ============================================================
echo   Desinstalador de servicios Comfutech
echo ============================================================
echo.

REM --- Verificar permisos de admin ---
net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Este script debe ejecutarse como Administrador.
    pause
    exit /b 1
)

REM --- Verificar NSSM ---
where nssm >nul 2>&1
if errorlevel 1 (
    echo [ERROR] NSSM no esta en PATH.
    pause
    exit /b 1
)

REM --- Confirmar ---
set /p CONFIRM="¿Eliminar los servicios Comfutech? [s/N]: "
if /i not "%CONFIRM%"=="s" (
    echo Cancelado.
    pause
    exit /b 0
)

echo.
echo === Deteniendo servicios ===
nssm stop ComfutechDjango
nssm stop ComfutechMonitor

echo.
echo === Eliminando servicios ===
nssm remove ComfutechDjango confirm
nssm remove ComfutechMonitor confirm

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