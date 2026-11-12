"""Linha de comando: `extdj analisar` e `extdj estender`."""

from __future__ import annotations

import argparse
import csv
import sys
import time
import warnings
from pathlib import Path

from . import audio as au
from .config import dispositivo

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)


def _num(x: float | None, casas: int = 2) -> str:
    """Número com vírgula, para o Excel em português abrir certo."""
    if x is None:
        return ""
    return f"{x:.{casas}f}".replace(".", ",")


def _resumo(info: dict, grade) -> str:
    tom = info["tom"]
    estilo = info["estilos"][0]["estilo"] if info.get("estilos") else "?"
    bpm = f"{_num(grade.bpm)} BPM"
    if grade.variavel:
        bpm += f" (varia {_num(grade.bpm_min, 1)} a {_num(grade.bpm_max, 1)})"
    voz = f"voz no compasso {info['voz_compasso']}" if info.get("voz_compasso") else "sem voz"
    return f"{bpm} | {tom['tom']} ({tom['camelot']}) | {info['ritmo']['padrao']} | {estilo} | {voz}"


def cmd_analisar(args) -> int:
    from .analise import analisar

    arquivos = au.listar(args.entradas)
    if not arquivos:
        print("Nenhuma música encontrada.", file=sys.stderr)
        return 1
    disp = dispositivo()
    print(f"{len(arquivos)} música(s), processando em {disp}.")
    saida = Path(args.saida)
    saida.mkdir(parents=True, exist_ok=True)
    linhas = []
    for i, arq in enumerate(arquivos, 1):
        t = time.perf_counter()
        try:
            f = analisar(arq, disp, usar_cache=not args.sem_cache)
        except Exception as e:  # uma música ruim não para o lote
            print(f"[{i}/{len(arquivos)}] {arq.name}: ERRO {e}")
            continue
        dt = time.perf_counter() - t
        info, g = f.info, f.grade
        print(f"[{i}/{len(arquivos)}] {arq.name}  {_resumo(info, g)}  ({dt:.0f} s)")
        est = info.get("estilos", []) + [{}] * 3
        linhas.append({
            "arquivo": arq.name,
            "artista": info.get("artista", ""),
            "titulo": info.get("titulo", ""),
            "duracao_s": _num(info["duracao"], 1),
            "bpm": _num(g.bpm, 2),
            "andamento": "variável" if g.variavel else "fixo",
            "bpm_min": _num(g.bpm_min, 1),
            "bpm_max": _num(g.bpm_max, 1),
            "confianca_grade": _num(g.confianca, 2),
            "tom": info["tom"]["tom"],
            "camelot": info["tom"]["camelot"],
            "tom_pt": info["tom"]["tom_pt"],
            "confianca_tom": _num(info["tom"]["confianca"], 2),
            "tom_alternativo": info["tom"]["alternativa"],
            "estilo_1": est[0].get("estilo", ""),
            "estilo_2": est[1].get("estilo", ""),
            "estilo_3": est[2].get("estilo", ""),
            "batida": info["ritmo"]["padrao"],
            "primeiro_compasso_s": _num(info["entrada_s"], 3),
            "voz_entra_compasso": info.get("voz_compasso") or "",
            "voz_entra_s": _num(info.get("voz_s")),
            "compassos_musica": info["compassos_musica"],
            "tempo_s": _num(dt, 1),
        })
    if linhas:
        destino = saida / "analise.csv"
        with open(destino, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=list(linhas[0]), delimiter=";")
            w.writeheader()
            w.writerows(linhas)
        print(f"Planilha: {destino}")
    return 0


