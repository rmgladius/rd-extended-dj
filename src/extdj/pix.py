"""Pix para quem quiser apoiar o projeto: o texto do "Pix copia e cola" e o QR com o mesmo texto.

Segue o BR Code do Banco Central, sem valor fixo (quem paga escolhe quanto). Cada campo é
ID (2 dígitos) + tamanho (2 dígitos) + valor, e o último guarda o CRC16 de tudo o que vem antes.
"""

from __future__ import annotations

import unicodedata
from functools import cache

import segno

CHAVE = "561cdaea-b433-4980-b2fd-8f4578e6e37d"  # chave aleatória: não expõe CPF, e-mail nem telefone
NOME = "Rodrigo Dias"
CIDADE = "Florianópolis"


def copia_e_cola(chave: str, nome: str, cidade: str) -> str:
    conta = campo("00", "br.gov.bcb.pix") + campo("01", chave.strip())
    sem_crc = (
        campo("00", "01")  # versão do formato
        + campo("26", conta)  # onde o dinheiro cai
        + campo("52", "0000")  # categoria do comércio: não se aplica
        + campo("53", "986")  # real
        + campo("58", "BR")
        + campo("59", ascii_visivel(nome, 25))  # o padrão só aceita ASCII
        + campo("60", ascii_visivel(cidade, 15))
        + campo("62", campo("05", "***"))  # sem identificador: o mesmo código serve para sempre
        + "6304"
    )
    return sem_crc + f"{crc16(sem_crc):04X}"


def campo(id_: str, valor: str) -> str:
    if not 1 <= len(valor) <= 99:
        raise ValueError(f"O campo {id_} do Pix precisa ter de 1 a 99 caracteres.")
    return f"{id_}{len(valor):02d}{valor}"


def ascii_visivel(texto: str, maximo: int) -> str:
    """Tira acentos e o que não for ASCII visível, e corta no tamanho máximo do campo."""
    limpo = "".join(c for c in unicodedata.normalize("NFD", texto) if " " <= c <= "~").strip()
    return limpo[:maximo].rstrip()


def crc16(texto: str) -> int:
    """CRC16-CCITT (polinômio 0x1021, começando em 0xFFFF), o que o BR Code usa."""
    crc = 0xFFFF
    for b in texto.encode("ascii"):
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return crc


def matriz(texto: str) -> list[list[bool]]:
    """Os quadradinhos do QR, sem a margem branca; True é escuro. Correção de erro média."""
    qr = segno.make(texto, error="m", micro=False)
    return [[bool(m) for m in linha] for linha in qr.matrix]


def svg(m: list[list[bool]]) -> str:
    """O QR em vetor, um quadradinho por unidade. Módulos vizinhos na mesma linha viram um retângulo só.

    Sem a margem e sem o fundo branco: os dois vêm da moldura em volta, na tela.
    """
    lado = len(m)
    partes = []
    for y, linha in enumerate(m):
        x = 0
        while x < lado:
            if not linha[x]:
                x += 1
                continue
            inicio = x
            while x < lado and linha[x]:
                x += 1
            partes.append(f"M{inicio} {y}h{x - inicio}v1h-{x - inicio}z")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {lado} {lado}" '
        f'shape-rendering="crispEdges" role="img" aria-label="QR do Pix">'
        f'<path fill="#000" d="{"".join(partes)}"/></svg>'
    )


@cache
def codigo_do_projeto() -> str:
    return copia_e_cola(CHAVE, NOME, CIDADE)


@cache
def qr_do_projeto() -> str:
    return svg(matriz(codigo_do_projeto()))
