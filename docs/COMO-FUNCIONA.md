# Como funciona

Notas para quem vai mexer no código. A apresentação do programa está no [README](../README.md).

Para cada música, o programa:

1. detecta o BPM e o início de cada compasso;
2. separa bateria, baixo, voz e o resto (Demucs);
3. mede o tom (notação tradicional e Camelot), o estilo e o padrão da batida;
4. procura o trecho que repete melhor, sem voz e com batida firme;
5. monta `intro em loop + música original + outro em loop` e grava com as tags.

## Rodar o código

Precisa do [uv](https://docs.astral.sh/uv/) e do ffmpeg no PATH.

```bash
uv sync
uv run extdj-app        # a janela
uv run pytest           # testes
```

No WSL, deixe o ambiente fora do disco do Windows (o PyTorch fica muito lento em `/mnt`):

```bash
export UV_PROJECT_ENVIRONMENT=$HOME/.venvs/extended-dj
```

Os atalhos `./extdj` e `./extdj-app` já fazem isso. No WSL não há janela: `./extdj-app` abre a mesma
tela no navegador do Windows. A placa NVIDIA é usada quando existe; sem ela, roda no processador (mais
lento na separação). No Mac com chip M, usa a GPU do Mac.

Na primeira execução são baixados três modelos: Demucs (80 MB), beat_this e Discogs-EffNet (18 MB, de
um servidor lento: pode levar alguns minutos).

## Estrutura

| Arquivo | O que faz |
|---|---|
| `src/extdj/analise.py` | junta tudo da análise de uma música, com cache em disco |
| `src/extdj/grade.py` | batidas, BPM e primeiro tempo de cada compasso |
| `src/extdj/stems.py` | separação pelo Demucs e cache dos instrumentos |
| `src/extdj/tom.py`, `estilo.py`, `ritmo.py` | tom em Camelot, estilo e padrão da batida |
| `src/extdj/extender.py` | escolha dos loops e montagem do extended |
| `src/extdj/exportar.py`, `audio.py` | gravação em WAV, AIFF, FLAC ou MP3 com as tags |
| `src/extdj/cli.py` | linha de comando |
| `src/extdj/pix.py` | código e QR do Pix do botão Apoiar (BR Code do Banco Central) |
| `src/extdj/app/` | janela: servidor local (`servidor.py`, `sessao.py`), pywebview (`janela.py`) e a página em `ui/` |
| `empacotar/` | receita do PyInstaller e o `construir.bat` |
| `docs/fonte/` | geradores das imagens do README |

## Janela

A janela é uma página HTML sem etapa de build (`src/extdj/app/ui`), servida por um servidor HTTP
local que só escuta em 127.0.0.1 e exige um código gerado a cada abertura. No Windows ela abre pelo
pywebview (WebView2); os links com `target="_blank"` vão para o navegador padrão.

Os instrumentos separados ficam guardados (uns 140 MB por música), para a música abrir na hora da
segunda vez. Acima de 15 GB os mais antigos saem sozinhos; o **limpar** no topo da janela apaga os das
músicas que não estão abertas. A pasta é `%LOCALAPPDATA%\extdj\cache` no Windows e `~/.cache/extdj`
no Linux (ou `EXTDJ_CACHE`).

### Mixagem

Sem mixagem, o extended é `intro + música + outro`, um depois do outro. Com **Por cima**, o bloco entra
na música em compassos inteiros: os últimos compassos do intro tocam junto com os primeiros da música,
e os primeiros do outro junto com os últimos dela. O tamanho do bloco não muda, então o extended fica
mais curto. Cada compasso do loop sobreposto é encaixado no compasso da música por baixo e no ataque da
bateria dela, para os dois bumbos baterem juntos.

O **Fader** muda o volume do loop aos poucos, como a mão no fader do mixer:

- **Baixar** vai de 100% a 0% e **Subir** de 0% a 100%;
- a rampa ocupa os compassos por cima da música (sem sobreposição, o bloco inteiro);
- ao pôr o bloco por cima da música pela primeira vez, o fader já liga no sentido da mixagem: o intro
  baixa enquanto a música entra e o outro sobe enquanto ela acaba;
- na onda do extended a rampa é a linha branca. Os dois pontos podem ser arrastados, de tempo em tempo
  na horizontal e de 5 em 5% na vertical. **voltar ao automático** desfaz.

O nível segue a curva de um fader de mixer (no meio do caminho o loop está 12 dB abaixo). Música e loop
juntos passam do volume máximo, então enquanto tocam juntos o volume da mixagem baixa devagar (em uns
0,6 s) e volta conforme o loop sai, sem cortar bumbo a bumbo.

## Linha de comando

```bash
# planilha com BPM, tom, estilo, batida e onde a voz entra
./extdj analisar "/caminho/da/pasta"

# extended com intro e outro de 32 compassos, loop de 4 (o padrão)
./extdj estender "/caminho/da/pasta"

# intro de 64, sem outro, loop de 8, em MP3 320
./extdj estender musica.mp3 --intro 64 --outro 0 --loop 8 --formato mp3
```

Os arquivos vão para `saida/`, com " (Extended)" no nome e no título. Ao lado de cada um fica um
`.extdj.json` com BPM, posição do primeiro tempo e onde cada parte começa.

### Opções do `estender`

| Opção | O que faz |
|---|---|
| `--intro N` / `--outro N` | compassos adicionados no começo / no fim (0 desliga) |
| `--loop N` | compassos do trecho que se repete: 1, 2, 4, 8 ou 16 |
| `--modo` | de onde vem o loop (tabela abaixo) |
| `--modo-outro` | modo diferente só para o outro |
| `--inicio-intro K` / `--inicio-outro K` | força o loop a começar no compasso K da grade |
| `--sobre-intro N` / `--sobre-outro N` | compassos do intro (ou do outro) tocando por cima da música |
| `--fader-intro` / `--fader-outro` | `baixar` ou `subir` o loop aos poucos (veja [Mixagem](#mixagem)) |
| `--formato` | `wav` (padrão), `aiff`, `flac` ou `mp3` |
| `--saida PASTA` | pasta de destino |

### Modos

| Modo | Loop feito com |
|---|---|
| `auto` | música completa, se houver um trecho limpo sem voz; senão, em camadas |
| `completo` | a música como ela é |
| `instrumental` | tudo menos a voz |
| `batida` | só a bateria |
| `batida_baixo` | bateria e baixo |
| `camadas` | intro que vai crescendo: bateria na primeira metade, bateria e baixo, depois instrumental (em 32 compassos: 16 + 8 + 8). O outro faz o caminho inverso |

## Análise

- **Grade:** batidas pelo [beat_this](https://github.com/CPJKU/beat_this). Quando o detector alterna
  entre andamento cheio e meio-tempo (comum em trap e pop), a grade fica no andamento rápido até
  155 BPM. O BPM é refinado pelo ataque da bateria isolada: se a fase escorrega ao longo da música, o
  BPM é corrigido (0,01 BPM de erro já dá 15 ms no fim de uma faixa de 4 minutos).
- **Contratempo:** em alguns trechos o detector marca o "e" de cada tempo (acontece no funk, em que o
  tamborzão bate forte no contratempo). Esses trechos ficam fora da conta, senão cada um somaria uma
  batida e a grade sairia com o BPM errado e o primeiro tempo fora do lugar.
- **Andamento variável:** música com baterista ao vivo é detectada. O loop sai do trecho vizinho ao
  intro ou ao outro, no andamento local.
- **Emendas:** cada loop é recortado em compassos inteiros e encostado no ataque da bateria do próprio
  trecho. A emenda dura 3 ms e termina antes do tempo forte. As posições são acumuladas em ponto
  flutuante, então a grade não escorrega.
- **Anacruse e rabo:** se a música começa antes do primeiro tempo (uma voz puxando a frase), esse
  começo toca por cima do fim do intro. A música vai até o último compasso com batida até o fim; o que
  vem depois (pancada final, fade, reverb) toca por cima do começo do outro sem a bateria e o baixo,
  que ali vêm do loop.
- **Tom:** croma sem a bateria, comparado com os perfis de Krumhansl, Temperley e EDMA (Faraldo et al.,
  2016, feito para música eletrônica).
- **Estilo:** [Discogs-EffNet](https://essentia.upf.edu/models.html), 400 estilos do Discogs. Não tem
  funk brasileiro.
- **Tags:** título, artista, álbum e afins são copiados, além da capa no MP3. Grade e cue points do
  Traktor e do Serato no arquivo original não são copiados, porque estariam errados no extended.

## Gerar o .exe

Roda no Windows (o PyInstaller não gera .exe a partir do Linux):

1. coloque um ffmpeg "shared" em `build\ffmpeg` (`ffmpeg.exe`, `ffprobe.exe` e as DLLs `av*` e `sw*`),
   por exemplo de [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) ou do
   [BtbN](https://github.com/BtbN/FFmpeg-Builds/releases);
2. rode `empacotar\construir.bat leve` ou `empacotar\construir.bat`. Ele instala o ambiente, junta os
   modelos em `build\modelos` (ou use `empacotar/juntar_modelos.py` num ambiente que já os tenha
   baixado) e chama o PyInstaller.

| | `construir.bat leve` | `construir.bat` |
|---|---|---|
| PyTorch | sem CUDA, do PyPI | com CUDA 12.8 |
| Pasta | `build\dist-leve\RD Extended DJ\` | `build\dist\RD Extended DJ\` |
| Tamanho | 1,3 GB (565 MB em .zip) | uns 5 GB |
| Separação de 3 min de música | perto de 80 s | perto de 8 s com placa NVIDIA |

A pasta inteira é o programa (o .exe precisa das pastas ao lado). A versão publicada no GitHub é a
leve, porque o GitHub aceita arquivos de até 2 GB por download. As duas funcionam em qualquer Windows
10 ou 11 de 64 bits.

Para conferir um pacote sem abrir a janela:

```bat
"RD Extended DJ.exe" --teste musica.mp3 --saida-teste C:\pasta
```

O resultado vai para `%LOCALAPPDATA%\extdj\cache\extdj.log`.

## Publicar uma versão

1. suba a versão em `pyproject.toml` e em `src/extdj/__init__.py` e rode `uv lock`;
2. gere a versão leve (`empacotar\construir.bat leve`);
3. no WSL, `./empacotar/publicar.sh "o que mudou"` compacta a pasta em
   `build/release/RD-Extended-DJ-Windows.zip` e cria a release `v<versão>` no GitHub com o .zip.

O botão de download do README aponta para `releases/latest/download/RD-Extended-DJ-Windows.zip`, então
o nome do arquivo precisa continuar o mesmo.

## Imagens do README

As imagens saem do próprio programa, com cinco músicas de nome e artista fictícios nas tags
(`ffmpeg -i original.mp3 -map 0:a:0 -c copy -map_metadata -1 -metadata title=... -metadata artist=... nova.mp3`).

1. suba o programa com um cache vazio, para a animação mostrar a análise:
   `EXTDJ_CACHE=/tmp/cache-demo uv run extdj-app --sem-abrir --porta 8766`;
2. `CAPTURAS=/tmp/capturas MUSICAS=/pasta/das/musicas node docs/fonte/captura/demo.cjs 8766` grava os
   quadros da animação e `node docs/fonte/captura/paradas.cjs 8766` as imagens paradas (precisa do
   Playwright com o Chromium e das fontes Segoe UI do Windows; no WSL elas são lidas de
   `/mnt/c/Windows/Fonts`);
3. `python3 docs/fonte/montar.py /tmp/capturas docs/imagens` monta `capa.png`, `demo.webp`,
   `leitura.png`, `ajustes.png` e `mixagem.png`. O `extended.svg` é escrito à mão.

## Créditos e licenças

- beat_this, CPJKU (MIT)
- Demucs, Alexandre Défossez / Meta (MIT)
- Discogs-EffNet, MTG / Universitat Pompeu Fabra (CC BY-NC-SA 4.0, uso sem fins comerciais)
- pywebview (BSD) e WebView2 da Microsoft, para a janela
- segno (BSD), para o QR do Pix
- FFmpeg (LGPL ou GPL, conforme o build usado no .exe)
