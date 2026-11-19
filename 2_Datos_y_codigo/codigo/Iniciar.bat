@echo off
REM ==================================================================
REM  Autosimilitud LAN - iniciador (doble clic)
REM  La primera vez crea el entorno .venv e instala las dependencias.
REM  Despues abre la ventana del programa sin consola.
REM ==================================================================
setlocal
cd /d "%~dp0"
title Autosimilitud LAN - iniciando

if exist ".venv\Scripts\pythonw.exe" goto :deps

echo Preparando el programa por primera vez (1-3 minutos)...
set "PYCMD="
where py >nul 2>nul && set "PYCMD=py -3"
if not defined PYCMD (
    where python >nul 2>nul && set "PYCMD=python"
)
if not defined PYCMD goto :nopython
%PYCMD% -m venv .venv
if errorlevel 1 goto :nopython

:deps
if exist ".venv\.deps_ok" goto :launch
echo Instalando dependencias (numpy, pandas, scipy, matplotlib)...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :piperror
echo ok> ".venv\.deps_ok"

:launch
start "" ".venv\Scripts\pythonw.exe" "%~dp0app_gui.py"
exit /b 0

:nopython
echo.
echo No se encontro Python 3.
echo Instalelo desde https://www.python.org/downloads/ marcando la casilla
echo "Add python.exe to PATH" y vuelva a hacer doble clic en Iniciar.bat
echo.
pause
exit /b 1

:piperror
echo.
echo No se pudieron instalar las dependencias. Revise su conexion a internet
echo y vuelva a intentarlo. Si el problema sigue, borre la carpeta .venv
echo y haga doble clic otra vez en Iniciar.bat
echo.
pause
exit /b 1
