"""Sobreposição do intro e do outro com a música e o fader do loop."""

import numpy as np
from test_basico import _faixa_cliques

from extdj.config import SR
from extdj.extender import PRE, Escolha, Fontes, ajuste_local, curva_fader, montar


def _blocos(f, fontes, sobre_i=4, sobre_o=4, fader_i="sem", fader_o="sem", inicio_o=30):
    def bloco(lado, inicio, sobre, fader):
        # o ajuste medido como no escolher: a medida do ataque tem o mesmo viés no loop e na música
        ajuste = round(ajuste_local(f, fontes, inicio, 4) * 1000, 2)
        return Escolha(lado, "batida", inicio=inicio, tamanho=4, compassos=8, nota=1, camadas=["batida"] * 8,
                       ajuste_ms=ajuste, sobrepor=sobre, fader=fader)
    return bloco("intro", 5, sobre_i, fader_i), bloco("outro", inicio_o, sobre_o, fader_o)


def _cliques(mono, limiar):
    return np.flatnonzero((mono[1:] > limiar) & (mono[:-1] <= limiar)) + 1


def test_sobreposicao_encaixa_na_grade():
    f = _faixa_cliques()          # 40 compassos, a música vai do 0 ao 37
    fontes = Fontes(f)
    intro, outro = _blocos(f, fontes)
    out, meta = montar(f, fontes, intro, outro)
    compasso = 4 * f.grade.periodo * SR
    n = 8 + 38 + 8 - 4 - 4
    assert abs(len(out) - (n * compasso + PRE)) <= 1
    c, cam, mus = meta["compassos_s"], meta["camadas_s"], meta["musica_s"]
    assert len(c) == n
    assert np.allclose(np.diff(c), 4 * f.grade.periodo, atol=1e-3)
    assert mus == [False] * 4 + [True] * 38 + [False] * 4
    assert cam[:8] == ["batida"] * 8 and set(cam[8:38]) == {"musica"} and cam[38:] == ["batida"] * 8
    assert abs(meta["inicio_original_s"] - (PRE / SR + 4 * compasso / SR)) < 1e-3
    assert abs(meta["intro_s"][1] - c[8]) < 1e-3 and abs(meta["outro_s"][0] - c[38]) < 1e-3
    # loop e música batem juntos: um clique por tempo, nenhum dobrado ao lado nem faltando
    acima = _cliques(out[:, 0], 0.3)
    periodo = f.grade.periodo * SR
    k = np.round((acima - PRE) / periodo)
    erro = acima - (PRE + periodo * k)
    assert len(np.unique(k)) == len(k) == k[-1] - k[0] + 1
    # da entrada ao fim da música (com o loop por cima) no lugar exato; o loop sozinho fica
    # no ajuste medido do ataque, a menos de 3 ms
    t = acima / SR
    na_musica = (t > meta["inicio_original_s"] - 1e-3) & (t < meta["fim_original_s"] - 0.003)
    assert na_musica.sum() == 38 * 4
    assert np.abs(erro[na_musica]).max() <= 1.0
    assert np.abs(erro).max() <= 0.003 * SR
    assert np.abs(out).max() <= 0.97 + 1e-6


def test_sobreposicao_cabe_na_musica():
    f = _faixa_cliques(compassos=12)   # música de 10 compassos
    fontes = Fontes(f)
    intro, outro = _blocos(f, fontes, sobre_i=8, sobre_o=8, inicio_o=4)
    _, meta = montar(f, fontes, intro, outro)
    assert meta["intro"]["sobrepor"] == 8
    assert meta["outro"]["sobrepor"] == 2
    assert meta["sobrepor_max"] == {"intro": 8, "outro": 2}


def test_fader_baixa_e_sobe_o_loop_aos_poucos():
    f = _faixa_cliques()
    f.audio *= 0.25                # longe do teto, para medir sem limitador (bateria é o mesmo sinal)
    fontes = Fontes(f)
    intro, outro = _blocos(f, fontes, fader_i="baixar", fader_o="subir")
    out, meta = montar(f, fontes, intro, outro)
    assert meta["intro"]["curva"] == [[4.0, 1.0], [8.0, 0.0]]
    assert meta["outro"]["curva"] == [[0.0, 0.0], [4.0, 1.0]]
    c = meta["compassos_s"]
    pico = 0.25 * 0.9

    def no_tempo_forte(k):
        p = int(round(c[k] * SR))
        return float(out[p - 150:p + 60, 0].max())

    # nível do fader em cada compasso sobreposto: 1, 3/4, 1/2, 1/4 (ganho é o quadrado)
    intro_v = [no_tempo_forte(k) for k in range(4, 8)]
    assert np.allclose(intro_v, [pico * (1 + v * v) for v in (1, 0.75, 0.5, 0.25)], rtol=0.02)
    assert abs(no_tempo_forte(8) - pico) < 0.01 * pico            # depois: só a música
    outro_v = [no_tempo_forte(k) for k in range(38, 42)]
    assert np.allclose(outro_v, [pico * (1 + v * v) for v in (0, 0.25, 0.5, 0.75)], rtol=0.02)
    # loop sozinho, inteiro (no 43: no 42 o loop volta ao começo e o ataque, adiantado pelo
    # ajuste medido nesta grade sintética, cai no cruzamento da emenda)
    assert abs(no_tempo_forte(43) - pico) < 0.01 * pico


def test_curva_do_fader():
    e = Escolha("intro", "batida", inicio=0, tamanho=4, compassos=16, nota=1, camadas=[], fader="baixar")
    assert curva_fader(e, 0) == [(0.0, 1.0), (16.0, 0.0)]       # sem sobreposição: o bloco todo
    assert curva_fader(e, 8) == [(8.0, 1.0), (16.0, 0.0)]
    e.fader = "subir"
    assert curva_fader(e, 8) == [(8.0, 0.0), (16.0, 1.0)]
    e.fader_pontos = [[20, 0.4], [-3, 1.5]]                       # pontos da tela: em ordem e no bloco
    assert curva_fader(e, 8) == [(0.0, 1.0), (16.0, 0.4)]
    e.fader = "sem"
    assert curva_fader(e, 8) is None
