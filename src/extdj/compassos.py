"""Medidas compasso a compasso: volume, voz e uma impressão digital para comparar compassos."""

from __future__ import annotations

import numpy as np

from .grade import Grade


def limites(grade: Grade, sr: int, n_amostras: int) -> np.ndarray:
    """Início e fim de cada compasso em amostras (float), formato (compassos, 2)."""
    ini = grade.inicios * sr
    fim = np.array([grade.fim_compasso(k) for k in range(len(grade.compassos))]) * sr
    return np.column_stack([ini, np.minimum(fim, n_amostras)])


def completos(grade: Grade, sr: int, n_amostras: int) -> np.ndarray:
    """Compassos que cabem inteiros dentro do arquivo."""
    lim = limites(grade, sr, n_amostras)
    tam = grade.periodo * grade.batidas_por_compasso * sr
    return (lim[:, 0] >= 0) & (lim[:, 1] - lim[:, 0] > 0.97 * tam)


def rms_db(mono: np.ndarray, grade: Grade, sr: int) -> np.ndarray:
    lim = limites(grade, sr, len(mono)).astype(int)
    out = np.full(len(lim), -120.0)
    for k, (a, b) in enumerate(lim):
        a = max(a, 0)
        if b > a:
            out[k] = 10 * np.log10(np.mean(mono[a:b].astype(np.float64) ** 2) + 1e-12)
    return out


def _rms_quadros(x: np.ndarray, n: int = 2048, hop: int = 1024) -> np.ndarray:
    q = 1 + max(0, len(x) - n) // hop
    idx = np.arange(n)[None, :] + hop * np.arange(q)[:, None]
    return np.sqrt(np.mean(x[idx].astype(np.float64) ** 2, axis=1) + 1e-12)


def voz(vocais: np.ndarray, mix: np.ndarray, grade: Grade, sr: int) -> np.ndarray:
    """Fração de cada compasso com voz (0 a 1).

    Conta como voz o quadro em que o stem de voz está acima de -45 dBFS e a no máximo
    14 dB abaixo da música inteira; abaixo disso é vazamento da separação.
    """
    hop = 1024
    v = 20 * np.log10(_rms_quadros(vocais, hop=hop))
    m = 20 * np.log10(_rms_quadros(mix, hop=hop))
    ativo = (v > -45) & (v - m > -14)
    tempos = (np.arange(len(ativo)) * hop + 1024) / sr
    out = np.zeros(len(grade.compassos))
    for k in range(len(grade.compassos)):
        sel = (tempos >= grade.compassos[k]) & (tempos < grade.fim_compasso(k))
        if sel.any():
            out[k] = ativo[sel].mean()
    return out


def impressoes(mono: np.ndarray, grade: Grade, sr: int, passos: int = 16, bandas: int = 40) -> np.ndarray:
    """Vetor por compasso: mel de 40 bandas em 16 fatias de tempo, normalizado.

    Dois compassos parecidos (mesma batida, mesmo timbre, mesma harmonia) dão
    produto interno perto de 1. Serve para achar trechos que repetem sem emenda.
    """
    import librosa
    import soxr

    y = soxr.resample(mono.astype(np.float32), sr, 22050)
    hop = 256
    mel = librosa.feature.melspectrogram(y=y, sr=22050, n_fft=1024, hop_length=hop, n_mels=bandas, fmax=11025)
    mel = np.log(mel + 1e-6)
    mel = (mel - mel.mean(axis=1, keepdims=True)) / (mel.std(axis=1, keepdims=True) + 1e-6)
    seg = hop / 22050
    out = np.zeros((len(grade.compassos), passos * bandas), dtype=np.float32)
    for k in range(len(grade.compassos)):
        a, b = grade.compassos[k], grade.fim_compasso(k)
        bordas = np.linspace(a, b, passos + 1) / seg
        fatias = []
        for i in range(passos):
            q0 = int(np.floor(bordas[i]))
            q1 = max(q0 + 1, int(np.floor(bordas[i + 1])))
            if q0 < 0 or q1 > mel.shape[1]:
                fatias.append(np.full(bandas, -3.0))
            else:
                fatias.append(mel[:, q0:q1].mean(axis=1))
        v = np.concatenate(fatias)
        out[k] = v / (np.linalg.norm(v) + 1e-9)
    return out
