"""Análise completa de uma música: grade, stems, voz, tom, estilo e padrão da batida."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import audio as au
from . import compassos as cp
from . import estilo, ritmo, stems, tom
from .config import SR, VERSAO_ANALISE, pasta_cache
from .grade import Grade, ajustar_grade, detectar_batidas, envelope_ataques


@dataclass
class Faixa:
    caminho: Path
    audio: np.ndarray
    stems: dict[str, np.ndarray]
    grade: Grade
    info: dict
    voz: np.ndarray
    rms_mix: np.ndarray
    rms_bateria: np.ndarray
    validos: np.ndarray
    entrada: int          # compasso que contém o primeiro som da música
    saida: int            # compasso logo depois do último compasso com batida cheia
    primeiro_som: float   # segundos
    tempos: dict[str, float] = field(default_factory=dict)

    @property
    def duracao(self) -> float:
        return len(self.audio) / SR


def _primeiro_som(mono: np.ndarray) -> float:
    """Instante do primeiro som audível (45 dB abaixo do pico)."""
    q = cp._rms_quadros(mono, n=1024, hop=512)
    db = 20 * np.log10(q)
    acima = np.flatnonzero(db > db.max() - 45)
    return float(acima[0] * 512 / SR) if len(acima) else 0.0


def _limites_musica(grade: Grade, mono: np.ndarray, rms_mix: np.ndarray, rms_bat: np.ndarray,
                    validos: np.ndarray) -> tuple[int, int, float]:
    """(compasso de entrada, compasso de saída, instante do primeiro som)."""
    a = _primeiro_som(mono)
    inicios = grade.inicios
    # o compasso que contém o primeiro som (com 60 ms de folga para ataques adiantados)
    entrada = int(np.clip(np.searchsorted(inicios, a + 0.06, side="right") - 1, 0, len(inicios) - 1))

    cheio = validos & (rms_bat > -60)
    if cheio.sum() < 4:
        return entrada, len(inicios), a
    ref_mix = np.median(rms_mix[cheio])
    ref_bat = np.median(rms_bat[cheio])
    fortes = np.flatnonzero(validos & (rms_mix >= ref_mix - 9) & (rms_bat >= ref_bat - 15))
    fortes = fortes[fortes > entrada]
    if len(fortes) == 0:
        return entrada, len(inicios), a
    return entrada, int(fortes[-1] + 1), a


def _caminho_cache(caminho: Path) -> Path:
    return pasta_cache() / "analise" / f"{stems.chave_arquivo(caminho)}.json"


def analisar(caminho: Path, dispositivo: str, usar_cache: bool = True) -> Faixa:
    tempos: dict[str, float] = {}
    t = time.perf_counter()

    def marca(nome: str) -> None:
        nonlocal t
        agora = time.perf_counter()
        tempos[nome] = round(agora - t, 2)
        t = agora

    sinal = au.carregar(caminho)
    marca("leitura")
    st = stems.obter(caminho, sinal, dispositivo)
    marca("stems")

    mix = au.mono(sinal)
    bateria = au.mono(st["drums"])
    cache = _caminho_cache(caminho)
    salvo = None
    if usar_cache and cache.exists():
        salvo = json.loads(cache.read_text(encoding="utf-8"))
        if salvo.get("versao") != VERSAO_ANALISE:
            salvo = None

    if salvo:
        grade = Grade.de_dict(salvo["grade"])
        info = salvo["info"]
        voz = np.asarray(salvo["voz"])
        rms_mix = np.asarray(salvo["rms_mix"])
        rms_bat = np.asarray(salvo["rms_bateria"])
        marca("cache")
    else:
        batidas, primeiros = detectar_batidas(mix, SR, dispositivo)
        marca("batidas")
        grade = ajustar_grade(batidas, primeiros, len(mix) / SR, envelope_ataques(bateria, SR))
        marca("grade")
        voz = cp.voz(au.mono(st["vocals"]), mix, grade, SR)
        rms_mix = cp.rms_db(mix, grade, SR)
        rms_bat = cp.rms_db(bateria, grade, SR)
        marca("compassos")
        harmonico = au.mono(st["bass"] + st["other"] + 0.5 * st["vocals"])
        tonalidade = tom.estimar(harmonico, SR)
        marca("tom")
        estilos, emb = estilo.estimar(mix, SR)
        if emb is not None:
            pasta_emb = pasta_cache() / "impressoes"
            pasta_emb.mkdir(parents=True, exist_ok=True)
            np.save(pasta_emb / f"{stems.chave_arquivo(caminho)}.npy", emb.astype(np.float32))
        marca("estilo")
        info = {"tom": tonalidade, "estilos": estilos}

    validos = cp.completos(grade, SR, len(mix))
    entrada, saida, primeiro_som = _limites_musica(grade, mix, rms_mix, rms_bat, validos)

    if not salvo:
        com_batida = validos & (rms_bat > np.median(rms_bat[validos]) - 12)
        info["ritmo"] = ritmo.estimar(bateria, grade, SR, com_batida)
        marca("ritmo")
        tags = au.ler_tags(caminho)
        info.update({
            "arquivo": caminho.name,
            "titulo": tags.get("title", ""),
            "artista": tags.get("artist", ""),
            "duracao": round(len(mix) / SR, 2),
        })
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({
            "versao": VERSAO_ANALISE,
            "grade": grade.para_dict(),
            "info": info,
            "voz": [round(float(x), 3) for x in voz],
            "rms_mix": [round(float(x), 2) for x in rms_mix],
            "rms_bateria": [round(float(x), 2) for x in rms_bat],
        }, ensure_ascii=False), encoding="utf-8")

    com_voz = np.flatnonzero((voz > 0.3) & (np.arange(len(voz)) >= entrada))
    info["entrada_s"] = round(grade.compassos[entrada], 3)
    info["primeiro_som_s"] = round(primeiro_som, 3)
    info["saida_s"] = round(grade.fim_compasso(saida - 1), 3)
    info["voz_compasso"] = int(com_voz[0] - entrada + 1) if len(com_voz) else None
    info["voz_s"] = round(grade.compassos[com_voz[0]], 2) if len(com_voz) else None
    info["compassos_musica"] = int(saida - entrada)

    return Faixa(
        caminho=caminho, audio=sinal, stems=st, grade=grade, info=info, voz=voz,
        rms_mix=rms_mix, rms_bateria=rms_bat, validos=validos, entrada=entrada, saida=saida,
        primeiro_som=primeiro_som, tempos=tempos,
    )
