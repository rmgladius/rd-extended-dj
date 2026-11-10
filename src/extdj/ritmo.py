"""Padrão da batida a partir da bateria isolada.

Mede onde caem bumbo, caixa e chimbal nas 16 semicolcheias do compasso e classifica:
4 no chão (house, techno), 3-3-2 (funk, reggaeton), backbeat (pop, hip hop),
meio-tempo (trap) ou quebrado (breakbeat, DnB). É uma regra simples, não um modelo
treinado, e por isso vem com o perfil medido para conferência.
"""

from __future__ import annotations

import numpy as np

from .grade import Grade

BANDAS = {"bumbo": (30, 120), "caixa": (150, 2500), "chimbal": (6000, 16000)}


def _ataques_por_banda(mono: np.ndarray, sr: int, hop: int = 256) -> tuple[dict[str, np.ndarray], float]:
    import librosa

    s = np.abs(librosa.stft(mono.astype(np.float32), n_fft=2048, hop_length=hop)) ** 2
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    out = {}
    for nome, (f0, f1) in BANDAS.items():
        e = np.log10(s[(freqs >= f0) & (freqs < f1)].sum(axis=0) + 1e-10)
        d = np.maximum(np.diff(e, prepend=e[0]), 0)
        out[nome] = d
    return out, hop / sr


def perfil(mono: np.ndarray, grade: Grade, sr: int, validos: np.ndarray) -> dict[str, np.ndarray]:
    ataques, seg = _ataques_por_banda(mono, sr)
    raio = max(1, int(round(0.012 / seg)))
    perfis = {}
    for nome, env in ataques.items():
        linhas = []
        for k in np.flatnonzero(validos):
            a, b = grade.compassos[k], grade.fim_compasso(k)
            passos = a + (b - a) * np.arange(16) / 16
            q = np.round(passos / seg).astype(int)
            if q[0] - raio < 0 or q[-1] + raio >= len(env):
                continue
            linhas.append([env[i - raio:i + raio + 1].max() for i in q])
        p = np.mean(linhas, axis=0) if linhas else np.zeros(16)
        perfis[nome] = p / (p.max() + 1e-9)
    return perfis


def classificar(perfis: dict[str, np.ndarray]) -> tuple[str, float]:
    k, c = perfis["bumbo"], perfis["caixa"]
    tempos = [0, 4, 8, 12]
    fora = [i for i in range(16) if i not in tempos]
    quatro = min(k[i] for i in tempos)
    quatro_rel = quatro / (np.mean(k[fora]) + 1e-6)

    a = np.maximum(k, c)
    tres = [0, 3, 6, 8, 11, 14]
    resto = [i for i in range(16) if i not in tres]
    tresillo = np.mean(a[tres]) / (np.mean(a[resto]) + 1e-6)
    caixa_tres = np.mean(c[[3, 6, 11, 14]]) / (np.mean(c[[1, 2, 5, 9, 10, 13]]) + 1e-6)

    if caixa_tres > 1.8 and tresillo > 1.4:
        return "3-3-2 (funk, dembow)", float(min(1, caixa_tres / 3))
    if quatro >= 0.5 and quatro_rel > 1.8:
        return "4 no chão", float(min(1, quatro_rel / 3))
    if c[8] >= 0.6 and c[4] < 0.45 and c[12] < 0.45:
        return "meio-tempo", float(c[8] - max(c[4], c[12]))
    if c[4] >= 0.5 and c[12] >= 0.5:
        return "backbeat (caixa no 2 e no 4)", float(min(c[4], c[12]))
    if tresillo > 1.5:
        return "3-3-2 (funk, dembow)", float(min(1, tresillo / 3))
    return "quebrado", 0.3


def estimar(bateria_mono: np.ndarray, grade: Grade, sr: int, validos: np.ndarray) -> dict:
    perfis = perfil(bateria_mono, grade, sr, validos)
    nome, conf = classificar(perfis)
    return {
        "padrao": nome,
        "confianca": round(float(np.clip(conf, 0, 1)), 2),
        "perfil": {k: [round(float(x), 2) for x in v] for k, v in perfis.items()},
    }
