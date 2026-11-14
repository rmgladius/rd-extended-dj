// Grava os quadros da animação do README: cada quadro é um PNG + quanto tempo ele fica na tela.
const { abrir, CAPTURAS } = require('./base.cjs');
const fs = require('fs');
const path = require('path');

const PASTA = path.join(CAPTURAS, 'quadros');
// cinco músicas com nome e artista fictícios nas tags (veja docs/COMO-FUNCIONA.md)
const MUSICAS = process.env.MUSICAS;
fs.rmSync(PASTA, { recursive: true, force: true });
fs.mkdirSync(PASTA, { recursive: true });
const lista = [];
let n = 0;
let cursor = { x: 1300, y: 940 };

(async () => {
  const p = await abrir({ porta: Number(process.argv[2] || 8767), largura: 1440, altura: 1000, escala: 1 });
  const quadro = async (ms, marca = '-') => {
    const nome = String(n++).padStart(3, '0');
    await p.screenshot({ path: path.join(PASTA, nome + '.png') });
    lista.push(`${nome} ${ms} ${marca}`);
  };
  const mover = async (x, y, passos = 9) => {
    for (let i = 1; i <= passos; i++) {
      const t = i / passos;
      const s = t * t * (3 - 2 * t);
      await p.mouse.move(cursor.x + (x - cursor.x) * s, cursor.y + (y - cursor.y) * s);
      if (i % 2 === 1 || i === passos) await quadro(40);
    }
    cursor = { x, y };
  };
  const centro = async (sel) => {
    const b = await p.locator(sel).first().boundingBox();
    return [b.x + b.width / 2, b.y + b.height / 2];
  };
  const clicar = async (sel) => {
    const [x, y] = await centro(sel);
    await mover(x, y);
    await p.mouse.down(); await p.mouse.up();
  };
  const esperar = async (cond, ms = 20000) => p.waitForFunction(cond, null, { timeout: ms });

  // 1. janela vazia
  await p.mouse.move(cursor.x, cursor.y);
  await quadro(1300, 'vazio');
  // 2. arrastando músicas para a janela
  await mover(760, 520);
  await p.evaluate(() => { document.getElementById('soltar').hidden = false; });
  await quadro(900, 'soltar');
  await p.evaluate(async (pasta) => {
    document.getElementById('soltar').hidden = true;
    const nomes = ['Luz Neon', 'Até o Sol Nascer', 'Pista Molhada', 'Frequência', 'Calor de Março'];
    await fetch('/api/adicionar', {
      method: 'POST', headers: { 'X-Token': window.EXTDJ_TOKEN, 'Content-Type': 'application/json' },
      body: JSON.stringify({ caminhos: nomes.map((n) => `${pasta}/${n}.mp3`) }),
    });
  }, MUSICAS);
  // 3. análise (em tempo real ~15 s; na animação, acelerada)
  await esperar(() => !document.getElementById('m-espera').hidden);
  for (let i = 0; i < 60; i++) {
    const pronta = await p.evaluate(() => document.getElementById('m-espera').hidden);
    if (pronta) break;
    await quadro(i === 0 ? 700 : 260, 'analise');
    await p.waitForTimeout(500);
  }
  await esperar(() => !document.getElementById('x-carregando').hidden || document.querySelector('#x-duracao').textContent);
  await esperar(() => document.getElementById('x-carregando').hidden && document.querySelector('#x-duracao').textContent);
  await p.waitForTimeout(400);
  await quadro(2600, 'pronta');

  // 4. intro de 64 compassos
  await clicar('.lado[data-lado="intro"] .seg[data-campo="compassos"] button[data-v="64"]');
  await quadro(150);
  await p.waitForTimeout(400); await esperar(() => document.getElementById('x-carregando').hidden);
  await p.waitForTimeout(300);
  await quadro(1500, 'intro64');

  // 5. troca o trecho do loop do intro: arrasta o quadro verde na onda da original
  const onda = await p.locator('#onda-original').boundingBox();
  const regiao = await p.evaluate(() => {
    // acha o quadro verde do intro pela cor, na linha de cima da onda
    const c = document.getElementById('onda-original');
    const ctx = c.getContext('2d');
    const k = c.width / c.getBoundingClientRect().width;
    const y = Math.round(36 * k);
    const linha = ctx.getImageData(0, y, c.width, 1).data;
    let ini = -1, fim = -1;
    for (let x = 0; x < c.width; x++) {
      const [r, g, b] = linha.slice(x * 4, x * 4 + 3);
      const verde = g > 150 && r < 120 && b > 120;
      if (verde && ini < 0) ini = x;
      if (verde) fim = x;
    }
    return { ini: ini / k, fim: fim / k };
  });
  const xIni = onda.x + (regiao.ini + regiao.fim) / 2;
  const yQuadro = onda.y + 52;
  await mover(xIni, yQuadro);
  await quadro(350);
  await p.mouse.down();
  const destino = onda.x + onda.width * 0.29;
  for (let i = 1; i <= 10; i++) {
    const x = xIni + (destino - xIni) * (i / 10);
    await p.mouse.move(x, yQuadro);
    cursor = { x, y: yQuadro };
    if (i % 2 === 0) await quadro(60);
  }
  await p.mouse.up();
  await quadro(150);
  await p.waitForTimeout(400); await esperar(() => document.getElementById('x-carregando').hidden);
  await p.waitForTimeout(300);
  await quadro(1500, 'trecho');

  // 6. intro por cima da música: dois cliques no », o fader liga sozinho
  const mais = '.lado[data-lado="intro"] .passo[data-campo="sobrepor"] button[data-passo="1"]';
  await clicar(mais);
  await quadro(300);
  await p.mouse.down(); await p.mouse.up();
  await quadro(150);
  await p.waitForTimeout(400); await esperar(() => document.getElementById('x-carregando').hidden);
  await p.waitForTimeout(300);
  await quadro(1800, 'mixagem');

  // 7. ouve a entrada: o cursor de reprodução anda pela emenda
  await clicar('#ir-entrada');
  await p.waitForTimeout(250);
  for (let i = 0; i < 12; i++) {
    await quadro(220, 'tocando');
    await p.waitForTimeout(220);
  }
  await p.evaluate(() => document.querySelectorAll('audio').forEach((a) => a.pause()));
  await p.evaluate(() => document.querySelectorAll('.tocar.tocando').forEach((b) => b.click()));

  // 8. gerar
  await clicar('#btn-gerar');
  await quadro(500);
  await esperar(() => document.getElementById('status').classList.contains('ok'), 60000);
  await p.waitForTimeout(200);
  await quadro(2800, 'salvo');

  fs.writeFileSync(path.join(PASTA, 'quadros.txt'), lista.join('\n') + '\n');
  console.log(n, 'quadros; erros:', p.erros);
  await p.fechar();
})().catch((e) => { console.error(e); process.exit(1); });
