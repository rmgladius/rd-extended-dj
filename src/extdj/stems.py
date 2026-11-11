"""Separação em bateria, baixo, voz e resto (Demucs), com cache em disco."""

from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import Callable
from pathlib import Path

import numpy as np
import soundfile as sf

from .config import SR, modelo_embutido, pasta_cache

NOMES = ("drums", "bass", "other", "vocals")
MODELO = "htdemucs"

# Cada música ocupa uns 140 MB de stems. Passando disso, as usadas há mais tempo saem
# do cache (só custa separar de novo, se a música voltar).
LIMITE_CACHE_GB = float(os.environ.get("EXTDJ_LIMITE_CACHE_GB", "15"))

Progresso = Callable[[float], None]

_separador = None


def chave_arquivo(caminho: Path) -> str:
    """Identifica a música pelo conteúdo do começo, do fim e pelo tamanho (renomear não invalida)."""
    tam = caminho.stat().st_size
    h = hashlib.sha1(str(tam).encode())
    with open(caminho, "rb") as f:
        h.update(f.read(1 << 20))
        if tam > 2 << 20:
            f.seek(-(1 << 20), 2)
            h.update(f.read(1 << 20))
    return h.hexdigest()[:16]


def _novo_separador(dispositivo: str):
    from demucs.api import Separator

    pasta = modelo_embutido("demucs")
    if pasta is None or not (pasta / f"{MODELO}.yaml").exists():
        return Separator(model=MODELO, device=dispositivo, progress=False)

    class SeparadorLocal(Separator):
        """O mesmo modelo do Hugging Face, lido da pasta do programa (sem internet)."""

        def _load_model(self):
            import yaml
            from demucs.apply import BagOfModels
            from demucs.hf import load_safetensors_model

            saco = yaml.safe_load((pasta / f"{MODELO}.yaml").read_text(encoding="utf-8"))
            modelos = [load_safetensors_model(str(pasta / f"{sig}.safetensors")) for sig in saco["models"]]
            self._model = BagOfModels(modelos, saco.get("weights"), saco.get("segment"))
            self._model.eval()
            self._audio_channels = self._model.audio_channels
            self._samplerate = self._model.samplerate

    return SeparadorLocal(model=MODELO, device=dispositivo, progress=False)


def _separar(audio: np.ndarray, dispositivo: str, progresso: Progresso | None = None) -> dict[str, np.ndarray]:
    global _separador
    import torch

    if _separador is None:
        _separador = _novo_separador(dispositivo)

    def avisar(d: dict) -> None:
        if d.get("state") == "end" and d.get("audio_length"):
            progresso(min(1.0, (d["segment_offset"] + 1) / d["audio_length"]))

    _separador.update_parameter(callback=avisar if progresso else None)
    wav = torch.from_numpy(np.ascontiguousarray(audio.T))
    _, saida = _separador.separate_tensor(wav, SR)
    return {nome: saida[nome].cpu().numpy().T.astype(np.float32) for nome in NOMES}


def pasta_stems() -> Path:
    return pasta_cache() / "stems"


def _pasta_da_musica(caminho: Path) -> Path:
    return pasta_stems() / f"{chave_arquivo(caminho)}-{MODELO}"


def tem_cache(caminho: Path) -> bool:
    pasta = _pasta_da_musica(caminho)
    return all((pasta / f"{nome}.flac").exists() for nome in NOMES)


def obter(caminho: Path, audio: np.ndarray, dispositivo: str,
          progresso: Progresso | None = None) -> dict[str, np.ndarray]:
    """Stems da música, lendo do cache quando já foram separados."""
    pasta = _pasta_da_musica(caminho)
    arquivos = {nome: pasta / f"{nome}.flac" for nome in NOMES}
    if all(a.exists() for a in arquivos.values()):
        stems = {nome: sf.read(a, dtype="float32", always_2d=True)[0] for nome, a in arquivos.items()}
        os.utime(pasta)  # usada agora: vai para o fim da fila de limpeza
        n = len(audio)
        return {k: _ajustar_tamanho(v, n) for k, v in stems.items()}
    # o corte em ±1 vale para a memória também, para a 1ª e a 2ª execução darem o mesmo resultado
    stems = {k: np.clip(v, -1, 1) for k, v in _separar(audio, dispositivo, progresso).items()}
    pasta.mkdir(parents=True, exist_ok=True)
    for nome, dados in stems.items():
        sf.write(arquivos[nome], dados, SR, subtype="PCM_24")
    limpar_cache(manter=pasta)
    return stems


def tamanho_cache() -> int:
    raiz = pasta_stems()
    return sum(a.stat().st_size for a in raiz.rglob("*.flac")) if raiz.exists() else 0


def limpar_cache(limite_gb: float = LIMITE_CACHE_GB, manter: Path | None = None) -> int:
    """Apaga os stems usados há mais tempo até o cache caber no limite. Devolve os bytes liberados."""
    raiz = pasta_stems()
    if not raiz.exists():
        return 0
    pastas = []
    for p in raiz.iterdir():
        if p.is_dir():
            pastas.append((p.stat().st_mtime, sum(a.stat().st_size for a in p.glob("*.flac")), p))
    total = sum(t for _, t, _ in pastas)
    limite = limite_gb * 1024 ** 3
    liberado = 0
    for _, tam, p in sorted(pastas, key=lambda x: x[0]):
        if total <= limite:
            break
        if manter is not None and p == manter:
            continue
        shutil.rmtree(p, ignore_errors=True)
        total -= tam
        liberado += tam
    return liberado


def _ajustar_tamanho(x: np.ndarray, n: int) -> np.ndarray:
    if len(x) >= n:
        return x[:n]
    return np.vstack([x, np.zeros((n - len(x), x.shape[1]), dtype=x.dtype)])
