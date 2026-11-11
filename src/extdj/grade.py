"""Grade de batidas: BPM, início de cada compasso e oscilação do andamento.

O beat_this entrega as batidas com resolução de 20 ms. Aqui elas viram uma grade
contínua: uma reta (andamento fixo) mais uma correção lenta, que só é usada quando
a música tem baterista ao vivo e o andamento oscila de verdade.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

# Andamento variável: o BPM local oscila mais que isso, ou as batidas fogem mais que
# isso da grade fixa. A detecção tem resolução de 20 ms, então limites menores dariam
# alarme falso em música eletrônica de andamento fixo.
LIMITE_FAIXA_BPM = 1.2
LIMITE_DERIVA_MS = 25.0

# Entre dois andamentos possíveis (x e 2x), o rápido só vale até aqui.
MAIOR_BPM_PREFERIDO = 155.0

_modelo_batidas = None


@dataclass
class Grade:
    bpm: float
    periodo: float               # segundos por batida (média)
    batidas_por_compasso: int
    compassos: list[float]       # início de cada compasso, em segundos (o primeiro pode ser negativo)
    variavel: bool
    deriva_ms: float             # p95 da distância entre as batidas reais e a grade fixa
    bpm_min: float
    bpm_max: float
    confianca: float             # 0 a 1

    def para_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def de_dict(d: dict) -> "Grade":
        return Grade(**d)

    @property
    def inicios(self) -> np.ndarray:
        return np.asarray(self.compassos, dtype=float)

    def fim_compasso(self, k: int) -> float:
        """Fim do compasso k (início do seguinte, ou extrapolado no último)."""
        c = self.compassos
        if k + 1 < len(c):
            return c[k + 1]
        return c[k] + self.periodo * self.batidas_por_compasso

    def compasso_em(self, t: float) -> int:
        """Índice do compasso que contém o instante t."""
        return int(np.clip(np.searchsorted(self.inicios, t, side="right") - 1, 0, len(self.compassos) - 1))


def detectar_batidas(mono: np.ndarray, sr: int, dispositivo: str) -> tuple[np.ndarray, np.ndarray]:
    """Batidas e primeiros tempos de compasso (em segundos) pelo beat_this."""
    global _modelo_batidas
    from beat_this.inference import Audio2Beats

    if _modelo_batidas is None:
        from .config import modelo_embutido

        local = modelo_embutido("beat_this-final0.ckpt")
        _modelo_batidas = Audio2Beats(checkpoint_path=str(local) if local else "final0",
                                      device=dispositivo, dbn=False)
    batidas, primeiros = _modelo_batidas(mono.astype(np.float64), sr)
    return np.asarray(batidas, dtype=float), np.asarray(primeiros, dtype=float)


def _media_movel(x: np.ndarray, peso: np.ndarray, raio: int) -> np.ndarray:
    n = len(x)
    out = np.empty(n)
    for i in range(n):
        a, b = max(0, i - raio), min(n, i + raio + 1)
        w = peso[a:b]
        out[i] = (x[a:b] * w).sum() / w.sum() if w.sum() > 0 else 0.0
    return out


def _mediana_movel(x: np.ndarray, raio: int) -> np.ndarray:
    n = len(x)
    return np.array([np.median(x[max(0, i - raio):min(n, i + raio + 1)]) for i in range(n)])


def fase_por_ataques(tempos: np.ndarray, tempos_env: np.ndarray, env: np.ndarray, duracao: float,
                     alcance: float) -> tuple[float, float]:
    """Deslocamento (s) que encosta as batidas nos ataques, e quão nítido é esse encaixe.

    A nitidez é o quanto o melhor deslocamento se destaca da média; perto de zero quer
    dizer trecho sem bateria, onde a medida não vale.
    """
    t = np.asarray(tempos, dtype=float)
    t = t[(t > alcance + 0.01) & (t < duracao - alcance - 0.01)]
    if len(t) < 4:
        return 0.0, 0.0
    deslocs = np.arange(-alcance, alcance + 1e-9, 0.0005)
    notas = np.array([np.interp(t + d, tempos_env, env).sum() for d in deslocs])
    i = int(np.argmax(notas))
    forca = float((notas[i] - np.median(notas)) / (np.median(notas) + 1e-9))
    return float(deslocs[i]), max(0.0, forca)


def periodo_da_grade(intervalos: np.ndarray, teto_bpm: float = MAIOR_BPM_PREFERIDO) -> float:
    """Período da grade quando o detector alterna entre andamento cheio e meio-tempo.

    Em trap e pop é comum o detector marcar 68 BPM numa parte e 136 em outra. A grade
    fica no andamento rápido (o que o Rekordbox mostraria), a não ser que ele passe de
    `teto_bpm`: aí é hip hop a 90 lido como 180, e fica o lento.
    """
    d = np.asarray(intervalos, dtype=float)
    p = float(np.median(d))
    minimo = max(8, int(0.05 * len(d)))
    meio = d[(d > 0.4 * p) & (d < 0.6 * p)]
    dobro = d[(d > 1.8 * p) & (d < 2.2 * p)]
    if len(meio) >= minimo:
        rapido, lento = float(np.median(meio)), p
    elif len(dobro) >= minimo:
        rapido, lento = p, float(np.median(dobro))
    else:
        return p
    return rapido if 60.0 / rapido <= teto_bpm else lento


def _contar_seguido(b: np.ndarray, p: float) -> tuple[np.ndarray, np.ndarray]:
    """Conta arredondando o intervalo até a última batida aceita.

    Batida a menos de 3/4 de tempo da anterior (meio-tempo detectado em andamento
    cheio, ou ataque falso) fica de fora.
    """
    idx = np.zeros(len(b), dtype=int)
    ok = np.zeros(len(b), dtype=bool)
    ok[0] = True
    ult = 0
    for i in range(1, len(b)):
        r = (b[i] - b[ult]) / p
        if r < 0.75:
            continue
        idx[i] = idx[ult] + int(round(r))
        ok[i] = True
        ult = i
    return idx, ok


def _contar_sem_contratempo_a_partir(b: np.ndarray, p: float, inicio: int) -> tuple[np.ndarray, np.ndarray]:
    idx = np.zeros(len(b), dtype=int)
    ok = np.zeros(len(b), dtype=bool)
    ok[inicio] = True
    ancoras = [inicio]
    for i in range(inicio + 1, len(b)):
        ult = ancoras[-1]
        pl = p
        if len(ancoras) > 8:
            # período local pelas últimas 16 batidas aceitas: acompanha andamento ao vivo
            ant = ancoras[max(0, len(ancoras) - 17)]
            pl = (b[ult] - b[ant]) / (idx[ult] - idx[ant])
        r = (b[i] - b[ult]) / pl
        k = int(round(r))
        if k < 1 or abs(r - k) > 0.25:
            continue
        idx[i] = idx[ult] + k
        ok[i] = True
        ancoras.append(i)
    return idx, ok


def _contar_sem_contratempo(b: np.ndarray, p: float) -> tuple[np.ndarray, np.ndarray]:
    """Conta deixando de fora a batida a mais de um quarto de tempo da contagem.

    O detector às vezes passa a marcar o contratempo por um trecho (no funk o
    tamborzão bate forte no "e" de cada tempo). Na contagem seguida, a virada para o
    contratempo e a volta arredondam 1,5 tempo para 2, e cada trecho assim soma uma
    batida que não existe. Aqui esse trecho fica de fora; se a maioria cair no
    contratempo do começo, vale a fase da maioria.
    """
    idx, ok = _contar_sem_contratempo_a_partir(b, p, 0)
    fora = np.flatnonzero(~ok)
    if len(fora) and ok.sum() < len(b) / 2:
        idx2, ok2 = _contar_sem_contratempo_a_partir(b, p, int(fora[0]))
        if ok2.sum() > ok.sum():
            idx, ok = idx2, ok2
    return idx, ok


@dataclass
class _Reta:
    b: np.ndarray          # batidas aceitas
    idx: np.ndarray        # número de cada uma na grade
    t0: float
    periodo: float
    lento: np.ndarray      # oscilação lenta do andamento em volta da reta
    validas: np.ndarray    # batidas que não são erro de detecção
    deriva_ms: float


def _reta(b: np.ndarray, idx: np.ndarray, ok: np.ndarray) -> _Reta:
    b, idx = b[ok], idx[ok]

    # 1) reta inicial e separação entre oscilação lenta (andamento) e erro de detecção
    t0, periodo = np.polyfit(idx, b, 1)[::-1]
    res = b - (t0 + periodo * idx)
    lento = _mediana_movel(res, 4)
    validas = np.abs(res - lento) < 0.035
    if validas.sum() < 16:
        validas[:] = True

    # 2) reta final só com as batidas confiáveis
    t0, periodo = np.polyfit(idx[validas], b[validas], 1)[::-1]
    res = b - (t0 + periodo * idx)
    lento = _media_movel(res, validas.astype(float), 8)
    deriva_ms = float(np.percentile(np.abs(lento[validas]), 95) * 1000)
    return _Reta(b, idx, float(t0), float(periodo), lento, validas, deriva_ms)


def numerar_batidas(batidas: np.ndarray, p: float) -> _Reta:
    """Numera as batidas na grade e passa uma reta (andamento) por elas.

    Há duas contagens: a seguida, que aguenta trechos fora da grade (uma quebra com
    andamento livre no meio de um bootleg), e a que ignora o contratempo. Fica a que
    explica as batidas com o andamento mais estável: uma batida contada a mais vira um
    degrau na oscilação e aparece na deriva.
    """
    b = np.asarray(batidas, dtype=float)
    melhor = None
    for contar in (_contar_seguido, _contar_sem_contratempo):
        idx, ok = contar(b, p)
        if ok.sum() < 16:
            continue
        r = _reta(b, idx, ok)
        if melhor is None or r.deriva_ms < melhor.deriva_ms - 0.5:
            melhor = r
    if melhor is None:
        raise RuntimeError("Não achei batidas suficientes para montar a grade.")
    return melhor


def ajustar_grade(
    batidas: np.ndarray,
    primeiros: np.ndarray,
    duracao: float,
    ataques: tuple[np.ndarray, float] | None = None,
) -> Grade:
    """Monta a grade a partir das batidas detectadas.

    `ataques` é (envelope de ataques, segundos por quadro), de preferência da bateria
    isolada; serve para encostar a grade no ataque do bumbo com precisão de ~3 ms.
    """
    b = np.asarray(batidas, dtype=float)
    if len(b) < 16:
        raise RuntimeError("Não achei batidas suficientes para montar a grade.")

    reta = numerar_batidas(b, periodo_da_grade(np.diff(b)))
    b, idx, t0, periodo = reta.b, reta.idx, reta.t0, reta.periodo
    lento, validas, deriva_ms = reta.lento, reta.validas, reta.deriva_ms

    # andamento local em janelas de 16 batidas
    posicoes = t0 + periodo * idx + lento
    bpms_locais = []
    for i in range(0, len(idx) - 16, 4):
        dt = posicoes[i + 16] - posicoes[i]
        di = idx[i + 16] - idx[i]
        if dt > 0:
            bpms_locais.append(60.0 * di / dt)
    if bpms_locais:
        bpm_min, bpm_max = (float(x) for x in np.percentile(bpms_locais, [5, 95]))
    else:
        bpm_min = bpm_max = 60.0 / periodo
    variavel = (bpm_max - bpm_min) > LIMITE_FAIXA_BPM or deriva_ms > LIMITE_DERIVA_MS

    if variavel:
        def tempo(i: np.ndarray) -> np.ndarray:
            corr = np.interp(i, idx[validas], lento[validas])
            return t0 + periodo * i + corr
    else:
        def tempo(i: np.ndarray) -> np.ndarray:
            return t0 + periodo * np.asarray(i, dtype=float)

    # 3) ajuste fino pelo ataque da bateria. Primeiro mede a fase em blocos de 32
    #    batidas: se ela escorrega em linha reta ao longo da música, o BPM estava um
    #    pouco errado (0,01 BPM já dá 15 ms de erro no fim de uma faixa de 4 minutos).
    if ataques is not None:
        env, seg_por_quadro = ataques
        tempos_env = np.arange(len(env)) * seg_por_quadro
        todas = np.arange(idx.min(), idx.max() + 1)

        if not variavel:
            centros, fases, pesos = [], [], []
            for i0 in range(int(todas[0]), int(todas[-1]) - 31, 32):
                bloco = np.arange(i0, i0 + 32)
                d, forca = fase_por_ataques(tempo(bloco), tempos_env, env, duracao, 0.03)
                if forca > 0:
                    centros.append(i0 + 16)
                    fases.append(d)
                    pesos.append(forca)
            if len(centros) >= 4:
                w = np.sqrt(np.asarray(pesos))
                inclinacao, desloc = np.polyfit(np.asarray(centros, float), np.asarray(fases), 1, w=w)
                t0 += desloc
                periodo += inclinacao

        d, _ = fase_por_ataques(tempo(todas), tempos_env, env, duracao, 0.025)
        t0 += d

    # 4) qual batida abre o compasso: voto dos primeiros tempos detectados
    pb = 4
    if len(primeiros) >= 4:
        k_primeiros = np.round((np.asarray(primeiros) - t0) / periodo).astype(int)
        difs = np.diff(k_primeiros)
        difs = difs[difs > 0]
        if len(difs):
            pb = int(np.median(difs))
            if pb not in (2, 3, 4, 6, 7):
                pb = 4
        fase = int(np.bincount(np.mod(k_primeiros, pb), minlength=pb).argmax())
    else:
        fase = 0

    # 5) início de cada compasso cobrindo a música toda (um a mais antes do zero)
    i_ini = int(np.floor((-(pb * periodo) - t0) / periodo))
    i_ini += (fase - i_ini) % pb
    i_fim = int(np.ceil((duracao - t0) / periodo))
    ks = np.arange(i_ini, i_fim + 1, pb)
    inicios = tempo(ks)
    inicios = inicios[(inicios >= -pb * periodo) & (inicios < duracao)]

    cobertura = (b[-1] - b[0]) / max(duracao, 1e-6)
    confianca = float(np.clip(validas.mean() * min(1.0, cobertura / 0.6), 0, 1))
    if variavel:
        confianca *= 0.7

    return Grade(
        bpm=float(60.0 / periodo),
        periodo=float(periodo),
        batidas_por_compasso=pb,
        compassos=[float(x) for x in inicios],
        variavel=bool(variavel),
        deriva_ms=deriva_ms,
        bpm_min=bpm_min,
        bpm_max=bpm_max,
        confianca=confianca,
    )


def envelope_ataques(mono: np.ndarray, sr: int, hop: int = 128) -> tuple[np.ndarray, float]:
    """Força de ataque quadro a quadro (~3 ms por quadro a 44,1 kHz)."""
    import librosa

    env = librosa.onset.onset_strength(y=mono.astype(np.float32), sr=sr, hop_length=hop, n_mels=64)
    return env.astype(np.float32), hop / sr
