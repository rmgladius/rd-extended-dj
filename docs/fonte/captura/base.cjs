// Kit de captura do README: Chromium do Playwright com a Segoe UI do Windows e um cursor desenhado.
// Uso: veja docs/COMO-FUNCIONA.md, seção "Imagens do README".
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

// pasta onde ficam os quadros, as imagens paradas e o extended gravado na demonstração
const CAPTURAS = process.env.CAPTURAS || path.join(__dirname, 'saida');
const FONTES_WINDOWS = process.env.FONTES || '/mnt/c/Windows/Fonts';
const FONTES = { 'segoeui.ttf': 400, 'seguisb.ttf': 600, 'segoeuib.ttf': 700, 'seguibl.ttf': 800 };
const PASTA_TELA = 'C:\\Users\\DJ\\Music\\Extended';
const CURSOR = `<svg xmlns="http://www.w3.org/2000/svg" width="22" height="28" viewBox="0 0 22 28"><path d="M2 2v20.5l5.2-5 3.6 8.3 3.4-1.5-3.5-8.1h7.3z" fill="#fff" stroke="#000" stroke-width="1.5" stroke-linejoin="round"/></svg>`;

async function abrir({ porta = 8766, largura = 1180, altura = 720, escala = 2, video } = {}) {
  const b = await chromium.launch({ args: ['--autoplay-policy=no-user-gesture-required'] });
  const ctx = await b.newContext({ viewport: { width: largura, height: altura }, deviceScaleFactor: escala, bypassCSP: true, recordVideo: video });
  await ctx.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: `http://127.0.0.1:${porta}` });
  const p = await ctx.newPage();
  p.erros = [];
  p.on('pageerror', (e) => p.erros.push(String(e)));
  await p.route('http://fontes.local/*', (r) => r.fulfill({ body: fs.readFileSync(path.join(FONTES_WINDOWS, r.request().url().split('/').pop())), contentType: 'font/ttf' }));
  // a versão publicada roda no processador; o topo mostra isso mesmo que a captura use a placa
  await p.route('**/api/estado', async (r) => {
    const resp = await r.fetch();
    const e = await resp.json();
    e.dispositivo = 'processador';
    e.config.pasta_saida = PASTA_TELA;
    await r.fulfill({ response: resp, json: e });
  });
  // a tela mostra uma pasta do Windows; o arquivo vai de verdade para CAPTURAS/extended
  await p.route(/\/api\/(musica\/[^/]+\/gerar|gerar-todas)$/, async (r) => {
    const corpo = JSON.parse(r.request().postData() || '{}');
    corpo.pasta = path.join(CAPTURAS, 'extended');
    await r.continue({ postData: JSON.stringify(corpo) });
  });
  await p.addInitScript(({ fontes, cursor }) => {
    const css = Object.entries(fontes).map(([f, w]) => `@font-face{font-family:"Segoe UI";src:url(http://fontes.local/${f});font-weight:${w}}`).join('')
      + '#cursor-falso{position:fixed;z-index:99;left:0;top:0;pointer-events:none;transform:translate(-2px,-2px);filter:drop-shadow(0 1px 2px rgba(0,0,0,.5))}';
    document.addEventListener('DOMContentLoaded', () => {
      const s = document.createElement('style'); s.textContent = css; document.head.append(s);
      const c = document.createElement('div'); c.id = 'cursor-falso'; c.innerHTML = cursor; c.style.display = 'none'; document.body.append(c);
      window.addEventListener('mousemove', (e) => { c.style.display = ''; c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
    });
  }, { fontes: FONTES, cursor: CURSOR });
  await p.goto(`http://127.0.0.1:${porta}/`);
  await p.evaluate(() => document.fonts.ready);
  await p.waitForTimeout(600);
  p.fechar = () => b.close();
  p.ctx = ctx;
  return p;
}
module.exports = { abrir, CAPTURAS };
