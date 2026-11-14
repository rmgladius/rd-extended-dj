// Imagens paradas do README, em escala 2: janela inteira e recortes de cada parte.
const { abrir, CAPTURAS } = require('./base.cjs');
const path = require('path');
const fs = require('fs');
const PASTA = path.join(CAPTURAS, 'paradas');
fs.mkdirSync(PASTA, { recursive: true });

(async () => {
  const p = await abrir({ porta: Number(process.argv[2] || 8769), largura: 1440, altura: 1000, escala: 2 });
  const esperarPrevia = async () => {
    await p.waitForTimeout(250);
    await p.waitForFunction(() => document.getElementById('x-carregando').hidden, null, { timeout: 30000 });
    await p.waitForTimeout(300);
  };
  await (await p.$$('.item'))[0].click();
  await esperarPrevia();

  // estado conhecido: tamanho 32, nada por cima, outro no automático
  for (const lado of ['intro', 'outro']) {
    await p.click(`.lado[data-lado="${lado}"] .seg[data-campo="compassos"] button[data-v="32"]`);
    await esperarPrevia();
    const auto = await p.$(`.lado[data-lado="${lado}"] [data-acao="auto"]`);
    if (auto) { await auto.click(); await esperarPrevia(); }
    for (let i = 0; i < 10; i++) {
      const v = Number(await p.textContent(`.lado[data-lado="${lado}"] .passo-valor`));
      if (v === 0) break;
      await p.click(`.lado[data-lado="${lado}"] .passo button[data-passo="-1"]`);
      await esperarPrevia();
    }
  }
  // loop do outro num trecho mais para o fim (os dois começam no mesmo lugar)
  const onda = await p.locator('#onda-original').boundingBox();
  const regiao = await p.evaluate(() => {
    const c = document.getElementById('onda-original');
    const g = c.getContext('2d');
    const k = c.width / c.getBoundingClientRect().width;
    const linha = g.getImageData(0, Math.round(36 * k), c.width, 1).data;
    let ini = -1, fim = -1;
    for (let x = 0; x < c.width; x++) {
      const [r, gg, b] = linha.slice(x * 4, x * 4 + 3);
      if (gg > 150 && r < 120 && b > 120) { if (ini < 0) ini = x; fim = x; }
    }
    return (ini + fim) / 2 / k;
  });
  await p.mouse.move(onda.x + regiao, onda.y + 70);
  await p.mouse.down();
  await p.mouse.move(onda.x + onda.width * 0.79, onda.y + 70, { steps: 12 });
  await p.mouse.up();
  await esperarPrevia();

  // intro e outro dois compassos por cima da música (o fader liga sozinho)
  for (const sel of ['.lado[data-lado="intro"] .passo button[data-passo="1"]', '.lado[data-lado="outro"] .passo button[data-passo="1"]']) {
    await p.click(sel); await p.waitForTimeout(150); await p.click(sel);
    await esperarPrevia();
  }
  await p.evaluate(() => { document.getElementById('cursor-falso').style.display = 'none'; });
  await p.mouse.move(5, 995);
  await p.evaluate(() => { document.getElementById('cursor-falso').style.display = 'none'; });
  await p.waitForTimeout(300);

  await p.screenshot({ path: path.join(PASTA, 'janela.png') });
  const caixa = async (sels, folga = 0) => {
    const bs = [];
    for (const s of sels) bs.push(await p.locator(s).first().boundingBox());
    const x0 = Math.min(...bs.map((b) => b.x)) - folga, y0 = Math.min(...bs.map((b) => b.y)) - folga;
    const x1 = Math.max(...bs.map((b) => b.x + b.width)) + folga, y1 = Math.max(...bs.map((b) => b.y + b.height)) + folga;
    return { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
  };
  await p.screenshot({ path: path.join(PASTA, 'leitura.png'), clip: await caixa(['.cab-musica', '#m-conteudo > .painel:first-child'], 10) });
  await p.screenshot({ path: path.join(PASTA, 'ajustes.png'), clip: await caixa(['.lados'], 10) });
  await p.screenshot({ path: path.join(PASTA, 'mixagem.png'), clip: await caixa(['#m-conteudo > .painel:last-child'], 10) });
  await p.screenshot({ path: path.join(PASTA, 'lista.png'), clip: await caixa(['.lateral'], 0) });
  console.log('erros', p.erros);
  await p.fechar();
})().catch((e) => { console.error(e); process.exit(1); });
