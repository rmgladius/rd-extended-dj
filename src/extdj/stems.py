"""Separação em bateria, baixo, voz e resto (Demucs), com cache em disco."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import soundfile as sf

from .config import SR, pasta_cache

NOMES = ("drums", "bass", "other", "vocals")
MODELO = "htdemucs"

_separador = None


def chave_arquivo(caminho: Path) -> str:
    """Identifica a música pelo conteúdo do começo, do fim e pelo tamanho (renomear não invalida)."""
    tam = caminho.stat().st_size
    h = hashlib.sha1(str(tam).encode())
    with open(caminho, "rb") as f:
        h.update(f.read(1 << 20))
        if tam > 2 << 20:
            f.seek(-(1 << 20), 2)
            h.update(f.read(1 << 20))
    return h.hexdigest()[:16]


def _separar(audio: np.ndarray, dispositivo: str) -> dict[str, np.ndarray]:
    global _separador
    import torch
    from demucs.api import Separator

    if _separador is None:
        _separador = Separator(model=MODELO, device=dispositivo, progress=False)
    wav = torch.from_numpy(np.ascontiguousarray(audio.T))
    _, saida = _separador.separate_tensor(wav, SR)
    return {nome: saida[nome].cpu().numpy().T.astype(np.float32) for nome in NOMES}


def obter(caminho: Path, audio: np.ndarray, dispositivo: str) -> dict[str, np.ndarray]:
    """Stems da música, lendo do cache quando já foram separados."""
    pasta = pasta_cache() / "stems" / f"{chave_arquivo(caminho)}-{MODELO}"
    arquivos = {nome: pasta / f"{nome}.flac" for nome in NOMES}
    if all(a.exists() for a in arquivos.values()):
        stems = {nome: sf.read(a, dtype="float32", always_2d=True)[0] for nome, a in arquivos.items()}
        n = len(audio)
        return {k: _ajustar_tamanho(v, n) for k, v in stems.items()}
    # o corte em ±1 vale para a memória também, para a 1ª e a 2ª execução darem o mesmo resultado
    stems = {k: np.clip(v, -1, 1) for k, v in _separar(audio, dispositivo).items()}
    pasta.mkdir(parents=True, exist_ok=True)
    for nome, dados in stems.items():
        sf.write(arquivos[nome], dados, SR, subtype="PCM_24")
    return stems


def _ajustar_tamanho(x: np.ndarray, n: int) -> np.ndarray:
    if len(x) >= n:
        return x[:n]
    return np.vstack([x, np.zeros((n - len(x), x.shape[1]), dtype=x.dtype)])
