"""Tonalidade (tom) em notação tradicional e Camelot.

Croma da parte harmônica (baixo + resto + um pouco de voz, sem a bateria),
comparado com três perfis de tonalidade. Os valores dos perfis são dados publicados:
Krumhansl e Kessler (1982), Temperley (MIREX 2005) e EDMA, de Faraldo et al. (2016),
feito a partir de música eletrônica de pista.
"""

from __future__ import annotations

import numpy as np

PERFIS = {
    "krumhansl": (
        [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88],
        [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17],
    ),
    "temperley": (
        [0.748, 0.060, 0.488, 0.082, 0.670, 0.460, 0.096, 0.715, 0.104, 0.366, 0.057, 0.400],
        [0.712, 0.084, 0.474, 0.618, 0.049, 0.460, 0.105, 0.747, 0.404, 0.067, 0.133, 0.330],
    ),
    "edma": (
        [1.00, 0.29, 0.50, 0.40, 0.60, 0.56, 0.32, 0.80, 0.31, 0.45, 0.42, 0.39],
        [1.00, 0.31, 0.44, 0.58, 0.33, 0.49, 0.29, 0.78, 0.43, 0.29, 0.53, 0.32],
    ),
}

NOTAS_MAIOR = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
NOTAS_MENOR = ["Cm", "C#m", "Dm", "Ebm", "Em", "Fm", "F#m", "Gm", "G#m", "Am", "Bbm", "Bm"]
NOMES_PT = ["Dó", "Dó#", "Ré", "Mi♭", "Mi", "Fá", "Fá#", "Sol", "Lá♭", "Lá", "Si♭", "Si"]
NOMES_PT_MENOR = ["Dó", "Dó#", "Ré", "Mi♭", "Mi", "Fá", "Fá#", "Sol", "Sol#", "Lá", "Si♭", "Si"]


def camelot(tonica: int, menor: bool) -> str:
    """Posição na roda de Camelot: Dó maior = 8B, Lá menor = 8A."""
    base = (tonica + 3) % 12 if menor else tonica
    n = (7 * base + 8) % 12
    return f"{12 if n == 0 else n}{'A' if menor else 'B'}"


def nome_tom(tonica: int, menor: bool) -> tuple[str, str]:
    """(notação curta, nome em português), por exemplo ("Am", "Lá menor")."""
    if menor:
        return NOTAS_MENOR[tonica], f"{NOMES_PT_MENOR[tonica]} menor"
    return NOTAS_MAIOR[tonica], f"{NOMES_PT[tonica]} maior"


def croma(harmonico_mono: np.ndarray, sr: int) -> np.ndarray:
    """Perfil de croma médio (12 valores) da música inteira."""
    import librosa

    y = harmonico_mono.astype(np.float32)
    if sr != 22050:
        import soxr

        y = soxr.resample(y, sr, 22050)
    c = librosa.feature.chroma_cqt(y=y, sr=22050, hop_length=4096, bins_per_octave=36, norm=None)
    energia = c.sum(axis=0)
    ativo = energia > np.percentile(energia, 20)
    perfil = np.sqrt(np.maximum(c[:, ativo], 0)).sum(axis=1)
    return perfil / (perfil.sum() + 1e-12)


def _correlacoes(perfil: np.ndarray) -> np.ndarray:
    """Matriz (24,) somando a correlação dos três perfis: 0-11 maior, 12-23 menor."""
    total = np.zeros(24)
    for maior, menor in PERFIS.values():
        for modo, ref in enumerate((maior, menor)):
            ref = np.asarray(ref, dtype=float)
            for t in range(12):
                total[modo * 12 + t] += np.corrcoef(perfil, np.roll(ref, t))[0, 1]
    return total / len(PERFIS)


def estimar(harmonico_mono: np.ndarray, sr: int) -> dict:
    perfil = croma(harmonico_mono, sr)
    notas = _correlacoes(perfil)
    ordem = np.argsort(notas)[::-1]
    melhor, segundo = int(ordem[0]), int(ordem[1])
    tonica, menor = melhor % 12, melhor >= 12
    curto, pt = nome_tom(tonica, menor)
    t2, m2 = segundo % 12, segundo >= 12
    curto2, _ = nome_tom(t2, m2)
    return {
        "tom": curto,
        "tom_pt": pt,
        "camelot": camelot(tonica, menor),
        "confianca": float(np.clip((notas[melhor] - notas[segundo]) * 5 + notas[melhor] * 0.5, 0, 1)),
        "alternativa": f"{curto2} ({camelot(t2, m2)})",
    }
