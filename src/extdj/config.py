"""Configurações compartilhadas: taxa de amostragem, pasta de cache e dispositivo."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Tudo é processado a 44,1 kHz estéreo, a taxa do Demucs e do CD.
SR = 44100

# Sobe quando o formato da análise muda, para não reaproveitar cache velho.
VERSAO_ANALISE = 2


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
