@echo off
chcp 65001 >nul
rem Lance le photobooth (Windows). Installe les dependances au premier lancement.
rem Usage : lancer.bat                      -> fenetre + camera simulee (test)
rem         lancer.bat --camera <option>    -> vos propres options (voir --help)
cd /d "%~dp0"

set PY=
py -3 --version >nul 2>nul && set PY=py -3
if "%PY%"=="" (
  python --version >nul 2>nul && set PY=python
)
if "%PY%"=="" (
  echo.
  echo Python 3 n'est pas installe sur ce PC ^(le raccourci "python" de Windows ne compte pas^).
  echo Installez-le depuis https://www.python.org/downloads/
  echo et COCHEZ "Add python.exe to PATH" sur le premier ecran de l'installeur.
  echo Puis relancez ce script.
  echo.
  pause
  exit /b 1
)

if not exist .venv\Scripts\activate.bat (
  echo Creation de l'environnement Python...
  %PY% -m venv .venv
  if errorlevel 1 ( pause & exit /b 1 )
)
call .venv\Scripts\activate.bat

if not exist .venv\deps_ok (
  echo Installation des dependances ^(une seule fois^)...
  python -m pip install -q --upgrade pip
  pip install -q --only-binary=:all: pillow numpy flask
  if errorlevel 1 ( pause & exit /b 1 )
  pip install -q --only-binary=:all: pygame
  if errorlevel 1 (
    echo pygame indisponible pour cette version de Python, installation de pygame-ce a la place...
    pip install -q --only-binary=:all: pygame-ce
    if errorlevel 1 ( pause & exit /b 1 )
  )
  echo ok> .venv\deps_ok
)

if "%~1"=="" (
  python photobooth.py --windowed --camera fake
) else (
  python photobooth.py %*
)
if errorlevel 1 pause
