@echo off
rem Gera o programa para Windows.
rem   construir.bat        com o PyTorch para placa NVIDIA (uns 5 GB): build\dist\RD Extended DJ\
rem   construir.bat leve   so com o processador, a versao publicada no GitHub: build\dist-leve\RD Extended DJ\
rem O GitHub aceita arquivos de ate 2 GB por download, e por isso a versao publicada e a leve.
rem Antes, coloque o ffmpeg (versao "shared": ffmpeg.exe, ffprobe.exe e as DLLs) em build\ffmpeg
rem e rode empacotar\juntar_modelos.py para preencher build\modelos.
setlocal
cd /d "%~dp0\.."
set "UV=uv"
if exist "build\ferramentas\uv.exe" set "UV=build\ferramentas\uv.exe"
set "VERSAO=%~1"
if /i "%VERSAO%"=="leve" (
  set "UV_PROJECT_ENVIRONMENT=%CD%\build\venv-win-leve"
  set "DIST=build\dist-leve"
  set "TRABALHO=build\pyinstaller-leve"
) else (
  set "UV_PROJECT_ENVIRONMENT=%CD%\build\venv-win"
  set "DIST=build\dist"
  set "TRABALHO=build\pyinstaller"
)
if not exist "build\ffmpeg\ffmpeg.exe" (
  echo Falta o ffmpeg em build\ffmpeg
  exit /b 1
)
if /i "%VERSAO%"=="leve" (
  rem tudo pelo uv.lock menos o PyTorch, que no Windows vem do PyPI sem CUDA
  "%UV%" sync --frozen --group empacotar --no-install-package torch --no-install-package torchaudio || exit /b 1
  "%UV%" pip install --python "%UV_PROJECT_ENVIRONMENT%" torch==2.11.0 torchaudio==2.11.0 || exit /b 1
) else (
  "%UV%" sync --frozen --group empacotar || exit /b 1
)
if not exist "build\modelos\demucs\htdemucs.yaml" (
  "%UV%" run --no-sync python empacotar\juntar_modelos.py build\modelos || exit /b 1
)
"%UV%" run --no-sync pyinstaller empacotar\extdj.spec --noconfirm --clean --distpath "%DIST%" --workpath "%TRABALHO%" || exit /b 1
echo.
echo Pronto: %DIST%\RD Extended DJ\RD Extended DJ.exe
