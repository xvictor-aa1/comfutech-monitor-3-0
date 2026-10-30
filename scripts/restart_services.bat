@echo off
setlocal

REM ============================================================
REM restart_services.bat - Reinicia ambos servicios
REM ============================================================

net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Ejecutar como Administrador.
    pause
    exit /b 1
)

echo === Reiniciando servicios ===
nssm restart ComfutechDjango
nssm restart ComfutechMonitor

timeout /t 2 /nobreak >nul
echo.
echo Django:  & nssm status ComfutechDjango
echo Monitor: & nssm status ComfutechMonitor
pause