"""Forma de onda em três faixas (graves, médios, agudos), como nos programas de DJ."""

from __future__ import annotations

import base64

import numpy as np

from ..config import SR

QUADROS_POR_SEGUNDO = 100


def calcular(audio: np.ndarray, sr: int = SR, fps: int = QUADROS_POR_SEGUNDO) -> dict:
    """Volume (RMS) de cada faixa a cada 10 ms, de 0 a 255, codificado em base64.

    Graves até 200 Hz, médios até 2,5 kHz, agudos acima. Cada faixa é normalizada
    pelo próprio volume alto (percentil 99); a tela desenha uma sobre a outra, com os
    graves maiores atrás e os agudos menores na frente, como no Rekordbox.
    """
    from scipy.signal import butter, sosfilt

    mono = audio.mean(axis=1).astype(np.float32) if audio.ndim == 2 else audio.astype(np.float32)
    hop = sr // fps
    n = len(mono) // hop
    if n == 0:
        return {"fps": fps, "n": 0, "graves": "", "medios": "", "agudos": ""}

    def rms(x: np.ndarray) -> np.ndarray:
        q = x[: n * hop].astype(np.float32).reshape(n, hop)
        return np.sqrt(np.mean(q * q, axis=1))

    def codificar(x: np.ndarray) -> str:
        y = np.clip(x / max(float(np.percentile(x, 99)), 1e-9), 0, 1)
        return base64.b64encode((y * 255).astype(np.uint8).tobytes()).decode()

    graves = rms(sosfilt(butter(4, 200, "lowpass", fs=sr, output="sos"), mono))
    medios = rms(sosfilt(butter(2, [200, 2500], "bandpass", fs=sr, output="sos"), mono))
    agudos = rms(sosfilt(butter(4, 2500, "highpass", fs=sr, output="sos"), mono))
    return {"fps": fps, "n": int(n), "graves": codificar(graves), "medios": codificar(medios),
            "agudos": codificar(agudos)}
