# extended-dj

Cria versões extended de músicas para mixar em beat match: um intro e um outro em loop,
do tamanho que você escolher, encaixados na grade de batidas da música original.

Para cada música, o programa:

1. detecta o BPM e o início de cada compasso;
2. separa bateria, baixo, voz e o resto (Demucs);
3. mede o tom (notação tradicional e Camelot), o estilo e o padrão da batida;
4. procura o trecho que repete melhor, sem voz e com batida firme;
5. monta `intro em loop + música original + outro em loop` e grava com as tags.

## Instalação

Precisa do [uv](https://docs.astral.sh/uv/) e do ffmpeg no PATH.

```bash
uv sync
```

No WSL, deixe o ambiente fora do disco do Windows (o PyTorch fica muito lento em `/mnt`):

```bash
export UV_PROJECT_ENVIRONMENT=$HOME/.venvs/extended-dj
```

O atalho `./extdj` já faz isso. A placa NVIDIA é usada quando existe; sem ela, roda no
processador (mais lento na separação). No Mac com chip M, usa a GPU do Mac.

Na primeira execução são baixados três modelos: Demucs (80 MB), beat_this e
Discogs-EffNet (18 MB, de um servidor lento: pode levar alguns minutos).

## Programa com janela

No Windows, o `Extended DJ.exe` (veja [Gerar o .exe](#gerar-o-exe)) abre direto. O caminho é:

1. arraste as músicas (ou uma pasta) para a janela, ou clique em **Adicionar**;
2. cada música é analisada na hora: BPM, tom em Camelot, estilo, batida e onde a voz entra;
3. ajuste o intro e o outro: tamanho, loop de quantos compassos e o que toca (camadas,
   música completa, instrumental, só bateria, bateria e baixo);
4. arraste os quadros coloridos na onda da original para escolher de onde sai cada loop;
5. ouça a prévia do extended (os botões **Ouvir entrada** e **Ouvir saída** pulam para as emendas);
6. **Gerar extended** grava na pasta escolhida, em WAV, AIFF, FLAC ou MP3 320.
   **Gerar todas** faz a lista inteira, cada uma com os próprios ajustes.

Fora do .exe, a mesma tela abre com `uv run extdj-app`. No WSL não há janela: use
`./extdj-app`, que abre no navegador do Windows.

Os instrumentos separados ficam guardados (uns 140 MB por música), para a música abrir
na hora da segunda vez. Acima de 15 GB os mais antigos saem sozinhos; o **limpar** no topo
da janela apaga os das músicas que não estão abertas.

## Linha de comando

```bash
# planilha com BPM, tom, estilo, batida e onde a voz entra
./extdj analisar "/caminho/da/pasta"

# extended com intro e outro de 32 compassos, loop de 4 (o padrão)
./extdj estender "/caminho/da/pasta"

# intro de 64, sem outro, loop de 8, em MP3 320
./extdj estender musica.mp3 --intro 64 --outro 0 --loop 8 --formato mp3
```

Os arquivos vão para `saida/`, com " (Extended)" no nome e no título. Ao lado de cada
um fica um `.extdj.json` com BPM, posição do primeiro tempo e onde cada parte começa.

### Opções do `estender`

| Opção | O que faz |
|---|---|
| `--intro N` / `--outro N` | compassos adicionados no começo / no fim (0 desliga) |
| `--loop N` | compassos do trecho que se repete: 1, 2, 4, 8 ou 16 |
| `--modo` | de onde vem o loop (tabela abaixo) |
| `--modo-outro` | modo diferente só para o outro |
| `--inicio-intro K` / `--inicio-outro K` | força o loop a começar no compasso K da grade |
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

## Como funciona

- **Grade:** batidas pelo [beat_this](https://github.com/CPJKU/beat_this). Quando o
  detector alterna entre andamento cheio e meio-tempo (comum em trap e pop), a grade
  fica no andamento rápido até 155 BPM. O BPM é refinado pelo ataque da bateria
  isolada: se a fase escorrega ao longo da música, o BPM é corrigido (0,01 BPM de erro
  já dá 15 ms no fim de uma faixa de 4 minutos).
- **Andamento variável:** música com baterista ao vivo é detectada. O loop sai do
  trecho vizinho ao intro ou ao outro, no andamento local.
- **Emendas:** cada loop é recortado em compassos inteiros e encostado no ataque da
  bateria do próprio trecho. A emenda dura 3 ms e termina antes do tempo forte. As
  posições são acumuladas em ponto flutuante, então a grade não escorrega.
- **Anacruse e rabo:** se a música começa antes do primeiro tempo (uma voz puxando a
  frase), esse começo toca por cima do fim do intro. O fade e o reverb do final tocam
  por cima do começo do outro.
- **Tom:** croma sem a bateria, comparado com os perfis de Krumhansl, Temperley e EDMA
  (Faraldo et al., 2016, feito para música eletrônica).
- **Estilo:** [Discogs-EffNet](https://essentia.upf.edu/models.html), 400 estilos do
  Discogs. Não tem funk brasileiro; para isso virão os estilos aprendidos por exemplo.
- **Tags:** título, artista, álbum e afins são copiados, além da capa no MP3. Grade e
  cue points do Traktor e do Serato no arquivo original não são copiados, porque
  estariam errados no extended.

## Gerar o .exe

Roda no Windows (o PyInstaller não gera .exe a partir do Linux):

1. coloque um ffmpeg "shared" em `build\ffmpeg` (`ffmpeg.exe`, `ffprobe.exe` e as DLLs `av*` e `sw*`),
   por exemplo de [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) ou do
   [BtbN](https://github.com/BtbN/FFmpeg-Builds/releases);
2. rode `empacotar\construir.bat`. Ele instala o ambiente em `build\venv-win`, junta os modelos
   em `build\modelos` (ou use `empacotar/juntar_modelos.py` num ambiente que já os tenha
   baixado) e chama o PyInstaller.

Sai em `build\dist\Extended DJ\`: a pasta inteira é o programa (o .exe precisa das pastas ao
lado). Com o PyTorch com CUDA dentro, ela tem uns 5 GB e funciona em qualquer Windows 10 ou
11 de 64 bits; com placa NVIDIA usa a placa, sem ela usa o processador (a separação de uma
música de 3 minutos leva perto de 80 s em vez de 8 s).

Para conferir um pacote sem abrir a janela:

```bat
"Extended DJ.exe" --teste musica.mp3 --saida-teste C:\pasta
```

O resultado vai para `%LOCALAPPDATA%\extdj\cache\extdj.log`.

## Testes

```bash
uv run pytest
```

## Créditos e licenças

- beat_this, CPJKU (MIT)
- Demucs, Alexandre Défossez / Meta (MIT)
- Discogs-EffNet, MTG / Universitat Pompeu Fabra (CC BY-NC-SA 4.0, uso sem fins comerciais)
- pywebview (BSD) e WebView2 da Microsoft, para a janela
- FFmpeg (LGPL ou GPL, conforme o build usado no .exe)
