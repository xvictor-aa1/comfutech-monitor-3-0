@echo off
setlocal

REM ============================================================
REM view_logs.bat - Muestra los ultimos logs de los servicios
REM ============================================================

for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"

echo === Django (ultimas 30 lineas) ===
if exist "%PROJECT_ROOT%\logs\django_err.log" (
    powershell -Command "Get-Content '%PROJECT_ROOT%\logs\django_err.log' -Tail 30"
) else (
    echo   (sin log)
)

echo.
echo === Monitor (ultimas 30 lineas) ===
if exist "%PROJECT_ROOT%\logs\monitor_err.log" (
    powershell -Command "Get-Content '%PROJECT_ROOT%\logs\monitor_err.log' -Tail 30"
) else (
    echo   (sin log)
)

pause