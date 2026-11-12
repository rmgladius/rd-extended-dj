"""Estado do programa: músicas abertas, fila de análise, prévias e exportação."""

from __future__ import annotations

import json
import math
import queue
import shutil
import threading
import time
import traceback
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

from .. import audio as au
from ..config import SR, pasta_cache
from . import forma

# o navegador da janela toca estes formatos direto do arquivo original
TOCA_DIRETO = {".mp3", ".wav", ".flac", ".ogg", ".opus", ".m4a", ".aac"}
FAIXAS_NA_MEMORIA = 2   # cada música aberta ocupa ~1 GB (áudio + stems)

LADO_PADRAO = {"compassos": 32, "loop": 4, "modo": "auto", "sobrepor": 0, "fader": "sem"}


def _pasta_musicas() -> Path:
    musica = Path.home() / "Music"
    return musica / "Extended" if musica.exists() else Path.home() / "Extended"


@dataclass
class Config:
    pasta_saida: str = field(default_factory=lambda: str(_pasta_musicas()))
    formato: str = "wav"
    intro: dict = field(default_factory=lambda: dict(LADO_PADRAO))
    outro: dict = field(default_factory=lambda: dict(LADO_PADRAO))

    @staticmethod
    def arquivo() -> Path:
        return pasta_cache() / "config.json"

    @classmethod
    def carregar(cls) -> Config:
        c = cls()
        try:
            dados = json.loads(cls.arquivo().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return c
        for k in ("pasta_saida", "formato"):
            if isinstance(dados.get(k), str):
                setattr(c, k, dados[k])
        for lado in ("intro", "outro"):
            if isinstance(dados.get(lado), dict):
                getattr(c, lado).update({k: v for k, v in dados[lado].items() if k in LADO_PADRAO})
        if c.formato not in au.FORMATOS:
            c.formato = "wav"
        return c

    def salvar(self) -> None:
        self.arquivo().write_text(json.dumps(self.__dict__, ensure_ascii=False, indent=2), encoding="utf-8")


@dataclass
class Musica:
    id: str
    caminho: Path
    nome: str
    enviada: bool = False          # cópia recebida pela janela (arrastar e soltar)
    estado: str = "na fila"        # na fila, analisando, pronta, erro
    etapa: str = ""
    progresso: float = 0.0
    erro: str = ""
    resumo: dict | None = None
    detalhes: dict | None = None
    exportando: bool = False
    exportado: str = ""
    erro_exportar: str = ""
    adicionada: float = field(default_factory=time.time)

    def para_lista(self) -> dict:
        return {
            "id": self.id, "nome": self.nome, "estado": self.estado, "etapa": self.etapa,
            "progresso": round(self.progresso, 3), "erro": self.erro, "resumo": self.resumo,
            "exportando": self.exportando, "exportado": self.exportado,
            "erro_exportar": self.erro_exportar,
        }


class OpcoesInvalidas(ValueError):
    pass


def _lado(dados: dict | None, nome: str):
    """Valida as opções de um lado (intro ou outro) vindas da tela."""
    from ..extender import FADERS, MODOS

    d = dict(LADO_PADRAO)
    d.update(dados or {})
    compassos, loop = int(d.get("compassos") or 0), int(d.get("loop") or 4)
    if compassos <= 0:
        return None
    if loop not in (1, 2, 4, 8, 16):
        raise OpcoesInvalidas(f"Loop do {nome} precisa ser 1, 2, 4, 8 ou 16 compassos.")
    if compassos % loop:
        raise OpcoesInvalidas(f"O {nome} de {compassos} compassos não fecha com loops de {loop}.")
    modo = d.get("modo") or "auto"
    if modo not in MODOS:
        raise OpcoesInvalidas(f"Modo desconhecido: {modo}")
    inicio = d.get("inicio")
    try:
        sobrepor = min(max(int(d.get("sobrepor") or 0), 0), compassos)
    except (TypeError, ValueError) as e:
        raise OpcoesInvalidas(f"Sobreposição do {nome} inválida.") from e
    fader = d.get("fader") or "sem"
    if fader not in FADERS:
        raise OpcoesInvalidas(f"Fader desconhecido: {fader}")
    pontos = d.get("fader_pontos")
    if pontos is not None:
        try:
            pontos = [[float(p), float(v)] for p, v in pontos]
        except (TypeError, ValueError) as e:
            raise OpcoesInvalidas(f"Pontos do fader do {nome} inválidos.") from e
        if len(pontos) != 2 or not all(math.isfinite(x) for par in pontos for x in par):
            pontos = None
    return {"compassos": compassos, "loop": loop, "modo": modo,
            "inicio": None if inicio is None else int(inicio),
            "sobrepor": sobrepor, "fader": fader, "fader_pontos": pontos}


class Sessao:
    def __init__(self) -> None:
        self.musicas: OrderedDict[str, Musica] = OrderedDict()
        self.trava = threading.RLock()
        self.config = Config.carregar()
        self.dispositivo: str | None = None
        self.nome_dispositivo = "carregando..."
        self._fila: queue.Queue[str] = queue.Queue()
        self._exportar: queue.Queue[tuple[str, dict, str, str]] = queue.Queue()
        self._faixas: OrderedDict[str, tuple] = OrderedDict()
        self._trava_faixas = threading.Lock()
        self._trava_montagem = threading.Lock()
        self._previas: dict[str, tuple[str, np.ndarray, dict, object, object]] = {}
        self._escolhas: dict[str, tuple[str, object, object]] = {}
        self._seq: dict[str, int] = {}
        self.pasta_envios = pasta_cache() / "enviadas"
        self.pasta_previas = pasta_cache() / "previas"
        self.pasta_ondas = pasta_cache() / "ondas"
        for p in (self.pasta_envios, self.pasta_previas):
            shutil.rmtree(p, ignore_errors=True)  # sobras da sessão anterior
            p.mkdir(parents=True, exist_ok=True)
        self.pasta_ondas.mkdir(parents=True, exist_ok=True)
        threading.Thread(target=self._analisador, name="analise", daemon=True).start()
        threading.Thread(target=self._exportador, name="exportar", daemon=True).start()

    # ------------------------------------------------------------ músicas

    def adicionar(self, caminhos: list[str], enviada: bool = False) -> list[str]:
        from ..stems import chave_arquivo

        ids = []
        for arq in au.listar(caminhos):
            try:
                chave = chave_arquivo(arq)
            except OSError:
                continue
            with self.trava:
                existente = self.musicas.get(chave)
                if existente is not None and existente.estado != "erro":
                    ids.append(chave)
                    continue
                # nova, ou uma que deu erro e foi adicionada de novo: vai (de volta) para a fila
                self.musicas[chave] = Musica(id=chave, caminho=arq, nome=arq.name, enviada=enviada)
            self._fila.put(chave)
            ids.append(chave)
        return ids

    def receber(self, nome: str, dados_iter, tamanho: int) -> str:
        """Grava uma música enviada pela janela (arrastar e soltar) e põe na fila."""
        nome = Path(nome).name or "musica"
        if Path(nome).suffix.lower() not in au.EXTENSOES_AUDIO:
            raise OpcoesInvalidas(f"{nome}: formato de áudio não suportado.")
        pasta = self.pasta_envios / uuid.uuid4().hex[:8]
        pasta.mkdir(parents=True)
        destino = pasta / nome
        with open(destino, "wb") as fh:
            restante = tamanho
            for bloco in dados_iter:
                fh.write(bloco)
                restante -= len(bloco)
        if restante > 0:
            shutil.rmtree(pasta, ignore_errors=True)
            raise OpcoesInvalidas("Envio incompleto.")
        mid = self.adicionar([str(destino)], enviada=True)[0]
        if self.musica(mid).caminho != destino:
            shutil.rmtree(pasta, ignore_errors=True)  # já estava na lista: a cópia sobra
        return mid

    def remover(self, mid: str) -> None:
        with self.trava:
            m = self.musicas.pop(mid, None)
        with self._trava_faixas:
            self._faixas.pop(mid, None)
        self._previas.pop(mid, None)
        self._escolhas.pop(mid, None)
        if m and m.enviada:
            shutil.rmtree(m.caminho.parent, ignore_errors=True)

    def lista(self) -> list[dict]:
        with self.trava:
            return [m.para_lista() for m in self.musicas.values()]

    def musica(self, mid: str) -> Musica:
        with self.trava:
            m = self.musicas.get(mid)
        if m is None:
            raise KeyError(mid)
        return m

    # ------------------------------------------------------------ análise

    def _preparar_dispositivo(self) -> None:
        if self.dispositivo is None:
            from ..config import dispositivo, nome_dispositivo

            self.dispositivo = dispositivo()
            self.nome_dispositivo = nome_dispositivo(self.dispositivo)

    def _analisador(self) -> None:
        try:
            self._preparar_dispositivo()
        except Exception as e:  # sem torch funcionando não há o que fazer, mas a janela avisa
            self.nome_dispositivo = f"erro: {e}"
        while True:
            mid = self._fila.get()
            try:
                m = self.musica(mid)
            except KeyError:
                continue
            m.estado, m.etapa, m.progresso = "analisando", "começando", 0.0
            try:
                self._analisar(m)
            except Exception as e:
                traceback.print_exc()
                m.estado, m.erro = "erro", str(e) or e.__class__.__name__

    def _analisar(self, m: Musica) -> None:
        from ..analise import analisar
        from ..extender import Fontes

        def progresso(etapa: str, fracao: float) -> None:
            m.etapa, m.progresso = etapa, fracao

        f = analisar(m.caminho, self.dispositivo, progresso=progresso)
        m.etapa = "desenhando a forma de onda"
        onda = self.pasta_ondas / f"{m.id}.json"
        if not onda.exists():
            onda.write_text(json.dumps(forma.calcular(f.audio)), encoding="utf-8")
        if m.caminho.suffix.lower() not in TOCA_DIRETO:
            import soundfile as sf

            sf.write(self.pasta_previas / f"{m.id}-original.wav", f.audio, SR, subtype="PCM_16")
        m.etapa = "preparando os loops"
        fontes = Fontes(f)
        for fonte in ("completo", "batida"):   # usadas no modo automático; ficam em disco
            fontes.impressoes(fonte)
        m.resumo = self._resumo(f)
        m.detalhes = self._detalhes(f)
        self._escolhas.pop(m.id, None)   # analisada de novo: a grade pode ter mudado
        with self._trava_faixas:
            # só ocupa a memória se houver lugar: não tira a música que está sendo editada
            if len(self._faixas) < FAIXAS_NA_MEMORIA:
                self._guardar_faixa(m.id, (f, fontes))
        m.estado, m.etapa, m.progresso = "pronta", "", 1.0

    @staticmethod
    def _resumo(f) -> dict:
        info, g = f.info, f.grade
        return {
            "titulo": info.get("titulo") or "", "artista": info.get("artista") or "",
            "duracao": info["duracao"], "bpm": round(g.bpm, 2), "variavel": g.variavel,
            "bpm_min": round(g.bpm_min, 1), "bpm_max": round(g.bpm_max, 1),
            "tom": info["tom"], "estilos": info.get("estilos", []), "batida": info["ritmo"]["padrao"],
            "voz_compasso": info.get("voz_compasso"), "voz_s": info.get("voz_s"),
            "compassos_musica": info["compassos_musica"],
        }

    @staticmethod
    def _detalhes(f) -> dict:
        g = f.grade
        cheio = f.validos & (f.rms_bateria > -60)
        ref = float(np.median(f.rms_bateria[cheio])) if cheio.any() else -20.0
        return {
            "compassos": [round(x, 4) for x in g.compassos],
            "periodo": g.periodo,
            "batidas_por_compasso": g.batidas_por_compasso,
            "entrada": f.entrada,
            "saida": f.saida,
            "voz": [round(float(x), 2) for x in f.voz],
            "bateria": [round(float(np.clip((x - ref + 18) / 18, 0, 1)), 2) for x in f.rms_bateria],
            "validos": [bool(x) for x in f.validos],
            "duracao": round(f.duracao, 3),
        }

    def _guardar_faixa(self, mid: str, par: tuple) -> None:
        self._faixas[mid] = par
        self._faixas.move_to_end(mid)
        while len(self._faixas) > FAIXAS_NA_MEMORIA:
            velho, _ = self._faixas.popitem(last=False)
            self._previas.pop(velho, None)

    def faixa(self, mid: str):
        """(Faixa, Fontes) da música, lendo do cache de análise quando não está na memória."""
        from ..analise import analisar
        from ..extender import Fontes

        m = self.musica(mid)
        if m.estado != "pronta":
            raise OpcoesInvalidas("A música ainda está sendo analisada.")
        with self._trava_faixas:
            par = self._faixas.get(mid)
            if par is not None:
                self._faixas.move_to_end(mid)
                return par
        from ..stems import tem_cache

        if not tem_cache(m.caminho):
            # os stems saíram do cache: separa de novo na fila, com progresso na tela
            m.estado, m.etapa, m.progresso = "na fila", "", 0.0
            self._fila.put(mid)
            raise OpcoesInvalidas("Os instrumentos separados saíram do cache. Analisando de novo.")
        f = analisar(m.caminho, self.dispositivo or "cpu")
        par = (f, Fontes(f))
        with self._trava_faixas:
            self._guardar_faixa(mid, par)
        return par

    def onda_original(self, mid: str) -> Path:
        return self.pasta_ondas / f"{mid}.json"

    def audio_original(self, mid: str) -> Path:
        m = self.musica(mid)
        if m.caminho.suffix.lower() in TOCA_DIRETO:
            return m.caminho
        return self.pasta_previas / f"{mid}-original.wav"

    # ------------------------------------------------------------ montagem

    def _montar(self, mid: str, opcoes: dict):
        """Monta o extended (ou reaproveita a última prévia com as mesmas opções)."""
        from ..extender import escolher, montar

        intro_op = _lado(opcoes.get("intro"), "intro")
        outro_op = _lado(opcoes.get("outro"), "outro")
        if not intro_op and not outro_op:
            raise OpcoesInvalidas("Escolha pelo menos um intro ou um outro.")
        chave = json.dumps([intro_op, outro_op], sort_keys=True)
        guardada = self._previas.get(mid)
        if guardada and guardada[0] == chave:
            return guardada[1:]
        f, fontes = self.faixa(mid)
        n = len(f.grade.compassos)
        for op in (intro_op, outro_op):
            if op and op["inicio"] is not None:
                op["inicio"] = int(np.clip(op["inicio"], 0, max(0, n - op["loop"])))

        # o loop escolhido só depende destas opções: mexer na sobreposição ou no fader
        # remonta o extended sem procurar o trecho de novo
        def do_loop(op):
            return op and {k: op[k] for k in ("compassos", "loop", "modo", "inicio")}

        chave_loop = json.dumps([do_loop(intro_op), do_loop(outro_op)], sort_keys=True)
        guardadas = self._escolhas.get(mid)
        if guardadas and guardadas[0] == chave_loop:
            intro, outro = guardadas[1:]
        else:
            try:
                intro = (escolher(f, fontes, "intro", intro_op["compassos"], intro_op["loop"], intro_op["modo"],
                                  intro_op["inicio"]) if intro_op else None)
                outro = (escolher(f, fontes, "outro", outro_op["compassos"], outro_op["loop"], outro_op["modo"],
                                  outro_op["inicio"]) if outro_op else None)
            except (RuntimeError, ValueError) as e:
                raise OpcoesInvalidas(str(e)) from e
            self._escolhas[mid] = (chave_loop, intro, outro)

        def mixagem(e, op):
            return e and replace(e, sobrepor=op["sobrepor"], fader=op["fader"], fader_pontos=op["fader_pontos"])

        intro, outro = mixagem(intro, intro_op), mixagem(outro, outro_op)
        sinal, meta = montar(f, fontes, intro, outro)
        self._previas[mid] = (chave, sinal, meta, intro, outro)
        return sinal, meta, intro, outro

    def previa(self, mid: str, opcoes: dict, seq: int) -> dict | None:
        """Monta a prévia e grava um WAV para a janela tocar. None se já pediram outra."""
        import soundfile as sf

        self._seq[mid] = max(self._seq.get(mid, 0), seq)
        with self._trava_montagem:
            if self._seq.get(mid, 0) > seq:
                return None
            sinal, meta, _, _ = self._montar(mid, opcoes)
            versao = uuid.uuid4().hex[:8]
            for velho in self.pasta_previas.glob(f"{mid}-previa-*.wav"):
                try:
                    velho.unlink()
                except OSError:
                    pass  # ainda tocando na janela; sai na próxima
            sf.write(self.pasta_previas / f"{mid}-previa-{versao}.wav", sinal, SR, subtype="PCM_16")
            onda = forma.calcular(sinal)
        g = self.faixa(mid)[0].grade
        return {
            "seq": seq,
            "versao": versao,
            "meta": meta,
            "intro": meta["intro"],
            "outro": meta["outro"],
            "onda": onda,
            "duracao": round(len(sinal) / SR, 3),
            "batidas_por_compasso": g.batidas_por_compasso,
            "periodo": g.periodo,
        }

    def arquivo_previa(self, mid: str, versao: str) -> Path:
        return self.pasta_previas / f"{mid}-previa-{versao}.wav"

    # ------------------------------------------------------------ exportação

    def exportar(self, mid: str, opcoes: dict, formato: str, pasta: str) -> None:
        if formato not in au.FORMATOS:
            raise OpcoesInvalidas(f"Formato desconhecido: {formato}")
        if not pasta:
            raise OpcoesInvalidas("Escolha a pasta onde salvar.")
        _lado(opcoes.get("intro"), "intro")
        _lado(opcoes.get("outro"), "outro")
        m = self.musica(mid)
        if m.estado != "pronta":
            raise OpcoesInvalidas(f"{m.nome} ainda não foi analisada.")
        m.exportando, m.erro_exportar = True, ""
        self._exportar.put((mid, opcoes, formato, pasta))

    def _exportador(self) -> None:
        from ..exportar import gravar

        while True:
            mid, opcoes, formato, pasta = self._exportar.get()
            try:
                m = self.musica(mid)
            except KeyError:
                continue
            try:
                with self._trava_montagem:
                    sinal, meta, intro, outro = self._montar(mid, opcoes)
                f = self.faixa(mid)[0]
                destino = gravar(f, sinal, meta, intro, outro, Path(pasta), formato, com_json=False)
                m.exportado = str(destino)
            except Exception as e:
                traceback.print_exc()
                m.erro_exportar = str(e) or e.__class__.__name__
            finally:
                m.exportando = False

    # ------------------------------------------------------------ outros

    def estado(self) -> dict:
        from ..stems import tamanho_cache

        return {
            "musicas": self.lista(),
            "config": self.config.__dict__,
            "dispositivo": self.nome_dispositivo,
            "cache_mb": round(tamanho_cache() / 2 ** 20),
            "fila": self._fila.qsize(),
        }

    def atualizar_config(self, dados: dict) -> dict:
        c = self.config
        if isinstance(dados.get("pasta_saida"), str) and dados["pasta_saida"].strip():
            c.pasta_saida = dados["pasta_saida"].strip()
        if dados.get("formato") in au.FORMATOS:
            c.formato = dados["formato"]
        for lado in ("intro", "outro"):
            if isinstance(dados.get(lado), dict):
                novo = {k: v for k, v in dados[lado].items() if k in LADO_PADRAO}
                getattr(c, lado).update(novo)
        c.salvar()
        return c.__dict__

    def limpar_cache(self) -> int:
        """Apaga os stems das músicas que não estão abertas. Devolve os bytes liberados."""
        from ..stems import MODELO, chave_arquivo, pasta_stems

        with self.trava:
            abertas = {f"{chave_arquivo(m.caminho)}-{MODELO}" for m in self.musicas.values()
                       if m.caminho.exists()}
        liberado = 0
        raiz = pasta_stems()
        if raiz.exists():
            for p in raiz.iterdir():
                if p.is_dir() and p.name not in abertas:
                    liberado += sum(a.stat().st_size for a in p.glob("*.flac"))
                    shutil.rmtree(p, ignore_errors=True)
        return liberado

