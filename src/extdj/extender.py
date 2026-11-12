"""Escolhe o loop e monta o extended: intro em loop + música original + outro em loop.

O intro e o outro podem entrar por cima da música (sobreposição, em compassos inteiros)
e ter um fader que sobe ou baixa o loop aos poucos.

Cada pedaço é copiado em compassos inteiros, com as posições acumuladas em ponto
flutuante. A 128 BPM um compasso tem 82.687,5 amostras: arredondar compasso a
compasso faria a grade escorregar ao longo do intro; aqui só a posição final de cada
emenda é arredondada, então o erro nunca passa de meia amostra.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace

import numpy as np

from . import compassos as cp
from .analise import Faixa
from .config import SR
from .grade import envelope_ataques, fase_por_ataques

FADERS = ("sem", "baixar", "subir")
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
    sobrepor: int = 0        # compassos do fim do intro (ou do começo do outro) por cima da música
    fader: str = "sem"       # sem, baixar ou subir: o volume do loop muda aos poucos
    fader_pontos: list | None = None   # [[compasso, nível], [compasso, nível]] escolhidos na tela

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
            elif nome == "sem_batida":
                x = st["vocals"] + st["other"]
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


def _tocar(out: np.ndarray, pedacos: list[tuple[str, float, float]], pos: float, fontes: Fontes,
           abre: bool, fecha: bool) -> tuple[list[float], float]:
    """Toca os pedaços (fonte, início, fim em amostras) um atrás do outro a partir de pos.

    pos é a posição no extended, com fração. Cada pedaço entra PRE antes do seu tempo
    forte; entre dois pedaços a troca é um cruzamento de XF amostras. Com `abre` o primeiro
    também entra cruzando e com `fecha` o último sai cruzando; sem `fecha` ele vai até PRE
    depois do fim, que é onde o extended termina. Devolve onde cada pedaço começou e a
    posição final.
    """
    sobe = np.linspace(0, 1, XF, dtype=np.float32)[:, None]
    desce = sobe[::-1]
    inicios = []
    for i, (nome, a, b) in enumerate(pedacos):
        inicios.append(pos)
        o0 = int(round(pos))
        pos += b - a
        o1 = int(round(pos))
        ultimo = i == len(pedacos) - 1
        m = (o1 - o0) + (PRE if ultimo and not fecha else XF)
        peca = _trecho(fontes[nome], int(round(a)) - PRE, m)
        if i > 0 or abre:
            peca[:XF] *= sobe
        if not ultimo or fecha:
            peca[-XF:] *= desce
        m = min(m, len(out) - o0)
        out[o0:o0 + m] += peca[:m]
    return inicios, pos


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


def _conter(x: np.ndarray, regioes: list[tuple[int, int]], teto: float = 0.97) -> None:
    """Baixa o volume da mixagem onde o loop toca por cima da música, sem picotar.

    Música e loop juntos passam do teto em toda batida. Cortar bumbo a bumbo (o que o
    limitador rápido do fim faz com picos soltos) deixaria o som sujo e bombeando; aqui o
    ganho anda devagar, uns 0,6 s para descer ou voltar, como quem segura o master da
    mesa enquanto as duas tocam. Com o fader baixando o loop, o volume volta sozinho.
    """
    from scipy.ndimage import minimum_filter1d, uniform_filter1d

    bloco = 512
    h = max(1, int(round(0.3 * SR / bloco)))
    margem = int(0.4 * SR)
    for a, b in regioes:
        a0, b0 = max(0, a - margem), min(len(x), b + margem)
        if b0 - a0 < 4 * bloco:
            continue
        pico = np.abs(x[a0:b0]).max(axis=1)
        nb = -(-len(pico) // bloco)
        picos = np.pad(pico, (0, nb * bloco - len(pico))).reshape(nb, bloco).max(axis=1)
        precisa = np.minimum(1.0, 0.97 * teto / np.maximum(picos, 1e-9))
        if precisa.min() >= 1.0:
            continue
        # a janela do mínimo cobre a da média: em cada pico o ganho já chegou ao necessário
        gb = uniform_filter1d(minimum_filter1d(precisa, size=2 * h + 3), size=2 * h + 1)
        g = np.interp(np.arange(b0 - a0), np.arange(nb) * bloco + bloco / 2, gb)
        # fora da sobreposição o ganho volta a 1 aos poucos
        peso = np.ones(b0 - a0)
        if a > a0:
            peso[:a - a0] = np.linspace(0, 1, a - a0)
        if b0 > b:
            peso[b - a0:] = np.linspace(1, 0, b0 - b)
        x[a0:b0] *= (1 - (1 - g) * peso).astype(np.float32)[:, None]


def ajuste_local(faixa: Faixa, fontes: Fontes, inicio: int, tamanho: int, vizinhos: int = 1) -> float:
    """Deslocamento (s) que encosta o ataque da bateria do trecho na grade.

    A grade é uma média da música inteira; num trecho específico a batida pode estar
    alguns milissegundos fora. O loop é recortado já com essa correção, para não
    "flamejar" contra a música original na entrada e na saída. A medida inclui
    `vizinhos` compassos de cada lado do trecho.
    """
    g = faixa.grade
    pb = g.batidas_por_compasso
    k0, k1 = max(0, inicio - vizinhos), min(len(g.compassos), inicio + tamanho + vizinhos)
    tempos = np.concatenate([g.compassos[k] + g.periodo * np.arange(pb) for k in range(k0, k1)])
    tempos_env, env = fontes.ataques(float(tempos.min()), float(tempos.max()))
    d, forca = fase_por_ataques(tempos, tempos_env, env, faixa.duracao, 0.015)
    return d if forca > 0.05 else 0.0


def _pedacos_loop(faixa: Faixa, e: Escolha, comprimentos: list[float], j0: int = 0) -> list[tuple[str, float, float]]:
    """Pedaços (fonte, início, fim em amostras) dos compassos j0, j0+1... do bloco.

    `comprimentos` diz quanto cada compasso ocupa no extended: o tamanho do compasso de
    onde ele sai ou, por cima da música, o do compasso da música que está por baixo.
    """
    g = faixa.grade
    desloc = e.ajuste_ms / 1000 * SR
    out: list[tuple[str, float, float]] = []
    for j, n in enumerate(comprimentos, start=j0):
        k = e.inicio + (j % e.tamanho)
        a = g.compassos[k] * SR + desloc
        nome = e.camadas[j]
        if out and out[-1][0] == nome and abs(out[-1][2] - a) < 1e-6:
            out[-1] = (nome, out[-1][1], a + n)  # continua o mesmo trecho sem emenda
        else:
            out.append((nome, a, a + n))
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


def curva_fader(e: Escolha, sobre: int) -> list[tuple[float, float]] | None:
    """Os dois pontos do fader, (compasso dentro do bloco, nível de 0 a 1), ou None.

    Sem pontos escolhidos na tela, a rampa ocupa os compassos que ficam por cima da
    música (o bloco inteiro, se não houver sobreposição): baixar vai de 100% a 0% e
    subir de 0% a 100%.
    """
    if e.fader not in ("baixar", "subir"):
        return None
    n = e.compassos
    if e.fader_pontos and len(e.fader_pontos) == 2:
        par = sorted((float(np.clip(p, 0, n)), float(np.clip(v, 0, 1))) for p, v in e.fader_pontos)
        return [par[0], par[1]]
    if sobre > 0:
        p0, p1 = (n - sobre, n) if e.lado == "intro" else (0, sobre)
    else:
        p0, p1 = 0, n
    n0, n1 = (1.0, 0.0) if e.fader == "baixar" else (0.0, 1.0)
    return [(float(p0), n0), (float(p1), n1)]


def _fader(x: np.ndarray, posicoes: np.ndarray, curva: list[tuple[float, float]]) -> None:
    """Aplica o fader num bloco: o nível anda em linha reta entre os dois pontos.

    O ganho é o nível ao quadrado, como num fader de mixer: no meio do caminho o loop
    está 12 dB abaixo, e não pela metade do volume. `posicoes` é onde começa cada compasso
    do bloco (e onde ele termina), nas amostras de x.
    """
    def amostra(p: float) -> float:
        j = int(np.clip(np.floor(p), 0, len(posicoes) - 2))
        return posicoes[j] + (p - j) * (posicoes[j + 1] - posicoes[j]) + PRE

    (p0, n0), (p1, n1) = curva
    s0, s1 = amostra(p0), amostra(p1)
    t = np.arange(len(x), dtype=np.float64)
    nivel = np.interp(t, [s0, s1], [n0, n1]) if s1 - s0 >= 1 else np.where(t < s0, n0, n1)
    x *= (nivel * nivel).astype(np.float32)[:, None]


def _bloco(out: np.ndarray, pedacos: list[tuple[str, float, float]], posicoes: np.ndarray, fontes: Fontes,
           abre: bool, fecha: bool, curva) -> tuple[list[float], float]:
    """Toca um bloco de loop (intro ou outro) em out, passando pelo fader se houver."""
    if curva is None:
        return _tocar(out, pedacos, float(posicoes[0]), fontes, abre, fecha)
    a = max(0, int(np.floor(posicoes[0])))
    b = min(len(out), int(np.ceil(posicoes[-1])) + PRE + XF + 4)
    buf = np.zeros((b - a, 2), dtype=np.float32)
    inicios, fim = _tocar(buf, pedacos, float(posicoes[0]) - a, fontes, abre, fecha)
    _fader(buf, posicoes - a, curva)
    out[a:b] += buf
    return [x + a for x in inicios], fim + a


def montar(faixa: Faixa, fontes: Fontes, intro: Escolha | None, outro: Escolha | None) -> tuple[np.ndarray, dict]:
    """Monta o extended: intro, música original e outro, cada um na sua camada.

    Sem sobreposição as três ficam uma depois da outra. Com `sobrepor`, os últimos
    compassos do intro tocam junto com os primeiros da música (e os primeiros do outro
    com os últimos dela), cada compasso do loop encaixado no compasso da música por baixo.
    """
    g = faixa.grade
    n_total = len(faixa.audio)
    k_orig, anacruse = _entrada_original(faixa) if intro else (faixa.entrada, None)
    ini_orig = g.compassos[k_orig] * SR if intro else 0.0
    fim_orig = g.fim_compasso(faixa.saida - 1) * SR if outro else float(n_total)
    k_fim = faixa.saida if outro else len(g.compassos)

    def tam(k: int) -> float:
        return (g.fim_compasso(k) - g.compassos[k]) * SR

    # compassos de cada bloco por cima da música: cabem no bloco e na música
    n_orig = max(0, k_fim - k_orig)
    s1 = int(np.clip(intro.sobrepor, 0, min(intro.compassos, n_orig))) if intro else 0
    s2 = int(np.clip(outro.sobrepor, 0, min(outro.compassos, n_orig - s1))) if outro else 0
    livres = intro.compassos - s1 if intro else 0

    comp_i = comp_o = []
    if intro:
        comp_i = ([tam(intro.inicio + j % intro.tamanho) for j in range(livres)]
                  + [tam(k_orig + j) for j in range(s1)])
    if outro:
        comp_o = ([tam(faixa.saida - s2 + j) for j in range(s2)]
                  + [tam(outro.inicio + j % outro.tamanho) for j in range(s2, outro.compassos)])
    estimado = sum(comp_i[:livres]) + (fim_orig - ini_orig) + sum(comp_o[s2:])
    out = np.zeros((int(np.ceil(estimado)) + PRE + XF + 8, 2), dtype=np.float32)
    curva_i = curva_fader(intro, s1) if intro else None
    curva_o = curva_fader(outro, s2) if outro else None

    def por_cima(e: Escolha, k: int, n: int) -> Escolha:
        """O bloco com o ataque encostado no da bateria da música por baixo (k a k+n-1).

        A música toca como é, e a bateria dela pode estar uns milissegundos fora da grade
        nesse trecho; os dois bumbos juntos, desencontrados, soariam ocos.
        """
        return replace(e, ajuste_ms=e.ajuste_ms - 1000 * ajuste_local(faixa, fontes, k, n, vizinhos=0))

    pos_orig = 0.0
    if intro:
        # o trecho por cima da música é um pedaço à parte, para a música entrar exatamente
        # onde ele começa, na mesma conta de posição
        pedacos = _pedacos_loop(faixa, intro, comp_i[:livres])
        n_livres = len(pedacos)
        if s1:
            pedacos += _pedacos_loop(faixa, por_cima(intro, k_orig, s1), comp_i[livres:], livres)
        pos_i = np.concatenate([[0.0], np.cumsum(comp_i)])
        inicios, fim = _bloco(out, pedacos, pos_i, fontes, False, True, curva_i)
        pos_orig = inicios[n_livres] if s1 else fim
    marca_orig = int(round(pos_orig)) + PRE
    _tocar(out, [("completo", ini_orig, fim_orig)], pos_orig, fontes, bool(intro), bool(outro))
    fim_musica = pos_orig + (fim_orig - ini_orig)
    fim = fim_musica
    if outro:
        p0 = pos_orig + (g.compassos[faixa.saida - s2] * SR - ini_orig) if s2 else fim_musica
        pos_o = p0 + np.concatenate([[0.0], np.cumsum(comp_o)])
        pedacos = _pedacos_loop(faixa, outro, comp_o[s2:], s2)
        if s2:
            pedacos = _pedacos_loop(faixa, por_cima(outro, faixa.saida - s2, s2), comp_o[:s2]) + pedacos
        _, fim = _bloco(out, pedacos, pos_o, fontes, True, False, curva_o)
    out = out[:int(round(fim)) + PRE]

    # começo da música antes do primeiro compasso inteiro, por cima do fim do intro
    if anacruse is not None:
        s_a, s_b = anacruse
        n = int(round(s_b - s_a)) - PRE + XF
        o = marca_orig - PRE - (int(round(s_b - s_a)) - PRE)
        if n > 2 * XF and o >= 0:
            peca = _trecho(fontes["completo"], int(round(s_a)), n)
            rampa = min(int(0.02 * SR), n // 2)
            peca[:rampa] *= np.linspace(0, 1, rampa, dtype=np.float32)[:, None]
            peca[-XF:] *= np.linspace(1, 0, XF, dtype=np.float32)[:, None]
            out[o:o + n] += peca

    # rabo da música (fade, reverb) por cima do outro, sem bateria e baixo:
    # quem segura a batida ali é o loop, e a pancada final dobraria por cima dele
    o_fim = int(round(fim_musica))
    if outro and fim_orig < n_total:
        compasso = g.periodo * g.batidas_por_compasso * SR
        rabo = _trecho(fontes["sem_batida"], int(round(fim_orig)) - PRE, n_total - int(round(fim_orig)) + PRE)
        rabo = rabo[:int(4 * compasso)]
        env = np.ones(len(rabo), dtype=np.float32)
        env[:XF] = np.linspace(0, 1, XF)
        segura = min(len(rabo), int(2 * compasso))
        if len(rabo) > segura:
            env[segura:] = np.cos(np.linspace(0, np.pi / 2, len(rabo) - segura)) ** 2
        rabo = rabo[:len(out) - o_fim]
        out[o_fim:o_fim + len(rabo)] += rabo * env[:len(rabo), None]

    # fecha com 10 ms de fade para não terminar em estalo
    fim_fade = int(0.01 * SR)
    out[-fim_fade:] *= np.linspace(1, 0, fim_fade, dtype=np.float32)[:, None]
    juntos = []
    if s1:
        juntos.append((marca_orig - PRE, int(round(pos_i[-1])) + PRE + XF))
    if s2:
        juntos.append((int(round(pos_o[0])), o_fim + PRE + XF))
    if juntos:
        _conter(out, juntos)
    out = _limitar(out)

    # início de cada compasso no extended, o que toca nele e se a música está por baixo,
    # para desenhar a grade na tela
    compassos_s: list[float] = []
    camadas_s: list[str] = []
    musica_s: list[bool] = []

    def marcar(t: float, camada: str, musica: bool) -> None:
        compassos_s.append(t)
        camadas_s.append(camada)
        musica_s.append(musica)

    for j in range(livres):
        marcar((pos_i[j] + PRE) / SR, intro.camadas[j], False)
    t_orig = (marca_orig - ini_orig) / SR
    for k in range(k_orig if intro else 0, k_fim):
        if g.compassos[k] + t_orig < 0:
            continue
        camada = "musica"
        if intro and k - k_orig < s1:
            camada = intro.camadas[livres + k - k_orig]
        elif outro and k >= faixa.saida - s2:
            camada = outro.camadas[k - faixa.saida + s2]
        marcar(g.compassos[k] + t_orig, camada, True)
    for j in range(s2, outro.compassos if outro else 0):
        marcar((pos_o[j] + PRE) / SR, outro.camadas[j], False)

    def lado(e: Escolha, sobre: int, curva) -> dict:
        d = e.para_dict()
        d.update(sobrepor=sobre, curva=[list(p) for p in curva] if curva else None)
        return d

    meta = {
        "bpm": round(g.bpm, 3),
        "andamento_variavel": g.variavel,
        "primeiro_tempo_s": round(PRE / SR, 4),
        "inicio_original_s": round(marca_orig / SR, 3),
        "duracao_s": round(len(out) / SR, 2),
        "intro": lado(intro, s1, curva_i) if intro else None,
        "outro": lado(outro, s2, curva_o) if outro else None,
        # quanto cada bloco ainda pode entrar na música
        "sobrepor_max": {"intro": min(intro.compassos, n_orig - s2) if intro else 0,
                         "outro": min(outro.compassos, n_orig - s1) if outro else 0},
    }
    if intro:
        meta["intro_s"] = [round(PRE / SR, 4), round((pos_i[-1] + PRE) / SR, 4)]
    if outro:
        meta["inicio_outro_s"] = round((int(round(pos_o[0])) + PRE) / SR, 3)
        meta["fim_original_s"] = round((o_fim + PRE) / SR, 3)
        meta["outro_s"] = [round((pos_o[0] + PRE) / SR, 4), round((pos_o[-1] + PRE) / SR, 4)]
    meta["compassos_s"] = [round(x, 4) for x in compassos_s]
    meta["camadas_s"] = camadas_s
    meta["musica_s"] = musica_s
    return out, meta
