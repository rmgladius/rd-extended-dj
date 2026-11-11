@echo off
rem Gera o programa para Windows em build\dist\Extended DJ\Extended DJ.exe
rem Antes, coloque o ffmpeg (versao "shared": ffmpeg.exe, ffprobe.exe e as DLLs) em build\ffmpeg
rem e rode empacotar\juntar_modelos.py para preencher build\modelos.
setlocal
cd /d "%~dp0\.."
set "UV=uv"
if exist "build\ferramentas\uv.exe" set "UV=build\ferramentas\uv.exe"
set "UV_PROJECT_ENVIRONMENT=%CD%\build\venv-win"
if not exist "build\ffmpeg\ffmpeg.exe" (
  echo Falta o ffmpeg em build\ffmpeg
  exit /b 1
)
"%UV%" sync --frozen --group empacotar || exit /b 1
if not exist "build\modelos\demucs\htdemucs.yaml" (
  "%UV%" run --frozen python empacotar\juntar_modelos.py build\modelos || exit /b 1
)
"%UV%" run --frozen pyinstaller empacotar\extdj.spec --noconfirm --clean --distpath build\dist --workpath build\pyinstaller || exit /b 1
echo.
echo Pronto: build\dist\Extended DJ\Extended DJ.exe
