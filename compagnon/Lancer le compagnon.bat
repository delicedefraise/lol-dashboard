@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo   Python n'est pas installe sur ce PC.
  echo   Installe-le depuis le Microsoft Store ^(cherche "Python 3.12"^) puis relance ce fichier.
  echo.
  start "" "https://apps.microsoft.com/search?query=python"
  pause
  exit /b
)
python compagnon.py %*
pause
