#!/usr/bin/env bash
# Publica a versão leve no GitHub: compacta build/dist-leve/RD Extended DJ e cria a release.
# Antes: subir a versão (pyproject.toml e src/extdj/__init__.py), commitar e rodar
# empacotar\construir.bat leve no Windows.
# Uso: ./empacotar/publicar.sh "o que mudou nesta versão"
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."

VERSAO=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' src/extdj/__init__.py)
PASTA="build/dist-leve/RD Extended DJ"
ZIP="build/release/RD-Extended-DJ-Windows.zip"
NOTAS="${1:-}"

[ -f "$PASTA/RD Extended DJ.exe" ] || { echo "Falta $PASTA: rode empacotar\\construir.bat leve"; exit 1; }
[ -n "$NOTAS" ] || { echo "Uso: $0 \"o que mudou\""; exit 1; }
if gh release view "v$VERSAO" >/dev/null 2>&1; then
  echo "A release v$VERSAO já existe. Suba a versão antes."
  exit 1
fi

mkdir -p build/release
python3 - "$PASTA" "$ZIP" <<'PY'
import os, sys, zipfile
from pathlib import Path
pasta, destino = Path(sys.argv[1]), Path(sys.argv[2])
with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for raiz, _, arquivos in os.walk(pasta):
        for a in sorted(arquivos):
            c = Path(raiz) / a
            z.write(c, c.relative_to(pasta.parent).as_posix())
print(destino, round(destino.stat().st_size / 2**20), "MB")
PY

gh release create "v$VERSAO" "$ZIP" --title "RD Extended DJ $VERSAO" --notes "$NOTAS"
