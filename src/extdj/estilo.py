"""Estilo musical pelo Discogs-EffNet (400 estilos do Discogs), rodando em ONNX.

Modelo do MTG (Universitat Pompeu Fabra), licença CC BY-NC-SA 4.0: uso sem fins
comerciais, com crédito. Baixado na primeira vez para a pasta de cache.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

import numpy as np

from .config import modelo_embutido, pasta_cache

BASE = "https://essentia.upf.edu/models/feature-extractors/discogs-effnet/"
ARQ_MODELO = "discogs-effnet-bsdynamic-1.onnx"
ARQ_META = "discogs-effnet-bsdynamic-1.json"

_sessao = None
_classes: list[str] | None = None


def _baixar(nome: str) -> Path:
    junto = modelo_embutido(nome)
    if junto:
        return junto
    destino = pasta_cache() / "modelos" / nome
    if not destino.exists():
        destino.parent.mkdir(parents=True, exist_ok=True)
        tmp = destino.with_suffix(destino.suffix + ".parcial")
        print(f"Baixando {nome} (só na primeira vez)...", file=sys.stderr, flush=True)
        urllib.request.urlretrieve(BASE + nome, tmp)
        tmp.replace(destino)
    return destino


def _carregar():
    global _sessao, _classes
    if _sessao is None:
        import onnxruntime as ort

        _classes = json.loads(_baixar(ARQ_META).read_text(encoding="utf-8"))["classes"]
        _sessao = ort.InferenceSession(str(_baixar(ARQ_MODELO)), providers=["CPUExecutionProvider"])
    return _sessao, _classes


def espectrograma(mono16k: np.ndarray) -> np.ndarray:
    """Mel de 96 bandas igual ao TensorflowInputMusiCNN do Essentia: (quadros, 96)."""
    import librosa

    s = librosa.feature.melspectrogram(
        y=mono16k.astype(np.float32), sr=16000, n_fft=512, hop_length=256, n_mels=96,
        power=2.0, htk=False, norm="slaney", center=True, pad_mode="constant",
    )
    return np.log10(1 + 10000 * s).T.astype(np.float32)


def nome_amigavel(classe: str) -> str:
    """'Electronic---Tech House' vira 'Tech House (Electronic)'."""
    if "---" in classe:
        pai, filho = classe.split("---", 1)
        return f"{filho} ({pai})"
    return classe


def estimar(mono: np.ndarray, sr: int, quantos: int = 3) -> tuple[list[dict], np.ndarray | None]:
    """Os estilos mais prováveis e a impressão digital de 1280 valores da música.

    A impressão digital vai servir para os estilos aprendidos (funk BR e outros que o
    Discogs não tem): a música nova é comparada com exemplos marcados pelo usuário.
    """
    import soxr

    sessao, classes = _carregar()
    y = soxr.resample(mono.astype(np.float32), sr, 16000)
    mel = espectrograma(y)
    if len(mel) < 128:
        mel = np.vstack([mel, np.zeros((128 - len(mel), 96), np.float32)])
    blocos = np.stack([mel[i:i + 128] for i in range(0, len(mel) - 127, 62)])
    saidas = sessao.run(None, {sessao.get_inputs()[0].name: blocos})
    probs = next(s for s in saidas if s.shape[-1] == len(classes))
    emb = next((s for s in saidas if s.shape[-1] == 1280), None)
    media = probs.mean(axis=0)
    ordem = np.argsort(media)[::-1][:quantos]
    estilos = [{"estilo": nome_amigavel(classes[i]), "prob": float(media[i])} for i in ordem]
    return estilos, (None if emb is None else emb.mean(axis=0))
