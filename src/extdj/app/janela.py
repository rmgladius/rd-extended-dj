"""Abre o programa: servidor local + janela com a interface.

    extdj-app                 abre a janela
    extdj-app --navegador     abre no navegador padrão (útil no WSL e para depurar)
    extdj-app --teste ARQ     analisa e gera um extended sem janela, para conferir o pacote
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from ..config import CONGELADO, pasta_cache

TITULO = "Extended DJ"


def _preparar_ambiente() -> None:
    """Ajustes para o programa empacotado rodar sem console e sem internet."""
    if sys.stdout is None or sys.stderr is None:
        # programa sem console: o que seria impresso vai para um arquivo de registro
        registro = open(pasta_cache() / "extdj.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
        sys.stdout = sys.stdout or registro
        sys.stderr = sys.stderr or registro
        print(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} ---", file=sys.stderr)
    # o librosa usa numba com cache em disco; a pasta do programa pode ser só leitura
    os.environ.setdefault("NUMBA_CACHE_DIR", str(pasta_cache() / "numba"))
    if CONGELADO:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
    import warnings

    warnings.filterwarnings("ignore", category=UserWarning)
    warnings.filterwarnings("ignore", category=FutureWarning)


def abrir_no_explorador(caminho: str) -> None:
    """Mostra o arquivo (selecionado) ou a pasta no gerenciador de arquivos."""
    p = Path(caminho)
    if sys.platform == "win32":
        if p.is_file():
            subprocess.Popen(["explorer", "/select,", str(p)])
        else:
            p.mkdir(parents=True, exist_ok=True)
            os.startfile(str(p))  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(p)] if p.is_file() else ["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p.parent if p.is_file() else p)])


def _abrir_navegador(url: str) -> None:
    """Navegador padrão; no WSL, o do Windows (o localhost do WSL chega até ele)."""
    import platform

    if sys.platform == "linux" and "microsoft" in platform.release().lower():
        try:
            subprocess.Popen(["cmd.exe", "/c", "start", "", url], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return
        except OSError:
            pass
    import webbrowser

    webbrowser.open(url)


class Nativo:
    """Funções da janela que o HTML sozinho não tem: caixas de diálogo do sistema."""

    def __init__(self) -> None:
        self.janela = None

    def escolher_arquivos(self) -> list[str]:
        import webview

        tipos = ("Áudio (*.mp3;*.flac;*.wav;*.aif;*.aiff;*.m4a;*.aac;*.ogg;*.opus;*.wma)",
                 "Todos os arquivos (*.*)")
        r = self.janela.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True, file_types=tipos)
        return list(r or [])

    def escolher_pasta(self, atual: str = "") -> str:
        import webview

        r = self.janela.create_file_dialog(webview.FileDialog.FOLDER, directory=atual or "")
        if not r:
            return ""
        return r[0] if isinstance(r, (list, tuple)) else str(r)


def _teste(arquivo: str, pasta: str) -> int:
    """Roda a análise e a geração sem janela (confere modelos, ffmpeg e GPU no pacote)."""
    from ..analise import analisar
    from ..config import dispositivo, nome_dispositivo
    from ..exportar import gravar
    from ..extender import Fontes, escolher, montar

    t0 = time.perf_counter()
    disp = dispositivo()
    print(f"dispositivo: {nome_dispositivo(disp)}", flush=True)
    ultimo = [""]

    def progresso(etapa: str, fracao: float) -> None:
        if etapa != ultimo[0]:
            ultimo[0] = etapa
            print(f"  {time.perf_counter() - t0:6.1f} s  {etapa}", flush=True)

    f = analisar(Path(arquivo), disp, usar_cache=False, progresso=progresso)
    print(f"BPM {f.grade.bpm:.2f} | {f.info['tom']['tom']} ({f.info['tom']['camelot']}) | "
          f"{f.info['ritmo']['padrao']} | {f.info['estilos'][0]['estilo']}", flush=True)
    fontes = Fontes(f)
    intro = escolher(f, fontes, "intro", 32, 4)
    outro = escolher(f, fontes, "outro", 32, 4)
    sinal, meta = montar(f, fontes, intro, outro)
    destino = gravar(f, sinal, meta, intro, outro, Path(pasta), "mp3", com_json=False)
    print(f"gerado: {destino} ({time.perf_counter() - t0:.1f} s no total)", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    import multiprocessing

    multiprocessing.freeze_support()
    _preparar_ambiente()
    p = argparse.ArgumentParser(prog="extdj-app", description="Extended DJ com janela")
    p.add_argument("--navegador", action="store_true", help="abre no navegador em vez da janela")
    p.add_argument("--porta", type=int, default=0, help="porta do servidor local (padrão: livre)")
    p.add_argument("--sem-abrir", action="store_true", help="só o servidor, sem abrir nada")
    p.add_argument("--teste", metavar="ARQUIVO", help="analisa e gera um extended sem janela")
    p.add_argument("--saida-teste", default=".", help="pasta do arquivo gerado no --teste")
    args = p.parse_args(argv)

    if args.teste:
        return _teste(args.teste, args.saida_teste)

    from .servidor import Servidor
    from .sessao import Sessao

    sessao = Sessao()
    usar_janela = not (args.navegador or args.sem_abrir)
    nativo = Nativo() if usar_janela else None
    srv = Servidor(sessao, args.porta, nativo)
    print(f"{TITULO} em {srv.endereco}?t={srv.token}", flush=True)

    if not usar_janela:
        if args.navegador:
            _abrir_navegador(srv.endereco)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
        return 0

    import webview

    srv.em_segundo_plano()
    # abre maximizada; o tamanho abaixo vale ao restaurar e precisa caber em notebook pequeno
    largura, altura = 1440, 900
    try:
        tela = webview.screens[0]
        largura, altura = min(largura, tela.width - 60), min(altura, tela.height - 90)
    except (IndexError, AttributeError):
        pass
    nativo.janela = webview.create_window(
        TITULO, srv.endereco, width=largura, height=altura,
        min_size=(min(1100, largura), min(680, altura)),
        background_color="#0f1114", text_select=False, maximized=True,
    )
    webview.start(private_mode=False, storage_path=str(pasta_cache() / "janela"))
    # fechou a janela: encerra mesmo que uma análise esteja no meio
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
