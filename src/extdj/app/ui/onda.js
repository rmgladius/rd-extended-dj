// Forma de onda em três faixas, com grade de compassos, zoom, regiões arrastáveis
// (os loops) e o cursor de reprodução.

export const CORES = {
  graves: '#2f6fed',
  medios: '#f08a24',
  agudos: '#e4e9f0',
  fundo: '#12151a',
  grade: 'rgba(255,255,255,0.10)',
  frase: 'rgba(255,255,255,0.26)',
  batida: 'rgba(255,255,255,0.05)',
  rotulo: 'rgba(230,233,238,0.55)',
  cursor: '#ffffff',
};

const TOPO = 18;    // faixa dos números de compasso
const FAIXA = 7;    // faixa colorida (camadas ou voz)

function decodificar(b64) {
  const bin = atob(b64 || '');
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

export class Onda {
  constructor(canvas, opcoes = {}) {
    this.c = canvas;
    this.ctx = canvas.getContext('2d');
    this.aoBuscar = opcoes.aoBuscar || (() => {});
    this.aoMoverRegiao = opcoes.aoMoverRegiao || (() => {});
    this.dados = null;
    this.duracao = 0;
    this.compassos = [];
    this.rotulo = (i) => String(i + 1);
    this.batidasPorCompasso = 4;
    this.regioes = [];
    this.faixas = [];      // {t0, t1, cor, alfa, onde: 'topo' | 'base'}
    this.fundos = [];      // {t0, t1, cor}
    this.marcos = [];      // {t, cor, rotulo}
    this.v0 = 0;
    this.v1 = 1;
    this.tempo = null;
    this.estatico = document.createElement('canvas');
    this.arrasto = null;
    this.pronto = false;
    new ResizeObserver(() => this._medir()).observe(canvas);
    this._eventos();
    this._medir();
  }

  // ---------------------------------------------------------------- dados

  definirDados(onda, duracao) {
    this.dados = {
      fps: onda.fps,
      n: onda.n,
      graves: decodificar(onda.graves),
      medios: decodificar(onda.medios),
      agudos: decodificar(onda.agudos),
    };
    this.duracao = duracao;
    this.v0 = 0;
    this.v1 = duracao;
    this.pronto = true;
    this.redesenhar();
  }

  limpar() {
    this.dados = null;
    this.pronto = false;
    this.regioes = [];
    this.faixas = [];
    this.fundos = [];
    this.marcos = [];
    this.compassos = [];
    this.tempo = null;
    this.redesenhar();
  }

  definirGrade(compassos, batidasPorCompasso, rotulo) {
    this.compassos = compassos || [];
    this.batidasPorCompasso = batidasPorCompasso || 4;
    if (rotulo) this.rotulo = rotulo;
    this.redesenhar();
  }

  definirRegioes(regioes) { this.regioes = regioes; this.redesenhar(); }
  definirFaixas(faixas) { this.faixas = faixas; this.redesenhar(); }
  definirFundos(fundos) { this.fundos = fundos; this.redesenhar(); }
  definirMarcos(marcos) { this.marcos = marcos; this.redesenhar(); }

  definirTempo(t) {
    if (t === this.tempo) return;
    this.tempo = t;
    this._acompanhar();
    this._compor();
  }

  // ---------------------------------------------------------------- geometria

  _medir() {
    const r = this.c.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.dpr = dpr;
    this.L = Math.max(1, Math.round(r.width));
    this.A = Math.max(1, Math.round(r.height));
    this.c.width = this.estatico.width = Math.round(this.L * dpr);
    this.c.height = this.estatico.height = Math.round(this.A * dpr);
    this.redesenhar();
  }

  x(t) { return ((t - this.v0) / (this.v1 - this.v0)) * this.L; }
  t(x) { return this.v0 + (x / this.L) * (this.v1 - this.v0); }

  fimCompasso(k) {
    const c = this.compassos;
    if (k + 1 < c.length) return c[k + 1];
    const tam = c.length > 1 ? c[c.length - 1] - c[c.length - 2] : 2;
    return c[k] + tam;
  }

  compassoEm(t) {
    const c = this.compassos;
    let a = 0;
    let b = c.length - 1;
    if (!c.length) return 0;
    if (t < c[0]) return 0;
    while (a < b) {
      const m = (a + b + 1) >> 1;
      if (c[m] <= t) a = m; else b = m - 1;
    }
    return a;
  }

  compassoMaisPerto(t) {
    const k = this.compassoEm(t);
    const c = this.compassos;
    if (k + 1 < c.length && Math.abs(c[k + 1] - t) < Math.abs(c[k] - t)) return k + 1;
    return k;
  }

  _limitarVista() {
    const span = Math.min(Math.max(this.v1 - this.v0, Math.min(4, this.duracao)), this.duracao || 1);
    let v0 = Math.max(0, Math.min(this.v0, (this.duracao || 1) - span));
    this.v0 = v0;
    this.v1 = v0 + span;
  }

  _acompanhar() {
    // durante a reprodução com zoom, a vista anda junto com o cursor
    if (this.tempo == null || this.arrasto) return;
    const span = this.v1 - this.v0;
    if (span >= this.duracao - 0.01) return;
    if (this.tempo > this.v1 - span * 0.05 || this.tempo < this.v0) {
      this.v0 = this.tempo - span * 0.1;
      this.v1 = this.v0 + span;
      this._limitarVista();
      this.redesenhar();
    }
  }

  // ---------------------------------------------------------------- desenho

  redesenhar() {
    if (!this.estatico.width) return;
    const g = this.estatico.getContext('2d');
    const dpr = this.dpr || 1;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, this.L, this.A);
    g.fillStyle = CORES.fundo;
    g.fillRect(0, 0, this.L, this.A);
    if (!this.pronto) { this._compor(); return; }

    const topoOnda = TOPO + FAIXA + 2;
    const baseOnda = this.A - FAIXA - 2;
    const meio = (topoOnda + baseOnda) / 2;
    const meiaAltura = (baseOnda - topoOnda) / 2;

    for (const f of this.fundos) {
      g.fillStyle = f.cor;
      g.fillRect(this.x(f.t0), TOPO, this.x(f.t1) - this.x(f.t0), this.A - TOPO);
    }

    this._grade(g, topoOnda, baseOnda);
    this._onda(g, meio, meiaAltura);

    for (const f of this.faixas) {
      const y = f.onde === 'base' ? this.A - FAIXA : TOPO;
      g.globalAlpha = f.alfa ?? 1;
      g.fillStyle = f.cor;
      const xa = this.x(f.t0);
      g.fillRect(xa, y, Math.max(1, this.x(f.t1) - xa - 1), FAIXA - 1);
    }
    g.globalAlpha = 1;

    for (const m of this.marcos) {
      const x = Math.round(this.x(m.t)) + 0.5;
      if (x < -60 || x > this.L + 2) continue;
      g.strokeStyle = m.cor;
      g.lineWidth = 2;
      g.beginPath(); g.moveTo(x, TOPO); g.lineTo(x, this.A); g.stroke();
      if (m.rotulo) this._etiqueta(g, x + 1, TOPO + FAIXA + 3, m.rotulo, m.cor);
    }

    for (const r of this.regioes) this._regiao(g, r, topoOnda, baseOnda);

    if (this.v1 - this.v0 < this.duracao - 0.01) {
      // indicador de onde a vista está na música inteira
      const a = (this.v0 / this.duracao) * this.L;
      const b = (this.v1 / this.duracao) * this.L;
      g.fillStyle = 'rgba(255,255,255,0.08)';
      g.fillRect(0, this.A - 3, this.L, 3);
      g.fillStyle = 'rgba(255,255,255,0.45)';
      g.fillRect(a, this.A - 3, Math.max(4, b - a), 3);
    }
    this._compor();
  }

  _onda(g, meio, meiaAltura) {
    const d = this.dados;
    if (!d || !d.n) return;
    const colunas = Math.round(this.L * (this.dpr || 1));
    const passo = this.L / colunas;
    // graves atrás pelo pico (o bumbo aparece), médios e agudos na frente pela média
    // quadrática dos quadros de cada coluna, menores, para as quebras ficarem visíveis
    const camadas = [
      [d.graves, CORES.graves, 1, true],
      [d.medios, CORES.medios, 0.7, false],
      [d.agudos, CORES.agudos, 0.36, false],
    ];
    for (const [valores, cor, escala, pico] of camadas) {
      g.fillStyle = cor;
      g.beginPath();
      for (let i = 0; i < colunas; i++) {
        const xa = i * passo;
        const ia = Math.floor(this.t(xa) * d.fps);
        const ib = Math.max(ia + 1, Math.floor(this.t(xa + passo) * d.fps));
        if (ib <= 0 || ia >= d.n) continue;
        let soma = 0;
        let q = 0;
        let maior = 0;
        for (let j = Math.max(0, ia); j < Math.min(d.n, ib); j++) {
          const v = valores[j];
          soma += v * v;
          q++;
          if (v > maior) maior = v;
        }
        const m = pico ? maior : (q ? Math.sqrt(soma / q) : 0);
        const h = Math.min(1, (m / 255) * 1.15) * meiaAltura * escala;
        if (h < 0.4) continue;
        g.rect(xa, meio - h, passo + 0.02, 2 * h);
      }
      g.fill();
    }
  }

  _grade(g, topo, base) {
    const c = this.compassos;
    if (!c.length) return;
    const tam = c.length > 1 ? (c[c.length - 1] - c[0]) / (c.length - 1) : 2;
    const pxCompasso = (tam / (this.v1 - this.v0)) * this.L;
    const pxBatida = pxCompasso / this.batidasPorCompasso;
    let passoRotulo = 1;
    for (const p of [1, 2, 4, 8, 16, 32, 64]) { passoRotulo = p; if (pxCompasso * p >= 38) break; }
    const k0 = Math.max(0, this.compassoEm(this.v0) - 1);
    const k1 = Math.min(c.length - 1, this.compassoEm(this.v1) + 1);
    g.font = '600 10px "Segoe UI", system-ui, sans-serif';
    g.textBaseline = 'middle';
    for (let k = k0; k <= k1; k++) {
      const x = Math.round(this.x(c[k])) + 0.5;
      if (pxBatida >= 9) {
        g.strokeStyle = CORES.batida;
        g.lineWidth = 1;
        const fim = this.fimCompasso(k);
        for (let b = 1; b < this.batidasPorCompasso; b++) {
          const xb = Math.round(this.x(c[k] + ((fim - c[k]) * b) / this.batidasPorCompasso)) + 0.5;
          g.beginPath(); g.moveTo(xb, topo); g.lineTo(xb, base); g.stroke();
        }
      }
      const rot = this.rotulo(k);
      const numero = typeof rot === 'number' ? rot : parseInt(rot, 10);
      const frase = Number.isFinite(numero) && (numero - 1) % (passoRotulo >= 4 ? passoRotulo : 4) === 0;
      if (pxCompasso >= 5 || frase) {
        g.strokeStyle = frase ? CORES.frase : CORES.grade;
        g.lineWidth = 1;
        g.beginPath(); g.moveTo(x, topo); g.lineTo(x, base); g.stroke();
      }
      if (rot !== '' && Number.isFinite(numero) && (numero - 1) % passoRotulo === 0) {
        g.fillStyle = CORES.rotulo;
        g.fillText(String(rot), x + 3, TOPO / 2 + 1);
      }
    }
  }

  _regiao(g, r, topo, base) {
    const c = this.compassos;
    if (!c.length || r.ini == null || r.ini >= c.length) return;
    const t0 = c[r.ini];
    const t1 = this.fimCompasso(Math.min(c.length - 1, r.ini + r.tam - 1));
    const xa = this.x(t0);
    const xb = this.x(t1);
    if (xb < 0 || xa > this.L) return;
    g.fillStyle = r.cor + '2b';
    g.fillRect(xa, topo, xb - xa, base - topo);
    g.fillStyle = r.cor;
    g.fillRect(xa, topo, xb - xa, 2);
    g.fillRect(xa, base - 2, xb - xa, 2);
    g.fillRect(xa, topo, 2, base - topo);
    g.fillRect(xb - 2, topo, 2, base - topo);
    if (r.rotulo) this._etiqueta(g, xa, r.embaixo ? base - 17 : topo + 2, r.rotulo, r.cor, true);
    r._xa = xa;
    r._xb = xb;
  }

  _etiqueta(g, x, y, texto, cor, cheia) {
    g.font = '700 10px "Segoe UI", system-ui, sans-serif';
    const w = g.measureText(texto).width + 10;
    g.fillStyle = cheia ? cor : 'rgba(10,12,15,0.85)';
    g.fillRect(x, y, w, 15);
    g.fillStyle = cheia ? '#0b0d10' : cor;
    g.textBaseline = 'middle';
    g.fillText(texto, x + 5, y + 8);
  }

  _compor() {
    const g = this.ctx;
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.clearRect(0, 0, this.c.width, this.c.height);
    g.drawImage(this.estatico, 0, 0);
    if (this.tempo == null || !this.pronto) return;
    const dpr = this.dpr || 1;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const x = Math.round(this.x(this.tempo)) + 0.5;
    if (x < 0 || x > this.L) return;
    g.fillStyle = 'rgba(0,0,0,0.35)';
    g.fillRect(x - 2, TOPO, 4, this.A - TOPO);
    g.strokeStyle = CORES.cursor;
    g.lineWidth = 1.5;
    g.beginPath(); g.moveTo(x, TOPO); g.lineTo(x, this.A); g.stroke();
    g.fillStyle = CORES.cursor;
    g.beginPath(); g.moveTo(x - 5, TOPO); g.lineTo(x + 5, TOPO); g.lineTo(x, TOPO + 6); g.fill();
  }

  // ---------------------------------------------------------------- mouse

  _regiaoEm(x, y) {
    if (y < TOPO) return null;
    for (const r of [...this.regioes].reverse()) {
      if (r.arrastavel && r._xa != null && x >= r._xa - 3 && x <= r._xb + 3) return r;
    }
    return null;
  }

  _eventos() {
    const c = this.c;
    c.addEventListener('wheel', (e) => {
      if (!this.pronto) return;
      e.preventDefault();
      const r = c.getBoundingClientRect();
      const xm = e.clientX - r.left;
      if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) {
        const d = (e.deltaX || e.deltaY) / this.L * (this.v1 - this.v0);
        this.v0 += d; this.v1 += d;
      } else {
        const tm = this.t(xm);
        const fator = Math.exp(e.deltaY * 0.0016);
        const span = Math.min(this.duracao, Math.max(4, (this.v1 - this.v0) * fator));
        this.v0 = tm - (xm / this.L) * span;
        this.v1 = this.v0 + span;
      }
      this._limitarVista();
      this.redesenhar();
    }, { passive: false });

    c.addEventListener('pointerdown', (e) => {
      if (!this.pronto || e.button !== 0) return;
      const r = c.getBoundingClientRect();
      const x = e.clientX - r.left;
      const y = e.clientY - r.top;
      const reg = this._regiaoEm(x, y);
      this.arrasto = {
        x0: x, v0: this.v0, v1: this.v1, moveu: false, reg,
        ini0: reg ? reg.ini : null,
        desloc: reg ? this.t(x) - this.compassos[reg.ini] : 0,
      };
      c.setPointerCapture(e.pointerId);
    });

    c.addEventListener('pointermove', (e) => {
      const r = c.getBoundingClientRect();
      const x = e.clientX - r.left;
      const y = e.clientY - r.top;
      const a = this.arrasto;
      if (!a) {
        c.style.cursor = this._regiaoEm(x, y) ? 'grab' : 'pointer';
        return;
      }
      if (Math.abs(x - a.x0) > 3) a.moveu = true;
      if (!a.moveu) return;
      if (a.reg) {
        c.style.cursor = 'grabbing';
        let k = this.compassoMaisPerto(this.t(x) - a.desloc);
        k = Math.max(a.reg.min ?? 0, Math.min(a.reg.max ?? this.compassos.length - a.reg.tam, k));
        if (k !== a.reg.ini) { a.reg.ini = k; this.redesenhar(); }
      } else {
        const span = a.v1 - a.v0;
        if (span >= this.duracao - 0.01) return;
        const d = ((x - a.x0) / this.L) * span;
        this.v0 = a.v0 - d; this.v1 = a.v1 - d;
        this._limitarVista();
        this.redesenhar();
      }
    });

    const soltar = (e) => {
      const a = this.arrasto;
      this.arrasto = null;
      if (!a) return;
      const r = c.getBoundingClientRect();
      const x = e.clientX - r.left;
      if (a.reg && a.moveu) {
        if (a.reg.ini !== a.ini0) this.aoMoverRegiao(a.reg.id, a.reg.ini);
      } else if (!a.moveu) {
        this.aoBuscar(Math.max(0, Math.min(this.duracao, this.t(x))));
      }
    };
    c.addEventListener('pointerup', soltar);
    c.addEventListener('pointercancel', () => { this.arrasto = null; });
    c.addEventListener('dblclick', () => {
      this.v0 = 0; this.v1 = this.duracao; this.redesenhar();
    });
  }
}
