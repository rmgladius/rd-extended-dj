"""Desenha o ícone do programa (empacotar/icone.ico): cinco barras de forma de onda.

    uv run --with pillow python empacotar/gerar_icone.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

FUNDO = (15, 17, 20, 255)
ACENTO = (45, 212, 191, 255)
ALTURAS = (0.30, 0.58, 0.86, 0.50, 0.24)   # mesmo desenho do logo da janela


def desenhar(lado: int = 1024) -> Image.Image:
    img = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, lado - 1, lado - 1), radius=int(lado * 0.22), fill=FUNDO)
    largura = lado * 0.095
    vao = lado * 0.06
    total = 5 * largura + 4 * vao
    x = (lado - total) / 2
    for h in ALTURAS:
        alt = lado * h * 0.82
        y0 = (lado - alt) / 2
        d.rounded_rectangle((x, y0, x + largura, y0 + alt), radius=largura / 2, fill=ACENTO)
        x += largura + vao
    return img


if __name__ == "__main__":
    destino = Path(__file__).with_name("icone.ico")
    desenhar().save(destino, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(destino)
