"""Leitura e gravação de áudio pelo ffmpeg (MP3, FLAC, WAV, AIFF, M4A...)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np

from .config import SR

FORMATOS = ("wav", "aiff", "flac", "mp3")
TAGS_COPIADAS = {
    "title", "artist", "album", "album_artist", "genre", "date", "composer", "publisher",
    "track", "disc", "label", "isrc", "copyright", "lyricist", "remixer", "grouping",
}
EXTENSOES_AUDIO = {".mp3", ".flac", ".wav", ".aif", ".aiff", ".m4a", ".aac", ".ogg", ".opus", ".wma"}


def _exe(nome: str) -> str:
    env = os.environ.get("EXTDJ_" + nome.upper())
    exe = env or shutil.which(nome)
    if not exe:
        raise RuntimeError(f"{nome} não encontrado. Instale o ffmpeg e deixe no PATH.")
    return exe


def carregar(caminho: Path | str, sr: int = SR) -> np.ndarray:
    """Decodifica para float32 estéreo, formato (amostras, 2)."""
    cmd = [
        _exe("ffmpeg"), "-v", "error", "-nostdin", "-i", str(caminho),
        "-map", "0:a:0", "-ac", "2", "-ar", str(sr), "-f", "f32le", "-acodec", "pcm_f32le", "-",
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0 or not r.stdout:
        erro = r.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"Não consegui ler {caminho}: {erro}")
    return np.frombuffer(r.stdout, dtype="<f4").reshape(-1, 2).copy()


def ler_tags(caminho: Path | str) -> dict[str, str]:
    """Tags do arquivo com as chaves em minúsculas (title, artist, album...)."""
    cmd = [_exe("ffprobe"), "-v", "error", "-show_entries", "format_tags", "-of", "json", str(caminho)]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        return {}
    try:
        tags = json.loads(r.stdout).get("format", {}).get("tags", {})
    except json.JSONDecodeError:
        return {}
    return {k.lower(): str(v) for k, v in tags.items()}


def salvar(
    caminho: Path,
    audio: np.ndarray,
    sr: int = SR,
    formato: str = "wav",
    origem: Path | None = None,
    tags: dict[str, str] | None = None,
) -> None:
    """Grava pelo ffmpeg, copiando as tags (e a capa, no MP3) do arquivo de origem."""
    if formato not in FORMATOS:
        raise ValueError(f"Formato desconhecido: {formato}")
    caminho.parent.mkdir(parents=True, exist_ok=True)
    cmd = [_exe("ffmpeg"), "-v", "error", "-nostdin", "-y",
           "-f", "f32le", "-ar", str(sr), "-ac", "2", "-i", "-"]
    # Só as tags de informação passam. Grade e cue points do Traktor (PRIV TRAKTOR4),
    # do Serato (GEOB) e afins ficam de fora: são do arquivo original e estariam
    # errados no extended, que é mais longo.
    finais = {k: v for k, v in (ler_tags(origem) if origem else {}).items() if k in TAGS_COPIADAS}
    finais.update(tags or {})
    capa = origem is not None and formato == "mp3"
    if capa:
        cmd += ["-i", str(origem)]
    cmd += ["-map", "0:a", "-map_metadata", "-1"]
    if capa:
        cmd += ["-map", "1:v?", "-c:v", "copy", "-disposition:v:0", "attached_pic"]
    for chave, valor in finais.items():
        cmd += ["-metadata", f"{chave}={valor}"]
    if formato == "wav":
        cmd += ["-af", "aresample=dither_method=triangular", "-c:a", "pcm_s16le"]
    elif formato == "aiff":
        cmd += ["-af", "aresample=dither_method=triangular", "-c:a", "pcm_s16be", "-write_id3v2", "1"]
    elif formato == "flac":
        cmd += ["-af", "aresample=dither_method=triangular", "-c:a", "flac", "-sample_fmt", "s16"]
    elif formato == "mp3":
        cmd += ["-c:a", "libmp3lame", "-b:a", "320k", "-id3v2_version", "3"]
    cmd.append(str(caminho))
    dados = np.ascontiguousarray(audio, dtype="<f4").tobytes()
    r = subprocess.run(cmd, input=dados, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"Não consegui gravar {caminho}: {r.stderr.decode(errors='replace').strip()}")


def mono(audio: np.ndarray) -> np.ndarray:
    return audio.mean(axis=1) if audio.ndim == 2 else audio


def listar(entradas: list[str]) -> list[Path]:
    """Expande arquivos e pastas (sem recursão profunda) em uma lista de músicas."""
    arquivos: list[Path] = []
    for entrada in entradas:
        p = Path(entrada)
        if p.is_dir():
            arquivos += sorted(x for x in p.rglob("*") if x.suffix.lower() in EXTENSOES_AUDIO)
        elif p.is_file():
            arquivos.append(p)
        else:
            raise FileNotFoundError(f"Não encontrei: {entrada}")
    return arquivos
