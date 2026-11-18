"""Servidor HTTP local que liga a interface (HTML) ao motor de áudio.

Só escuta em 127.0.0.1 e exige um código gerado a cada abertura, para outra página
aberta no navegador não conseguir mandar comandos para o programa.
"""

from __future__ import annotations

import json
import mimetypes
import re
import secrets
import sys
import threading
import traceback
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .. import __version__, pix
from .sessao import OpcoesInvalidas, Sessao

PASTA_UI = Path(__file__).resolve().parent / "ui"
BLOCO = 256 * 1024
TIPOS = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac", ".flac": "audio/flac",
         ".wav": "audio/wav", ".ogg": "audio/ogg", ".opus": "audio/ogg", ".js": "text/javascript",
         ".css": "text/css", ".html": "text/html", ".svg": "image/svg+xml", ".png": "image/png"}


class Erro(Exception):
    def __init__(self, status: int, mensagem: str):
        super().__init__(mensagem)
        self.status = status


class Servidor(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, sessao: Sessao, porta: int = 0, nativo: object | None = None):
        super().__init__(("127.0.0.1", porta), Manipulador)
        self.sessao = sessao
        self.token = secrets.token_urlsafe(18)
        self.nativo = nativo     # funções da janela (escolher arquivos e pastas), se houver

    @property
    def endereco(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/"

    def em_segundo_plano(self) -> threading.Thread:
        t = threading.Thread(target=self.serve_forever, name="servidor", daemon=True)
        t.start()
        return t


class Manipulador(BaseHTTPRequestHandler):
    server: Servidor
    protocol_version = "HTTP/1.1"

    def log_message(self, formato: str, *args) -> None:  # silencioso
        pass

    # ------------------------------------------------------------ utilidades

    def _json(self, dados, status: int = 200) -> None:
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def _corpo(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except ValueError as e:
            raise Erro(400, "Pedido inválido.") from e

    def _conferir(self, query: dict) -> None:
        token = self.headers.get("X-Token") or (query.get("t") or [""])[0]
        if not secrets.compare_digest(token, self.server.token):
            raise Erro(403, "Acesso recusado.")

    def _arquivo(self, caminho: Path, tipo: str | None = None) -> None:
        """Manda um arquivo com suporte a Range (o player precisa para pular na música)."""
        if not caminho.is_file():
            raise Erro(404, "Arquivo não encontrado.")
        tamanho = caminho.stat().st_size
        tipo = tipo or TIPOS.get(caminho.suffix.lower()) or mimetypes.guess_type(caminho.name)[0] \
            or "application/octet-stream"
        ini, fim = 0, tamanho - 1
        faixa = self.headers.get("Range")
        parcial = False
        if faixa:
            m = re.match(r"bytes=(\d*)-(\d*)", faixa)
            if m:
                a, b = m.groups()
                if a:
                    ini = int(a)
                    fim = int(b) if b else tamanho - 1
                elif b:
                    ini = max(0, tamanho - int(b))
                fim = min(fim, tamanho - 1)
                if ini > fim:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{tamanho}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                parcial = True
        self.send_response(206 if parcial else 200)
        self.send_header("Content-Type", tipo)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(fim - ini + 1))
        if parcial:
            self.send_header("Content-Range", f"bytes {ini}-{fim}/{tamanho}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with open(caminho, "rb") as fh:
            fh.seek(ini)
            restante = fim - ini + 1
            while restante > 0:
                bloco = fh.read(min(BLOCO, restante))
                if not bloco:
                    break
                self.wfile.write(bloco)
                restante -= len(bloco)

    # ------------------------------------------------------------ rotas

    def do_GET(self) -> None:
        self._tratar("GET")

    def do_POST(self) -> None:
        self._tratar("POST")

    def _tratar(self, metodo: str) -> None:
        url = urlparse(self.path)
        caminho = unquote(url.path)
        query = parse_qs(url.query)
        try:
            # outro site que aponte o próprio nome para 127.0.0.1 não passa daqui
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            if host not in ("127.0.0.1", "localhost"):
                raise Erro(403, "Acesso recusado.")
            if metodo == "GET" and caminho in ("/", "/index.html"):
                return self._pagina()
            if metodo == "GET" and caminho.startswith("/ui/"):
                return self._estatico(caminho[4:])
            self._conferir(query)
            if caminho.startswith("/audio/"):
                return self._audio(caminho, query)
            if caminho.startswith("/api/"):
                return self._api(metodo, caminho[5:], query)
            raise Erro(404, "Página não encontrada.")
        except Erro as e:
            self._json({"erro": str(e)}, e.status)
        except OpcoesInvalidas as e:
            self._json({"erro": str(e)}, 400)
        except KeyError:
            self._json({"erro": "Música não encontrada."}, 404)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # o player cancela pedidos o tempo todo ao pular na música
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            try:
                self._json({"erro": f"Erro interno: {e}"}, 500)
            except OSError:
                pass

    def _pagina(self) -> None:
        html = (PASTA_UI / "index.html").read_text(encoding="utf-8")
        html = (
            html.replace("__TOKEN__", self.server.token)
            .replace("__VERSAO__", __version__)
            .replace("__PIX_QR__", pix.qr_do_projeto())
            .replace("__PIX_CODIGO__", escape(pix.codigo_do_projeto()))
            .replace("__PIX_CHAVE__", escape(pix.CHAVE))
        )
        corpo = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def _estatico(self, nome: str) -> None:
        alvo = (PASTA_UI / nome).resolve()
        if PASTA_UI not in alvo.parents:
            raise Erro(404, "Arquivo não encontrado.")
        self._arquivo(alvo)

    def _audio(self, caminho: str, query: dict) -> None:
        partes = caminho.strip("/").split("/")   # audio/<id>/original | audio/<id>/previa
        if len(partes) != 3:
            raise Erro(404, "Áudio não encontrado.")
        _, mid, qual = partes
        s = self.server.sessao
        if qual == "original":
            return self._arquivo(s.audio_original(mid))
        if qual == "previa":
            versao = (query.get("v") or [""])[0]
            if not re.fullmatch(r"[0-9a-f]{8}", versao):
                raise Erro(404, "Prévia não encontrada.")
            return self._arquivo(s.arquivo_previa(mid, versao), "audio/wav")
        raise Erro(404, "Áudio não encontrado.")

    def _api(self, metodo: str, rota: str, query: dict) -> None:
        s = self.server.sessao
        partes = rota.strip("/").split("/")

        if metodo == "GET" and rota == "estado":
            return self._json(s.estado())

        if metodo == "POST" and rota == "adicionar":
            corpo = self._corpo()
            caminhos = [c for c in corpo.get("caminhos", []) if isinstance(c, str)]
            try:
                return self._json({"ids": s.adicionar(caminhos)})
            except FileNotFoundError as e:
                raise Erro(400, str(e)) from e

        if metodo == "POST" and rota == "enviar":
            nome = unquote((query.get("nome") or [""])[0])
            tamanho = int(self.headers.get("Content-Length") or 0)
            if tamanho <= 0:
                raise Erro(400, "Arquivo vazio.")

            def blocos():
                restante = tamanho
                while restante > 0:
                    b = self.rfile.read(min(BLOCO, restante))
                    if not b:
                        return
                    restante -= len(b)
                    yield b

            return self._json({"id": s.receber(nome, blocos(), tamanho)})

        if metodo == "POST" and rota == "config":
            return self._json(s.atualizar_config(self._corpo()))

        if metodo == "POST" and rota == "limpar-cache":
            return self._json({"liberado_mb": round(s.limpar_cache() / 2 ** 20)})

        if metodo == "POST" and rota == "gerar-todas":
            corpo = self._corpo()
            formato = corpo.get("formato") or s.config.formato
            pasta = corpo.get("pasta") or s.config.pasta_saida
            feitas = 0
            for item in corpo.get("itens", []):
                try:
                    s.exportar(item["id"], item.get("opcoes") or {}, formato, pasta)
                    feitas += 1
                except (OpcoesInvalidas, KeyError):
                    continue
            return self._json({"na_fila": feitas})

        if metodo == "POST" and rota in ("escolher-arquivos", "escolher-pasta", "abrir-pasta"):
            return self._nativo(rota, self._corpo())

        if len(partes) >= 2 and partes[0] == "musica":
            mid = partes[1]
            acao = partes[2] if len(partes) > 2 else ""
            if metodo == "GET" and acao == "":
                m = s.musica(mid)
                return self._json({**m.para_lista(), "detalhes": m.detalhes})
            if metodo == "GET" and acao == "onda":
                return self._arquivo(s.onda_original(mid), "application/json")
            if metodo == "POST" and acao == "previa":
                corpo = self._corpo()
                r = s.previa(mid, corpo.get("opcoes") or {}, int(corpo.get("seq") or 0))
                return self._json(r if r is not None else {"superada": True})
            if metodo == "POST" and acao == "gerar":
                corpo = self._corpo()
                s.exportar(mid, corpo.get("opcoes") or {}, corpo.get("formato") or s.config.formato,
                           corpo.get("pasta") or s.config.pasta_saida)
                return self._json({"ok": True})
            if metodo == "POST" and acao == "remover":
                s.remover(mid)
                return self._json({"ok": True})
        raise Erro(404, "Rota desconhecida.")

    def _nativo(self, rota: str, corpo: dict) -> None:
        n = self.server.nativo
        s = self.server.sessao
        if rota == "abrir-pasta":
            from .janela import abrir_no_explorador

            abrir_no_explorador(corpo.get("caminho") or s.config.pasta_saida)
            return self._json({"ok": True})
        if n is None:
            raise Erro(501, "Disponível só no programa instalado.")
        if rota == "escolher-arquivos":
            caminhos = n.escolher_arquivos()
            ids = s.adicionar(caminhos) if caminhos else []
            return self._json({"ids": ids})
        if rota == "escolher-pasta":
            pasta = n.escolher_pasta(s.config.pasta_saida)
            if pasta:
                s.atualizar_config({"pasta_saida": pasta})
            return self._json({"pasta": pasta or ""})
        raise Erro(404, "Rota desconhecida.")
