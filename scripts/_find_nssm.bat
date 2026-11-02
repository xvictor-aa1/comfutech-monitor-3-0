@echo off
REM ============================================================
REM _find_nssm.bat - Localiza nssm.exe y exporta NSSM_EXE
REM ============================================================
REM Uso: call _find_nssm.bat
REM Exporta: NSSM_EXE (ruta completa o vacío si no se encuentra)
REM Devuelve errorlevel 1 si no lo encuentra.
REM
REM Prioridad de búsqueda:
REM   1. %PROJECT_ROOT%\bin\nssm\win64\nssm.exe  (instalado por instalador.bat)
REM   2. %PROJECT_ROOT%\bin\nssm\nssm.exe        (por si se movió)
REM   3. PATH del sistema (resuelto a ruta completa con %%~$PATH:I)
REM ============================================================

set "NSSM_EXE="

if not defined PROJECT_ROOT (
    for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"
)

REM --- 1. bin\nssm\win64\ (instalado por instalador.bat) ---
if exist "%PROJECT_ROOT%\bin\nssm\win64\nssm.exe" (
    set "NSSM_EXE=%PROJECT_ROOT%\bin\nssm\win64\nssm.exe"
    exit /b 0
)

REM --- 2. bin\nssm\ (por si el usuario lo movió) ---
if exist "%PROJECT_ROOT%\bin\nssm\nssm.exe" (
    set "NSSM_EXE=%PROJECT_ROOT%\bin\nssm\nssm.exe"
    exit /b 0
)

REM --- 3. PATH del sistema → resolver a ruta completa ---
REM    %%~$PATH:I expande al path completo del ejecutable encontrado.
for %%I in (nssm.exe) do (
    if not "%%~$PATH:I"=="" (
        set "NSSM_EXE=%%~$PATH:I"
    )
)

if defined NSSM_EXE (
    exit /b 0
)

echo.
echo [ERROR] No se encontro nssm.exe.
echo.
echo         Opciones:
echo         1. Ejecuta: instalador.bat
echo            (lo descarga automaticamente en bin\nssm\win64\)
echo         2. O instala NSSM en el PATH del sistema
echo            (copia nssm.exe a C:\Windows\System32\)
echo.
exit /b 1