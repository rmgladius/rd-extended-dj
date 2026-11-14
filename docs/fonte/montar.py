"""Monta as imagens do README a partir das capturas da janela (veja docs/fonte/captura).

Uso: python3 docs/fonte/montar.py <pasta das capturas> docs/imagens

A pasta das capturas tem `quadros/` (quadros.txt + PNGs da animação, em escala 1) e
`paradas/` (janela.png, leitura.png, ajustes.png e mixagem.png, em escala 2).
Gera demo.webp, capa.png (topo do README e prévia do GitHub, 1280x640), leitura.png,
ajustes.png e mixagem.png. Precisa das fontes Segoe UI do Windows (lidas de C:\\Windows\\Fonts).
"""
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

capturas = Path(sys.argv[1])
destino = Path(sys.argv[2])
destino.mkdir(parents=True, exist_ok=True)
icone_ico = Path(__file__).resolve().parents[2] / "empacotar/icone.ico"

FONTES = Path("/mnt/c/Windows/Fonts")
FUNDO = (15, 17, 20)
TOPO = (12, 14, 17)
BORDA = (53, 59, 69)
TEXTO = (231, 234, 238)
SUAVE = (163, 171, 183)
ACENTO = (45, 212, 191)
ROSA = (244, 114, 182)
NOME = "RD Extended DJ"


def fonte(nome, tam):
    return ImageFont.truetype(str(FONTES / nome), tam)


def cantos(img, raio):
    mascara = Image.new("L", img.size, 0)
    ImageDraw.Draw(mascara).rounded_rectangle([0, 0, img.width - 1, img.height - 1], raio, fill=255)
    saida = img.convert("RGBA")
    saida.putalpha(ImageChops.multiply(saida.getchannel("A"), mascara))
    return saida


def sombra(tam, raio, desfoque, opacidade):
    """Sombra (RGBA) do tamanho `tam`, para ficar atrás de um retângulo arredondado."""
    s = Image.new("L", (tam[0] + desfoque * 4, tam[1] + desfoque * 4), 0)
    ImageDraw.Draw(s).rounded_rectangle([desfoque * 2, desfoque * 2, desfoque * 2 + tam[0], desfoque * 2 + tam[1]],
                                        raio, fill=int(255 * opacidade))
    s = s.filter(ImageFilter.GaussianBlur(desfoque))
    preto = Image.new("RGBA", s.size, (0, 0, 0, 0))
    preto.putalpha(s)
    return preto


def icone(lado):
    ico = Image.open(icone_ico)
    maior = max(ico.info["sizes"])
    ico.size = maior
    return ico.convert("RGBA").resize((lado, lado), Image.LANCZOS)


def barra_de_titulo(largura, e):
    """Barra de título do Windows 11 (janela maximizada), no tom do topo do programa."""
    h = 32 * e
    barra = Image.new("RGBA", (largura, h), TOPO + (255,))
    d = ImageDraw.Draw(barra)
    barra.alpha_composite(icone(16 * e), (12 * e, 8 * e))
    d.text((38 * e, 16 * e), NOME, font=fonte("segoeui.ttf", 12 * e), fill=(200, 204, 212), anchor="lm")
    glifos = fonte("SegoeIcons.ttf", 10 * e)
    for i, glifo in enumerate(("\uE8BB", "\uE923", "\uE921")):  # fechar, restaurar, minimizar
        d.text((largura - (23 + 46 * i) * e, 16 * e), glifo, font=glifos, fill=(220, 222, 228), anchor="mm")
    ImageDraw.Draw(barra).line([0, h - 1, largura, h - 1], fill=(30, 34, 40), width=1)
    return barra


def janela(quadro, e):
    """Quadro + barra de título, cantos de 8 px e borda fina, como o Windows 11 desenha."""
    quadro = quadro.convert("RGBA")
    barra = barra_de_titulo(quadro.width, e)
    j = Image.new("RGBA", (quadro.width, quadro.height + barra.height), FUNDO + (255,))
    j.alpha_composite(barra, (0, 0))
    j.alpha_composite(quadro, (0, barra.height))
    j = cantos(j, 8 * e)
    ImageDraw.Draw(j).rounded_rectangle([0, 0, j.width - 1, j.height - 1], 8 * e, outline=BORDA + (255,), width=e)
    return j


# ── Animação: a análise é acelerada (um quadro em cada três) e a janela ganha sombra
pasta_q = capturas / "quadros"
linhas = [l.split() for l in (pasta_q / "quadros.txt").read_text().splitlines() if l.strip()]
quadros, n_analise = [], 0
for nome, ms, marca in linhas:
    if marca == "analise":
        n_analise += 1
        if n_analise > 1 and n_analise % 3:
            continue
        ms = "700" if n_analise == 1 else "230"
    quadros.append((nome, int(ms)))

