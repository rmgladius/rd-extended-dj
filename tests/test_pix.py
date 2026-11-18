"""Pix do botão Apoiar: código no padrão do Banco Central e QR que o app do banco consegue ler."""

import re

import numpy as np
import pytest
import zxingcpp

from extdj import pix


def test_crc16_e_o_ccitt_que_o_banco_central_usa():
    assert pix.crc16("123456789") == 0x29B1


def test_gera_o_mesmo_codigo_do_exemplo_do_banco_central():
    # O exemplo de QR estático do manual do BR Code, letra por letra.
    assert pix.copia_e_cola("123e4567-e12b-12d1-a456-426655440000", "Fulano de Tal", "BRASILIA") == (
        "00020126580014br.gov.bcb.pix0136123e4567-e12b-12d1-a456-4266554400005204000053039865802BR"
        "5913Fulano de Tal6008BRASILIA62070503***63041D3D"
    )


def test_codigo_do_projeto_nao_muda_sem_querer():
    # O mesmo do RD Track Downloader.
    assert pix.codigo_do_projeto() == (
        "00020126580014br.gov.bcb.pix0136561cdaea-b433-4980-b2fd-8f4578e6e37d5204000053039865802BR"
        "5912Rodrigo Dias6013Florianopolis62070503***6304F35F"
    )


@pytest.mark.parametrize(
    ("texto", "maximo", "esperado"),
    [
        ("Florianópolis", 15, "Florianopolis"),
        ("São João da Boa Vista", 15, "Sao Joao da Boa"),
        ("  Conceição  ", 25, "Conceicao"),
        ("Ação ✓ 🎵", 25, "Acao"),
    ],
)
def test_nome_e_cidade_vao_sem_acento_e_no_tamanho_do_campo(texto, maximo, esperado):
    assert pix.ascii_visivel(texto, maximo) == esperado


def test_recusa_campo_vazio_ou_grande_demais():
    with pytest.raises(ValueError):
        pix.campo("01", "")
    with pytest.raises(ValueError):
        pix.campo("01", "a" * 100)
    assert pix.campo("01", "a" * 99) == "0199" + "a" * 99


def _desenhar(svg: str, escala: int = 4, margem: int = 4) -> np.ndarray:
    """Pinta o SVG como a tela faria (preto no branco, com a margem da moldura) para o leitor."""
    lado = int(re.search(r'viewBox="0 0 (\d+) \1"', svg).group(1))
    m = np.zeros((lado, lado), dtype=bool)
    for x, y, w in re.findall(r"M(\d+) (\d+)h(\d+)v1h-\3z", svg):
        m[int(y), int(x) : int(x) + int(w)] = True
    m = np.pad(m, margem)
    return np.where(np.kron(m, np.ones((escala, escala), dtype=bool)), 0, 255).astype(np.uint8)


def test_svg_tem_os_mesmos_quadradinhos_da_matriz():
    m = pix.matriz(pix.codigo_do_projeto())
    imagem = _desenhar(pix.svg(m), escala=1, margem=0)
    assert np.array_equal(imagem == 0, np.array(m))


def test_qr_le_de_volta_o_mesmo_codigo():
    # Como a câmera do app do banco: tem de sair o mesmo copia e cola, sem nada a mais.
    lido = zxingcpp.read_barcode(_desenhar(pix.qr_do_projeto()))
    assert lido is not None
    assert lido.format == zxingcpp.BarcodeFormat.QRCode
    assert lido.text == pix.codigo_do_projeto()
