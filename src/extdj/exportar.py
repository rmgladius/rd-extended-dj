"""Nome, tags e gravação do arquivo extended (usado pela linha de comando e pela janela)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

from . import audio as au
from .analise import Faixa
from .config import SR
from .extender import NOMES_MODO, Escolha


def bpm_tag(bpm: float) -> str:
    return str(round(bpm)) if abs(bpm - round(bpm)) < 0.05 else f"{bpm:.1f}"


def nome_seguro(nome: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", nome).strip().rstrip(".")


def base_nome(info: dict, caminho: Path) -> str:
    if info.get("artista") and info.get("titulo"):
        return nome_seguro(f"{info['artista']} - {info['titulo']}")
    return nome_seguro(caminho.stem)


def destino(faixa: Faixa, pasta: Path, formato: str) -> Path:
    return pasta / f"{base_nome(faixa.info, faixa.caminho)} (Extended).{formato}"


def gravar(faixa: Faixa, sinal: np.ndarray, meta: dict, intro: Escolha | None, outro: Escolha | None,
           pasta: Path, formato: str = "wav", com_json: bool = True) -> Path:
    """Grava o extended com as tags do original, BPM, tom e um comentário do que foi feito."""
    arq = destino(faixa, pasta, formato)
    tags = {
        "title": (faixa.info.get("titulo") or faixa.caminho.stem) + " (Extended)",
        "TBPM": bpm_tag(faixa.grade.bpm),
        "TKEY": faixa.info["tom"]["tom"],
        "comment": "extdj: " + ", ".join(
            f"{e.lado} {e.compassos} compassos ({NOMES_MODO[e.modo]})" for e in (intro, outro) if e),
    }
    au.salvar(arq, sinal, SR, formato, origem=faixa.caminho, tags=tags)
    if com_json:
        dados = dict(meta)
        dados.pop("compassos_s", None)
        dados.pop("camadas_s", None)
        dados.update({"arquivo_original": faixa.caminho.name, "tom": faixa.info["tom"],
                      "estilos": faixa.info["estilos"]})
        arq.with_suffix(".extdj.json").write_text(json.dumps(dados, ensure_ascii=False, indent=2),
                                                  encoding="utf-8")
    return arq
