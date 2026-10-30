@echo off
setlocal

for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"
cd /d "%PROJECT_ROOT%"

call "%PROJECT_ROOT%\scripts\_detect_venv.bat"
if errorlevel 1 exit /b 1

echo === Deteniendo servicios ===
nssm stop ComfutechDjango
nssm stop ComfutechMonitor

echo === Aplicando migraciones ===
"%PYTHON_EXE%" manage.py migrate

echo === Recolectando estaticos ===
"%PYTHON_EXE%" manage.py collectstatic --no-input

echo === Reiniciando servicios ===
nssm start ComfutechDjango
nssm start ComfutechMonitor

timeout /t 2 /nobreak >nul
nssm status ComfutechDjango
nssm status ComfutechMonitor
pause