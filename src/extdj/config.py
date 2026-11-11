"""Configurações compartilhadas: taxa de amostragem, pastas e dispositivo."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Tudo é processado a 44,1 kHz estéreo, a taxa do Demucs e do CD.
SR = 44100

# Sobe quando o formato da análise muda, para não reaproveitar cache velho.
VERSAO_ANALISE = 3

# Programa empacotado (PyInstaller): modelos e ffmpeg vêm junto, dentro de _internal.
CONGELADO = bool(getattr(sys, "frozen", False))


def pasta_programa() -> Path:
    """Onde ficam os arquivos que acompanham o programa (modelos, ffmpeg, interface)."""
    if CONGELADO:
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def pasta_cache() -> Path:
    """Pasta onde ficam stems, análises e modelos baixados."""
    env = os.environ.get("EXTDJ_CACHE")
    if env:
        pasta = Path(env)
    elif sys.platform == "win32":
        pasta = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "extdj" / "cache"
    elif sys.platform == "darwin":
        pasta = Path.home() / "Library" / "Caches" / "extdj"
    else:
        pasta = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "extdj"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def modelo_embutido(*partes: str) -> Path | None:
    """Arquivo de modelo que veio com o programa, se existir.

    No programa empacotado os modelos ficam em `_internal/modelos`, para funcionar
    sem internet. Fora dele, `EXTDJ_MODELOS` aponta para uma pasta com a mesma
    estrutura; sem ela, cada biblioteca baixa o seu na primeira vez.
    """
    raiz = os.environ.get("EXTDJ_MODELOS")
    base = Path(raiz) if raiz else (pasta_programa() / "modelos" if CONGELADO else None)
    if base is None:
        return None
    caminho = base.joinpath(*partes)
    return caminho if caminho.exists() else None


def dispositivo() -> str:
    """cuda (NVIDIA), mps (Mac com chip M) ou cpu."""
    forcado = os.environ.get("EXTDJ_DISPOSITIVO")
    if forcado:
        return forcado
    import torch

    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


def nome_dispositivo(disp: str) -> str:
    """Nome legível do processador usado, para mostrar na tela."""
    if disp == "cuda":
        try:
            import torch

            return f"placa de vídeo ({torch.cuda.get_device_name(0)})"
        except Exception:
            return "placa de vídeo"
    if disp == "mps":
        return "GPU do Mac"
    return "processador"
