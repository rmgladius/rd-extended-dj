"""Testes do programa com janela: servidor local, grade do extended e limitador."""

import json
import urllib.error
import urllib.request

import numpy as np
from scipy.ndimage import minimum_filter1d, uniform_filter1d
from test_basico import _faixa_cliques

from extdj import __version__, pix
from extdj.config import SR
from extdj.extender import PRE, Escolha, Fontes, _limitar, montar


def test_grade_do_extended():
    f = _faixa_cliques()
    intro = Escolha("intro", "batida", inicio=5, tamanho=4, compassos=32, nota=1, camadas=["batida"] * 32)
    outro = Escolha("outro", "batida", inicio=30, tamanho=4, compassos=16, nota=1, camadas=["batida"] * 16)
    _, meta = montar(f, Fontes(f), intro, outro)
    c, cam = meta["compassos_s"], meta["camadas_s"]
    assert len(c) == len(cam) == 32 + (f.saida - f.entrada) + 16
    assert abs(c[0] - PRE / SR) < 1e-4
    assert cam[:32] == ["batida"] * 32 and cam[-16:] == ["batida"] * 16
    assert set(cam[32:-16]) == {"musica"}
    assert abs(c[32] - meta["inicio_original_s"]) < 1e-3
    assert abs(c[-16] - meta["inicio_outro_s"]) < 1e-3
    passo = np.diff(c)
    assert np.allclose(passo, 4 * f.grade.periodo, atol=1e-3)


def _limitar_referencia(x, teto=0.97):
    pico = np.abs(x).max(axis=1)
    if pico.max() <= teto:
        return x
    ganho = np.minimum(1.0, teto / np.maximum(pico, 1e-9))
    w = int(0.005 * SR)
    g = uniform_filter1d(minimum_filter1d(ganho, size=2 * w + 1), size=w)
    return np.clip(x * g[:, None], -1, 1).astype(np.float32)


def test_limitador_igual_ao_de_referencia():
    rng = np.random.default_rng(3)
    x = (rng.normal(0, 0.2, (SR * 5, 2))).astype(np.float32)
    for p in (1000, 1300, 90_000, 150_000, SR * 5 - 10):
        x[p] = 1.4
    a, b = _limitar_referencia(x), _limitar(x)
    assert np.array_equal(a, b)
    assert np.abs(b).max() <= 0.97 + 1e-6
    # longe dos picos o sinal fica intacto
    assert np.array_equal(b[40_000:80_000], x[40_000:80_000])


class _SessaoFalsa:
    def __init__(self, arquivo):
        self.arquivo = arquivo

    def audio_original(self, mid):
        return self.arquivo

    def estado(self):
        return {"musicas": []}


def _servidor(tmp_path):
    from extdj.app.servidor import Servidor

    arq = tmp_path / "a.wav"
    arq.write_bytes(bytes(range(256)) * 40)
    srv = Servidor(_SessaoFalsa(arq))
    srv.em_segundo_plano()
    return srv


def _pedir(url, cabecalhos=None):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=cabecalhos or {})) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_servidor_exige_codigo(tmp_path):
    srv = _servidor(tmp_path)
    try:
        base = srv.endereco
        st, _, corpo = _pedir(base)
        assert st == 200 and srv.token.encode() in corpo
        assert f"Versão {__version__}".encode() in corpo and b"__VERSAO__" not in corpo
        # painel Apoiar: código, chave e QR preenchidos pelo servidor
        assert b"__PIX_" not in corpo
        assert f'data-copiar="{pix.codigo_do_projeto()}"'.encode() in corpo
        assert f">{pix.CHAVE}</b>".encode() in corpo and b'aria-label="QR do Pix"' in corpo
        assert _pedir(base + "api/estado")[0] == 403
        assert _pedir(base + "api/estado", {"X-Token": "errado"})[0] == 403
        st, _, corpo = _pedir(base + "api/estado", {"X-Token": srv.token})
        assert st == 200 and json.loads(corpo) == {"musicas": []}
        # site de fora que aponte o próprio domínio para 127.0.0.1
        assert _pedir(base, {"Host": "malicioso.example:80"})[0] == 403
        # não sai da pasta da interface
        assert _pedir(base + "ui/..%2f..%2fconfig.py")[0] == 404
    finally:
        srv.shutdown()


def test_audio_com_range(tmp_path):
    srv = _servidor(tmp_path)
    try:
        url = f"{srv.endereco}audio/x/original?t={srv.token}"
        st, cab, corpo = _pedir(url, {"Range": "bytes=100-199"})
        assert st == 206
        assert cab["Content-Range"] == "bytes 100-199/10240"
        assert corpo == (bytes(range(256)) * 40)[100:200]
        st, _, corpo = _pedir(url)
        assert st == 200 and len(corpo) == 10240
        assert _pedir(url, {"Range": "bytes=999999-"})[0] == 416
    finally:
        srv.shutdown()
