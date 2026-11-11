"""Escolhe o loop e monta o extended: intro em loop + música original + outro em loop.

Cada pedaço é copiado em compassos inteiros, com as posições acumuladas em ponto
flutuante. A 128 BPM um compasso tem 82.687,5 amostras: arredondar compasso a
compasso faria a grade escorregar ao longo do intro; aqui só a posição final de cada
emenda é arredondada, então o erro nunca passa de meia amostra.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from . import compassos as cp
from .analise import Faixa
from .config import SR
from .grade import envelope_ataques, fase_por_ataques

MODOS = ("auto", "completo", "instrumental", "batida", "batida_baixo", "camadas")
NOMES_MODO = {
    "completo": "música completa",
    "instrumental": "instrumental (sem voz)",
    "batida": "só a bateria",
    "batida_baixo": "bateria e baixo",
    "camadas": "em camadas",
}

PRE = int(0.004 * SR)   # cada emenda acontece 4 ms antes do tempo forte
XF = int(0.003 * SR)    # e dura 3 ms, terminando antes do ataque


@dataclass
class Escolha:
    lado: str
    modo: str
    inicio: int          # compasso onde o loop começa (índice da grade)
    tamanho: int         # compassos no loop
    compassos: int       # compassos adicionados
    nota: float
    camadas: list[str]
    ajuste_ms: float = 0.0   # quanto o loop foi deslocado para o ataque cair na grade

    def para_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- fontes de áudio

class Fontes:
    """Sinais que podem virar loop, calculados só quando usados."""

    def __init__(self, faixa: Faixa):
        self.f = faixa
        self._cache: dict[str, np.ndarray] = {}
        self._impressoes: dict[str, np.ndarray] = {}
        self._ataques: dict[tuple[int, int], tuple[np.ndarray, np.ndarray]] = {}

    def __getitem__(self, nome: str) -> np.ndarray:
        if nome not in self._cache:
            st = self.f.stems
            if nome == "completo":
                x = self.f.audio
            elif nome == "instrumental":
                x = st["drums"] + st["bass"] + st["other"]
            elif nome == "batida":
                x = st["drums"]
            elif nome == "batida_baixo":
                x = st["drums"] + st["bass"]
            else:
                raise KeyError(nome)
            self._cache[nome] = x
        return self._cache[nome]

    def ataques(self, t0: float, t1: float) -> tuple[np.ndarray, np.ndarray]:
        """Envelope de ataques da bateria entre t0 e t1 (s), ~1,5 ms por quadro.

        Só o trecho pedido: a música inteira nessa resolução leva segundos.
        """
        a = max(0, int((t0 - 0.5) * SR))
        b = min(len(self.f.audio), int((t1 + 0.5) * SR))
        if (a, b) not in self._ataques:
            env, seg = envelope_ataques(self.f.stems["drums"][a:b].mean(axis=1), SR, hop=64)
            self._ataques[(a, b)] = (a / SR + np.arange(len(env)) * seg, env)
        return self._ataques[(a, b)]

    def impressoes(self, nome: str) -> np.ndarray:
        """Impressão de cada compasso da fonte, guardada em disco (leva 1 a 2 s para calcular)."""
        if nome not in self._impressoes:
            arq = self._arquivo_impressoes(nome)
            imp = None
            if arq is not None and arq.exists():
                try:
                    imp = np.load(arq)
                except (OSError, ValueError):
                    imp = None
                if imp is not None and len(imp) != len(self.f.grade.compassos):
                    imp = None
            if imp is None:
                imp = cp.impressoes(self[nome].mean(axis=1), self.f.grade, SR)
                if arq is not None:
                    arq.parent.mkdir(parents=True, exist_ok=True)
                    np.save(arq, imp)
            self._impressoes[nome] = imp
        return self._impressoes[nome]

    def _arquivo_impressoes(self, nome: str):
        import hashlib

        from .config import pasta_cache
        from .stems import chave_arquivo

        try:
            chave = chave_arquivo(self.f.caminho)
        except OSError:
            return None
        grade = hashlib.sha1(np.asarray(self.f.grade.compassos, dtype=np.float64).tobytes()).hexdigest()[:10]
        return pasta_cache() / "compassos" / f"{chave}-{grade}-{nome}.npy"


# ---------------------------------------------------------------- escolha do loop

def _candidatos(faixa: Faixa, imp: np.ndarray, tamanho: int, lado: str, com_voz: bool) -> list[tuple[float, int]]:
    """(nota, compasso inicial) de cada janela possível, da melhor para a pior."""
    n = len(faixa.grade.compassos)
    validos = faixa.validos
    cheio = validos & (faixa.rms_bateria > -60)
    ref_bat = np.median(faixa.rms_bateria[cheio]) if cheio.any() else -20.0
    ini, fim = faixa.entrada, faixa.saida
    saida = []
    for b in range(ini, fim - tamanho + 1):
        janela = range(b, b + tamanho)
        if not all(validos[k] for k in janela):
            continue
        dist = (b - ini) if lado == "intro" else (fim - (b + tamanho))
        if faixa.grade.variavel and dist > 16:
            continue  # com baterista ao vivo, o loop precisa ser do andamento vizinho

        bat = faixa.rms_bateria[b:b + tamanho].min() - ref_bat
        if bat < -18:
            continue  # sem batida não dá para mixar

        # o que vem logo depois da janela parece com o começo dela? (emenda natural)
        seguinte = [imp[b + tamanho + i] @ imp[b + i] for i in range(tamanho)
                    if b + tamanho + i < n and validos[b + tamanho + i]]
        if not seguinte:
            anterior = [imp[b - tamanho + i] @ imp[b + i] for i in range(tamanho)
                        if b - tamanho + i >= 0 and validos[b - tamanho + i]]
            seguinte = anterior
        if not seguinte:
            continue
        emenda = 0.5 * float(np.mean(seguinte)) + 0.5 * float(seguinte[0])
        if tamanho > 1:
            interno = float(np.mean([imp[k] @ imp[k + 1] for k in range(b, b + tamanho - 1)]))
        else:
            interno = emenda

        frase = 1.0 if (b - ini) % 4 == 0 else (0.5 if (b - ini) % 2 == 0 else 0.0)
        perto = float(np.exp(-dist / 48))
        s_bat = float(np.clip((bat + 12) / 12, 0, 1))
        nota = 0.35 * emenda + 0.25 * interno + 0.15 * s_bat + 0.15 * frase + 0.10 * perto
        if com_voz:
            nota *= 1 - min(1.0, 2 * float(faixa.voz[b:b + tamanho].max()))
        saida.append((nota, b))
    saida.sort(reverse=True)
    return saida


def _camadas(n: int, ultima: str) -> list[str]:
    """Plano de camadas do intro, compasso a compasso.

    Metade só bateria, um quarto bateria e baixo, o último quarto com a camada que
    leva para a música. Em 32 compassos: 16 + 8 + 8, virando sempre em frase de 8.
    """
    if n >= 16:
        q = n // 4
        return ["batida"] * (2 * q) + ["batida_baixo"] * q + [ultima] * (n - 3 * q)
    if n >= 8:
        h = n // 2
        return ["batida"] * h + ["batida_baixo"] * (n - h)
    return ["batida"] * n


def escolher(faixa: Faixa, fontes: Fontes, lado: str, compassos: int, tamanho: int,
             modo: str = "auto", inicio: int | None = None) -> Escolha:
    if compassos % tamanho:
        raise ValueError(f"O {lado} de {compassos} compassos não fecha com loops de {tamanho}.")

    def melhor(fonte: str, com_voz: bool) -> tuple[float, int] | None:
        if inicio is not None:
            return (0.0, inicio)
        c = _candidatos(faixa, fontes.impressoes(fonte), tamanho, lado, com_voz)
        return c[0] if c else None

    if modo == "auto":
        cand = melhor("completo", True)
        b = cand[1] if cand else None
        limpo = (
            cand is not None and cand[0] >= 0.62
            and faixa.voz[b:b + tamanho].max() < 0.15
        )
        modo = "completo" if limpo else "camadas"

    if modo == "camadas":
        cand = melhor("batida", False)
        if cand is None:
            raise RuntimeError(f"Não achei um trecho com batida firme para o {lado}.")
        nota, b = cand
        sem_voz = faixa.voz[b:b + tamanho].max() < 0.15
        ultima = "completo" if sem_voz else "instrumental"
        plano = _camadas(compassos, ultima)
        if lado == "outro":
            plano = plano[::-1]
    else:
        cand = melhor(modo, modo == "completo")
        if cand is None:
            raise RuntimeError(f"Não achei um trecho bom para o {lado} no modo {NOMES_MODO[modo]}.")
        nota, b = cand
        plano = [modo] * compassos
    ajuste = ajuste_local(faixa, fontes, int(b), tamanho)
    return Escolha(lado=lado, modo=modo, inicio=int(b), tamanho=tamanho, compassos=compassos,
                   nota=round(float(nota), 3), camadas=plano, ajuste_ms=round(ajuste * 1000, 2))


# ---------------------------------------------------------------- montagem

def _trecho(x: np.ndarray, ini: int, n: int) -> np.ndarray:
    """n amostras a partir de ini, com silêncio onde passar das bordas."""
    out = np.zeros((n, x.shape[1]), dtype=np.float32)
    a, b = max(ini, 0), min(ini + n, len(x))
    if b > a:
        out[a - ini:b - ini] = x[a:b]
    return out


def _colar(pedacos: list[tuple[str, float, float]], fontes: Fontes) -> tuple[np.ndarray, list[int]]:
    """Cola os pedaços (fonte, início, fim em amostras) e devolve onde cada um começou."""
    total = sum(b - a for _, a, b in pedacos)
    out = np.zeros((int(np.ceil(total)) + PRE + XF + 2, 2), dtype=np.float32)
    sobe = np.linspace(0, 1, XF, dtype=np.float32)[:, None]
    desce = sobe[::-1]
    pos = 0.0
    marcas = []
    for i, (nome, a, b) in enumerate(pedacos):
        o0 = int(round(pos))
        pos += b - a
        o1 = int(round(pos))
        ultimo = i == len(pedacos) - 1
        m = (o1 - o0) + (PRE if ultimo else XF)
        peca = _trecho(fontes[nome], int(round(a)) - PRE, m)
        if i > 0:
            peca[:XF] *= sobe
        if not ultimo:
            peca[-XF:] *= desce
        out[o0:o0 + m] += peca
        marcas.append(o0 + PRE)
    return out, marcas


def _limitar(x: np.ndarray, teto: float = 0.97) -> np.ndarray:
    """Segura picos acima do teto (só onde soma de camadas ou o MP3 original estoura).

    O ganho só é calculado em volta de cada pico; o resto da música passa intacto.
    """
    from scipy.ndimage import minimum_filter1d, uniform_filter1d

    pico = np.maximum(np.abs(x[:, 0]), np.abs(x[:, 1]))
    acima = np.flatnonzero(pico > teto)
    if len(acima) == 0:
        return x
    w = int(0.005 * SR)
    g = np.ones(len(x), dtype=np.float32)
    quebras = np.flatnonzero(np.diff(acima) > 4 * w)
    for a, b in zip(np.r_[acima[0], acima[quebras + 1]], np.r_[acima[quebras], acima[-1]], strict=True):
        a0, b0 = max(0, a - 2 * w), min(len(x), b + 2 * w + 1)
        local = np.minimum(1.0, teto / np.maximum(pico[a0:b0], 1e-9))
        local = uniform_filter1d(minimum_filter1d(local, size=2 * w + 1), size=w)
        g[a0:b0] = np.minimum(g[a0:b0], local)
    return np.clip(x * g[:, None], -1, 1).astype(np.float32)


def ajuste_local(faixa: Faixa, fontes: Fontes, inicio: int, tamanho: int) -> float:
    """Deslocamento (s) que encosta o ataque da bateria do trecho na grade.

    A grade é uma média da música inteira; num trecho específico a batida pode estar
    alguns milissegundos fora. O loop é recortado já com essa correção, para não
    "flamejar" contra a música original na entrada e na saída.
    """
    g = faixa.grade
    pb = g.batidas_por_compasso
    k0, k1 = max(0, inicio - 1), min(len(g.compassos), inicio + tamanho + 1)
    tempos = np.concatenate([g.compassos[k] + g.periodo * np.arange(pb) for k in range(k0, k1)])
    tempos_env, env = fontes.ataques(float(tempos.min()), float(tempos.max()))
    d, forca = fase_por_ataques(tempos, tempos_env, env, faixa.duracao, 0.015)
    return d if forca > 0.05 else 0.0


def _pedacos_loop(faixa: Faixa, e: Escolha) -> list[tuple[str, float, float]]:
    g = faixa.grade
    desloc = e.ajuste_ms / 1000 * SR
    out: list[tuple[str, float, float]] = []
    for j in range(e.compassos):
        k = e.inicio + (j % e.tamanho)
        a, b = g.compassos[k] * SR + desloc, g.fim_compasso(k) * SR + desloc
        nome = e.camadas[j]
        if out and out[-1][0] == nome and abs(out[-1][2] - a) < 1e-6:
            out[-1] = (nome, out[-1][1], b)  # continua o mesmo trecho sem emenda
        else:
            out.append((nome, a, b))
    return out


def _entrada_original(faixa: Faixa) -> tuple[int, tuple[float, float] | None]:
    """Compasso onde a música original entra depois do intro e a anacruse, se houver.

    Quando a música começa depois do primeiro tempo (uma voz puxando a frase, por
    exemplo), ela entra no compasso seguinte e esse começo toca por cima do fim do
    intro, em vez de deixar um buraco sem batida.
    """
    g = faixa.grade
    k = faixa.entrada
    a = faixa.primeiro_som
    if a - g.compassos[k] > 0.9 * g.periodo and k + 1 < len(g.compassos):
        return k + 1, (max(a - 0.05, 0.0) * SR, g.compassos[k + 1] * SR)
    return k, None


def montar(faixa: Faixa, fontes: Fontes, intro: Escolha | None, outro: Escolha | None) -> tuple[np.ndarray, dict]:
    g = faixa.grade
    n_total = len(faixa.audio)
    k_orig, anacruse = _entrada_original(faixa) if intro else (faixa.entrada, None)
    ini_orig = g.compassos[k_orig] * SR if intro else 0.0
    fim_orig = g.fim_compasso(faixa.saida - 1) * SR if outro else float(n_total)

    pedacos: list[tuple[str, float, float]] = []
    if intro:
        pedacos += _pedacos_loop(faixa, intro)
    i_orig = len(pedacos)
    pedacos.append(("completo", ini_orig, fim_orig))
    if outro:
        pedacos += _pedacos_loop(faixa, outro)

    out, marcas = _colar(pedacos, fontes)
    total = int(round(sum(b - a for _, a, b in pedacos))) + PRE
    out = out[:total]

    # começo da música antes do primeiro compasso inteiro, por cima do fim do intro
    if anacruse is not None:
        s_a, s_b = anacruse
        n = int(round(s_b - s_a)) - PRE + XF
        o = marcas[i_orig] - PRE - (int(round(s_b - s_a)) - PRE)
        if n > 2 * XF and o >= 0:
            peca = _trecho(fontes["completo"], int(round(s_a)), n)
            rampa = min(int(0.02 * SR), n // 2)
            peca[:rampa] *= np.linspace(0, 1, rampa, dtype=np.float32)[:, None]
            peca[-XF:] *= np.linspace(1, 0, XF, dtype=np.float32)[:, None]
            out[o:o + n] += peca

    # rabo da música (fade, reverb) por cima do começo do outro
    if outro and fim_orig < n_total:
        compasso = g.periodo * g.batidas_por_compasso * SR
        o_fim = marcas[i_orig + 1] - PRE
        rabo = _trecho(fontes["completo"], int(round(fim_orig)) - PRE, n_total - int(round(fim_orig)) + PRE)
        rabo = rabo[:int(4 * compasso)]
        env = np.ones(len(rabo), dtype=np.float32)
        env[:XF] = np.linspace(0, 1, XF)
        segura = min(len(rabo), int(2 * compasso))
        if len(rabo) > segura:
            env[segura:] = np.cos(np.linspace(0, np.pi / 2, len(rabo) - segura)) ** 2
        rabo = rabo[:len(out) - o_fim]
        out[o_fim:o_fim + len(rabo)] += rabo * env[:len(rabo), None]

    # fecha com 10 ms de fade para não terminar em estalo
    fim = int(0.01 * SR)
    out[-fim:] *= np.linspace(1, 0, fim, dtype=np.float32)[:, None]
    out = _limitar(out)

    # início de cada compasso no extended e o que toca nele, para desenhar a grade na tela
    compassos_s: list[float] = []
    camadas_s: list[str] = []

    def loop_na_grade(e: Escolha, t: float) -> None:
        for j in range(e.compassos):
            k = e.inicio + j % e.tamanho
            compassos_s.append(t)
            camadas_s.append(e.camadas[j])
            t += g.fim_compasso(k) - g.compassos[k]

    if intro:
        loop_na_grade(intro, PRE / SR)
    t_orig = marcas[i_orig] / SR - ini_orig / SR
    k_fim = faixa.saida if outro else len(g.compassos)
    for k in range(k_orig if intro else 0, k_fim):
        if g.compassos[k] + t_orig >= 0:
            compassos_s.append(g.compassos[k] + t_orig)
            camadas_s.append("musica")
    if outro:
        loop_na_grade(outro, marcas[i_orig + 1] / SR)

    meta = {
        "bpm": round(g.bpm, 3),
        "andamento_variavel": g.variavel,
        "primeiro_tempo_s": round(PRE / SR, 4),
        "inicio_original_s": round(marcas[i_orig] / SR, 3),
        "duracao_s": round(len(out) / SR, 2),
        "intro": intro.para_dict() if intro else None,
        "outro": outro.para_dict() if outro else None,
    }
    if outro:
        meta["inicio_outro_s"] = round(marcas[i_orig + 1] / SR, 3)
    meta["compassos_s"] = [round(x, 4) for x in compassos_s]
    meta["camadas_s"] = camadas_s
    return out, meta
