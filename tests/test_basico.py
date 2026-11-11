"""Testes sem rede e sem GPU: grade, Camelot e precisão da montagem."""

from pathlib import Path

import numpy as np

from extdj.analise import Faixa
from extdj.config import SR
from extdj.extender import PRE, Escolha, Fontes, montar
from extdj.grade import Grade, ajustar_grade
from extdj.tom import camelot


def test_camelot():
    assert camelot(0, False) == "8B"    # Dó maior
    assert camelot(9, True) == "8A"     # Lá menor
    assert camelot(7, False) == "9B"    # Sol maior
    assert camelot(4, False) == "12B"   # Mi maior
    assert camelot(6, True) == "11A"    # Fá# menor
    assert camelot(11, False) == "1B"   # Si maior


def test_grade_fixa_com_ruido_de_deteccao():
    rng = np.random.default_rng(1)
    periodo = 60 / 128
    verdade = 0.31 + periodo * np.arange(480)
    # o detector trabalha em quadros de 20 ms
    detectadas = np.round((verdade + rng.normal(0, 0.003, len(verdade))) / 0.02) * 0.02
    primeiros = detectadas[2::4]
    g = ajustar_grade(detectadas, primeiros, verdade[-1] + 1)
    assert abs(g.bpm - 128) < 0.02
    assert not g.variavel
    # a batida 2 abre o compasso
    assert min(abs(np.asarray(g.compassos) - verdade[2])) < 0.006


def test_grade_variavel():
    # baterista ao vivo: andamento oscilando entre ~96 e ~100 BPM
    i = np.arange(400)
    periodos = 60 / (98 + 2 * np.sin(i / 40))
    batidas = np.cumsum(periodos)
    g = ajustar_grade(batidas, batidas[::4], batidas[-1] + 1)
    assert g.variavel
    assert g.bpm_max - g.bpm_min > 2


def _faixa_cliques(bpm=128.0, compassos=40, ini=0.5):
    periodo = 60 / bpm
    dur = ini + compassos * 4 * periodo + 2
    n = int(dur * SR)
    x = np.zeros((n, 2), np.float32)
    clique = np.exp(-np.arange(200) / 30).astype(np.float32)
    for b in range(compassos * 4):
        p = int(round((ini + b * periodo) * SR))
        x[p:p + 200, :] += clique[:, None] * (0.9 if b % 4 == 0 else 0.5)
    inicios = [ini + k * 4 * periodo for k in range(compassos)]
    g = Grade(bpm=bpm, periodo=periodo, batidas_por_compasso=4, compassos=inicios,
              variavel=False, deriva_ms=0.0, bpm_min=bpm, bpm_max=bpm, confianca=1.0)
    zeros = np.zeros_like(x)
    st = {"drums": x, "bass": zeros, "other": zeros, "vocals": zeros}
    nb = len(inicios)
    return Faixa(caminho=Path("teste.wav"), audio=x, stems=st, grade=g, info={},
                 voz=np.zeros(nb), rms_mix=np.zeros(nb), rms_bateria=np.zeros(nb),
                 validos=np.ones(nb, bool), entrada=0, saida=nb - 2, primeiro_som=ini)


def test_montagem_mantem_a_grade():
    f = _faixa_cliques()
    intro = Escolha("intro", "batida", inicio=5, tamanho=4, compassos=32, nota=1, camadas=["batida"] * 32)
    outro = Escolha("outro", "batida", inicio=30, tamanho=4, compassos=16, nota=1, camadas=["batida"] * 16)
    out, meta = montar(f, Fontes(f), intro, outro)
    mono = out[:, 0]
    # posição de cada clique: amostra onde o sinal cruza 0,3
    acima = np.flatnonzero((mono[1:] > 0.3) & (mono[:-1] <= 0.3)) + 1
    periodo = f.grade.periodo * SR
    esperado = PRE + periodo * np.round((acima - PRE) / periodo)
    erro = np.abs(acima - esperado)
    assert erro.max() <= 1.0, erro.max()
    # todos os tempos presentes: intro + música + outro, sem buraco
    n_batidas = int(round((acima[-1] - acima[0]) / periodo)) + 1
    assert n_batidas == len(acima)
    assert abs(meta["inicio_original_s"] - (PRE / SR + 32 * 4 * f.grade.periodo)) < 1e-3


def test_grade_com_trechos_em_meio_tempo():
    # 136 BPM, mas o detector só marcou uma batida sim, outra não em boa parte da música
    periodo = 60 / 136
    rapidas = 0.2 + periodo * np.arange(480)
    detectadas = np.concatenate([rapidas[:120:2], rapidas[120:200], rapidas[200::2]])
    g = ajustar_grade(detectadas, detectadas[::4], rapidas[-1] + 1)
    assert abs(g.bpm - 136) < 0.05
    assert not g.variavel


def test_hip_hop_nao_vira_180():
    periodo = 60 / 90
    lentas = 0.2 + periodo * np.arange(240)
    meio = (lentas[100:160] + periodo / 2)
    detectadas = np.sort(np.concatenate([lentas, meio]))
    g = ajustar_grade(detectadas, lentas[::4], lentas[-1] + 1)
    assert abs(g.bpm - 90) < 0.05


def test_grade_com_trechos_no_contratempo():
    # funk a 130 BPM: em dois trechos o detector marcou o "e" de cada tempo
    rng = np.random.default_rng(2)
    periodo = 60 / 130
    verdade = 0.02 + periodo * np.arange(240)
    detectadas = verdade.copy()
    for a, b in ((130, 150), (200, 222)):
        detectadas[a:b] += periodo / 2
    detectadas = np.round((detectadas + rng.normal(0, 0.003, len(detectadas))) / 0.02) * 0.02
    g = ajustar_grade(detectadas, verdade[::4], verdade[-1] + 1)
    assert abs(g.bpm - 130) < 0.05
    assert not g.variavel
    # o primeiro tempo continua no lugar até o fim da música
    c = np.asarray(g.compassos)
    k = np.round((c - 0.02) / periodo)
    assert np.abs(c - (0.02 + periodo * k)).max() < 0.006
    assert np.all(k % 4 == 0)


def test_saida_no_ultimo_compasso_com_batida_ate_o_fim():
    from extdj import compassos as cp
    from extdj.analise import _limites_musica

    f = _faixa_cliques(compassos=20)
    g = f.grade
    bat = f.audio[:, 0].copy()
    # a música acaba numa pancada no primeiro tempo do compasso 18
    corte = int((g.compassos[18] + 0.1) * SR)
    bat[corte:] = 0
    validos = cp.completos(g, SR, len(bat))
    rms = cp.rms_db(bat, g, SR)
    _, saida, _ = _limites_musica(g, bat, bat, rms, rms, validos)
    assert saida == 18


def test_camadas_comecam_na_bateria():
    from extdj.extender import _camadas

    plano = _camadas(32, "instrumental")
    assert plano == ["batida"] * 16 + ["batida_baixo"] * 8 + ["instrumental"] * 8
    assert _camadas(8, "completo") == ["batida"] * 4 + ["batida_baixo"] * 4