def cmd_estender(args) -> int:
    from dataclasses import replace

    from .analise import analisar
    from .exportar import gravar
    from .extender import NOMES_MODO, Fontes, escolher, montar

    arquivos = au.listar(args.entradas)
    if not arquivos:
        print("Nenhuma música encontrada.", file=sys.stderr)
        return 1
    disp = dispositivo()
    saida = Path(args.saida)
    print(f"{len(arquivos)} música(s), intro {args.intro} e outro {args.outro} compassos, "
          f"loop de {args.loop}, processando em {disp}.")
    erros = 0
    for i, arq in enumerate(arquivos, 1):
        t = time.perf_counter()
        try:
            f = analisar(arq, disp, usar_cache=not args.sem_cache)
            fontes = Fontes(f)
            intro = outro = None
            if args.intro > 0:
                intro = escolher(f, fontes, "intro", args.intro, args.loop, args.modo, args.inicio_intro)
                intro = replace(intro, sobrepor=args.sobre_intro, fader=args.fader_intro or "sem")
            if args.outro > 0:
                outro = escolher(f, fontes, "outro", args.outro, args.loop,
                                 args.modo_outro or args.modo, args.inicio_outro)
                outro = replace(outro, sobrepor=args.sobre_outro, fader=args.fader_outro or "sem")
            sinal, meta = montar(f, fontes, intro, outro)
            destino = gravar(f, sinal, meta, intro, outro, saida, args.formato)
        except Exception as e:
            erros += 1
            print(f"[{i}/{len(arquivos)}] {arq.name}: ERRO {e}")
            if args.detalhes:
                raise
            continue
        dt = time.perf_counter() - t
        partes = []
        for e in (intro, outro):
            if e:
                partes.append(f"{e.lado}: {NOMES_MODO[e.modo]}, loop no compasso {e.inicio - f.entrada + 1} "
                              f"(nota {_num(e.nota)})")
        print(f"[{i}/{len(arquivos)}] {arq.name}  {_num(f.grade.bpm)} BPM | " + " | ".join(partes)
              + f"  ({dt:.0f} s)")
        print(f"        {destino}")
    return 1 if erros else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="extdj", description="Cria intro e outro em loop para mixar.")
    sub = p.add_subparsers(dest="comando", required=True)

    a = sub.add_parser("analisar", help="BPM, grade, tom, estilo e voz de cada música")
    a.add_argument("entradas", nargs="+", help="arquivos ou pastas")
    a.add_argument("--saida", default="saida", help="pasta da planilha (padrão: saida)")
    a.add_argument("--sem-cache", action="store_true", help="refaz a análise do zero")
    a.set_defaults(func=cmd_analisar)

    e = sub.add_parser("estender", help="gera a versão extended")
    e.add_argument("entradas", nargs="+", help="arquivos ou pastas")
    e.add_argument("--intro", type=int, default=32, help="compassos de intro (0 = sem intro)")
    e.add_argument("--outro", type=int, default=32, help="compassos de outro (0 = sem outro)")
    e.add_argument("--loop", type=int, default=4, choices=(1, 2, 4, 8, 16), help="compassos do trecho que repete")
    e.add_argument("--modo", default="auto", choices=("auto", "completo", "instrumental", "batida",
                                                      "batida_baixo", "camadas"))
    e.add_argument("--modo-outro", choices=("auto", "completo", "instrumental", "batida",
                                           "batida_baixo", "camadas"), help="modo diferente para o outro")
    e.add_argument("--inicio-intro", type=int, help="força o loop do intro a começar neste índice de compasso")
    e.add_argument("--inicio-outro", type=int, help="força o loop do outro a começar neste índice de compasso")
    e.add_argument("--sobre-intro", type=int, default=0,
                   help="compassos do fim do intro tocando por cima do começo da música")
    e.add_argument("--sobre-outro", type=int, default=0,
                   help="compassos do começo do outro tocando por cima do fim da música")
    e.add_argument("--fader-intro", choices=("baixar", "subir"), help="volume do loop do intro mudando aos poucos")
    e.add_argument("--fader-outro", choices=("baixar", "subir"), help="volume do loop do outro mudando aos poucos")
    e.add_argument("--formato", default="wav", choices=au.FORMATOS)
    e.add_argument("--saida", default="saida", help="pasta de saída (padrão: saida)")
    e.add_argument("--sem-cache", action="store_true", help="refaz a análise do zero")
    e.add_argument("--detalhes", action="store_true", help="mostra o erro completo")
    e.set_defaults(func=cmd_estender)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
