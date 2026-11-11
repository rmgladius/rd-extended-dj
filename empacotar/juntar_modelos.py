"""Junta os três modelos numa pasta, para irem dentro do programa (funciona sem internet).

    python empacotar/juntar_modelos.py build/modelos

Usa o que já foi baixado pelas bibliotecas (cache do torch e do Hugging Face) e só
baixa o que faltar. Estrutura gerada:

    beat_this-final0.ckpt
    demucs/htdemucs.yaml
    demucs/<assinatura>.safetensors
    discogs-effnet-bsdynamic-1.onnx
    discogs-effnet-bsdynamic-1.json
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


def main() -> int:
    destino = Path(sys.argv[1] if len(sys.argv) > 1 else "build/modelos")
    destino.mkdir(parents=True, exist_ok=True)

    # beat_this: o torch.hub guarda em <hub>/checkpoints/beat_this-final0.ckpt
    import torch
    from beat_this.inference import load_checkpoint

    ckpt = Path(torch.hub.get_dir()) / "checkpoints" / "beat_this-final0.ckpt"
    if not ckpt.exists():
        load_checkpoint("final0")
    shutil.copy2(ckpt, destino / ckpt.name)
    print("beat_this:", ckpt)

    # Demucs (htdemucs) do Hugging Face: o yaml lista as assinaturas dos pesos
    import yaml
    from huggingface_hub import hf_hub_download

    pasta_demucs = destino / "demucs"
    pasta_demucs.mkdir(exist_ok=True)
    yml = Path(hf_hub_download("adefossez/HTDemucs", "htdemucs.yaml"))
    shutil.copy2(yml, pasta_demucs / "htdemucs.yaml")  # copy2 segue o link simbólico do cache
    for sig in yaml.safe_load(yml.read_text(encoding="utf-8"))["models"]:
        pesos = Path(hf_hub_download("adefossez/HTDemucs", f"{sig}.safetensors"))
        shutil.copy2(pesos, pasta_demucs / f"{sig}.safetensors")
        print("demucs:", pesos)

    # Discogs-EffNet: o extdj baixa para a própria pasta de cache
    from extdj import estilo

    for nome in (estilo.ARQ_MODELO, estilo.ARQ_META):
        origem = estilo._baixar(nome)
        shutil.copy2(origem, destino / nome)
        print("estilo:", origem)

    total = sum(a.stat().st_size for a in destino.rglob("*") if a.is_file())
    print(f"pronto: {destino} ({total / 2**20:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