LARGURA_DEMO = 1200
margem = 40
amostra = janela(Image.open(pasta_q / f"{quadros[0][0]}.png"), 1)
tam_janela = (LARGURA_DEMO, round(amostra.height * LARGURA_DEMO / amostra.width))
base = Image.new("RGBA", (tam_janela[0] + 2 * margem, tam_janela[1] + 2 * margem), (0, 0, 0, 0))
base.alpha_composite(sombra(tam_janela, 10, 20, 0.55), (margem - 40, margem - 40 + 10))
imagens, duracoes = [], []
for nome, ms in quadros:
    q = base.copy()
    q.alpha_composite(janela(Image.open(pasta_q / f"{nome}.png"), 1).resize(tam_janela, Image.LANCZOS), (margem, margem))
    imagens.append(q)
    duracoes.append(ms)
imagens[0].save(destino / "demo.webp", save_all=True, append_images=imagens[1:], duration=duracoes,
                loop=0, quality=82, method=4)

# ── Recortes das seções: cantos arredondados, largura de 2x a coluna do README
pasta_p = capturas / "paradas"
for nome in ("leitura", "ajustes", "mixagem"):
    img = Image.open(pasta_p / f"{nome}.png").convert("RGBA")
    img = img.resize((1760, round(img.height * 1760 / img.width)), Image.LANCZOS)
    cantos(img, 20).save(destino / f"{nome}.png", optimize=True)

# ── Capa (1280x640, desenhada em 2x e reduzida)
K = 2
W, H = 1280 * K, 640 * K
capa = Image.new("RGBA", (W, H), FUNDO + (255,))
brilho = Image.new("RGBA", (W, H), (0, 0, 0, 0))
d = ImageDraw.Draw(brilho)
d.ellipse([-500 * K, 260 * K, 520 * K, 1100 * K], fill=ACENTO + (46,))
d.ellipse([820 * K, -520 * K, 1700 * K, 260 * K], fill=ROSA + (30,))
capa.alpha_composite(brilho.filter(ImageFilter.GaussianBlur(170 * K)))

# janela do programa à direita, saindo pela borda
j = janela(Image.open(pasta_p / "janela.png"), 2)
alt = 600 * K
j = j.resize((round(j.width * alt / j.height), alt), Image.LANCZOS)
xj, yj = 640 * K, 64 * K
capa.alpha_composite(sombra(j.size, 16 * K, 28 * K, 0.6), (xj - 56 * K, yj - 56 * K + 14 * K))
capa.alpha_composite(j, (xj, yj))

d = ImageDraw.Draw(capa)
x = 86 * K
lado = 56 * K
fundo_icone = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
ImageDraw.Draw(fundo_icone).rounded_rectangle([0, 0, lado - 1, lado - 1], 14 * K, fill=TOPO + (255,), outline=BORDA + (255,), width=K)
fundo_icone.alpha_composite(icone(40 * K), (8 * K, 8 * K))
capa.alpha_composite(fundo_icone, (x, 112 * K))
d.text((x + lado + 18 * K, 112 * K + lado // 2), NOME, font=fonte("seguisb.ttf", 36 * K), fill=TEXTO, anchor="lm")
titulo = fonte("seguibl.ttf", 60 * K)
d.text((x, 196 * K), "Qualquer música", font=titulo, fill=TEXTO)
d.text((x, 270 * K), "vira extended.", font=titulo, fill=ACENTO)
sub = fonte("segoeui.ttf", 21 * K)
for i, linha in enumerate(("Acha o BPM e o tom e monta um começo e um fim", "em loop, na batida da música, prontos para mixar.")):
    d.text((x, 384 * K + i * 31 * K), linha, font=sub, fill=SUAVE)
pilula = fonte("segoeui.ttf", 17 * K)
xp = x
for texto in ("Windows 10 e 11", "Grátis", "Funciona sem internet"):
    w = d.textlength(texto, font=pilula)
    d.rounded_rectangle([xp, 488 * K, xp + w + 36 * K, 524 * K], 18 * K, fill=(29, 33, 39, 255))
    d.text((xp + 18 * K, 506 * K), texto, font=pilula, fill=TEXTO, anchor="lm")
    xp += w + 36 * K + 12 * K
capa.convert("RGB").resize((1280, 640), Image.LANCZOS).save(destino / "capa.png", optimize=True)

for f in sorted(destino.iterdir()):
    print(f.name, f.stat().st_size // 1024, "KB")
