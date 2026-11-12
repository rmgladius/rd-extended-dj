import { Onda } from './onda.js';

const TOKEN = window.EXTDJ_TOKEN;
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

const MODOS = [
  ['auto', 'Automático'],
  ['camadas', 'Em camadas (vai crescendo)'],
  ['completo', 'Música completa'],
  ['instrumental', 'Instrumental (sem voz)'],
  ['batida', 'Só a bateria'],
  ['batida_baixo', 'Bateria e baixo'],
];
const NOME_MODO = Object.fromEntries(MODOS);
const NOME_CAMADA = {
  batida: 'Bateria', batida_baixo: 'Bateria e baixo', instrumental: 'Instrumental',
  completo: 'Completa', musica: 'Original',
};
const COR_CAMADA = {
  batida: '#5b6cf0', batida_baixo: '#9b6cf6', instrumental: '#f2a53a', completo: '#3fcf7a', musica: '#4a515c',
};
const COR = { intro: '#2dd4bf', outro: '#f472b6', voz: '#c084fc' };

const S = {
  musicas: [],
  sel: null,
  detalhes: new Map(),
  ondas: new Map(),
  opcoes: new Map(),
  previas: new Map(),
  config: null,
  // ordem dos pedidos de prévia: parte do relógio para continuar crescendo se a janela
  // recarregar (o servidor descarta pedidos com número menor que o último)
  seq: Date.now(),
  exportando: new Set(),
  ultimoPlayer: 'extended',
};

// ------------------------------------------------------------------ servidor

async function api(rota, corpo) {
  const op = { method: corpo === undefined ? 'GET' : 'POST', headers: { 'X-Token': TOKEN } };
  if (corpo !== undefined) {
    op.headers['Content-Type'] = 'application/json';
    op.body = JSON.stringify(corpo);
  }
  const r = await fetch('/api/' + rota, op);
  const dados = await r.json().catch(() => ({}));
  if (!r.ok) {
    const e = new Error(dados.erro || `Erro ${r.status}`);
    e.status = r.status;
    throw e;
  }
  return dados;
}

// ------------------------------------------------------------------ formatação

function tempo(s, decimos) {
  if (!Number.isFinite(s)) return '0:00';
  const m = Math.floor(s / 60);
  const r = s - m * 60;
  const seg = decimos ? r.toFixed(1).padStart(4, '0') : String(Math.floor(r)).padStart(2, '0');
  return `${m}:${seg}`;
}
const num = (x, casas = 2) => Number(x).toFixed(casas).replace('.', ',');
function bpmTexto(b) { return Math.abs(b - Math.round(b)) < 0.05 ? String(Math.round(b)) : num(b, 1); }
function corCamelot(c) {
  const n = parseInt(c, 10);
  if (!n) return '#888';
  const hue = (((n - 1) * 30) + 160) % 360;
  return c.endsWith('B') ? `hsl(${hue} 70% 68%)` : `hsl(${hue} 62% 58%)`;
}
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function nomeMusica(m) {
  const r = m.resumo;
  if (r && r.titulo) return r.artista ? `${r.artista} - ${r.titulo}` : r.titulo;
  return m.nome.replace(/\.[^.]+$/, '');
}

let avisoTempo;
function aviso(texto, erro) {
  const el = $('#aviso');
  el.textContent = texto;
  el.classList.toggle('erro', !!erro);
  el.hidden = false;
  clearTimeout(avisoTempo);
  avisoTempo = setTimeout(() => { el.hidden = true; }, erro ? 6000 : 3500);
}

// ------------------------------------------------------------------ opções por música

function padraoLado(lado) {
  const c = S.config?.[lado] || {};
  return {
    compassos: c.compassos ?? 32, loop: c.loop ?? 4, modo: c.modo ?? 'auto', inicio: null,
    sobrepor: c.sobrepor ?? 0, fader: c.fader ?? 'sem', fader_pontos: null,
  };
}
function opcoesDe(id) {
  if (!S.opcoes.has(id)) S.opcoes.set(id, { intro: padraoLado('intro'), outro: padraoLado('outro') });
  return S.opcoes.get(id);
}

let configTempo;
function salvarPadrao(lado, op) {
  S.config[lado] = { compassos: op.compassos, loop: op.loop, modo: op.modo, sobrepor: op.sobrepor, fader: op.fader };
  clearTimeout(configTempo);
  configTempo = setTimeout(() => api('config', { intro: S.config.intro, outro: S.config.outro }).catch(() => {}), 400);
}

// ------------------------------------------------------------------ lista

let listaHtml = '';
function desenharLista() {
  const partes = S.musicas.map((m) => {
    const r = m.resumo;
    let info = '';
    if (m.estado === 'pronta' && r) {
      const salva = m.exportado ? '<span class="salva" title="Extended salvo">salva</span>' : '';
      const gerando = m.exportando ? '<span>gerando...</span>' : salva;
      info = `<div class="item-info"><span>${bpmTexto(r.bpm)} BPM</span>
        <span class="camelot" style="background:${corCamelot(r.tom.camelot)}">${esc(r.tom.camelot)}</span>
        <span>${tempo(r.duracao)}</span>${gerando}</div>`;
    } else if (m.estado === 'analisando') {
      info = `<div class="item-info"><span>${esc(m.etapa || 'analisando')}</span></div>
        <div class="mini"><span style="width:${Math.round(m.progresso * 100)}%"></span></div>`;
    } else if (m.estado === 'na fila') {
      info = '<div class="item-info"><span>na fila</span></div>';
    } else if (m.estado === 'erro') {
      info = `<div class="item-info erro"><span>${esc(m.erro)}</span></div>`;
    }
    return `<li class="item${m.id === S.sel ? ' ativo' : ''}" data-id="${m.id}" title="${esc(m.nome)}">
      <div class="item-nome">${esc(nomeMusica(m))}</div>${info}
      <button class="remover" data-remover="${m.id}" title="Tirar da lista">×</button></li>`;
  });
  const html = partes.join('');
  if (html !== listaHtml) {
    $('#lista').innerHTML = html;
    listaHtml = html;
  }
  $('#btn-todas').disabled = S.musicas.filter((m) => m.estado === 'pronta').length < 2;
}

$('#lista').addEventListener('click', async (e) => {
  const rem = e.target.closest('[data-remover]');
  if (rem) {
    e.stopPropagation();
    const id = rem.dataset.remover;
    await api(`musica/${id}/remover`, {}).catch(() => {});
    S.musicas = S.musicas.filter((m) => m.id !== id);
    if (S.sel === id) selecionar(S.musicas[0]?.id || null);
    desenharLista();
    return;
  }
  const li = e.target.closest('.item');
  if (li) selecionar(li.dataset.id);
});

// ------------------------------------------------------------------ estado (consulta periódica)

let consultaTempo;
async function consultar() {
  clearTimeout(consultaTempo);
  let ocupado = false;
  try {
    const e = await api('estado');
    if (!S.config) {
      S.config = e.config;
      $('#formato').value = e.config.formato;
    }
    S.config.pasta_saida = e.config.pasta_saida;
    mostrarPasta(e.config.pasta_saida);
    $('#dispositivo').textContent = `Processando em: ${e.dispositivo}`;
    $('#cache').textContent = `Cache ${e.cache_mb >= 1024 ? num(e.cache_mb / 1024, 1) + ' GB' : e.cache_mb + ' MB'}`;
    const antes = new Map(S.musicas.map((m) => [m.id, m]));
    S.musicas = e.musicas;
    for (const m of S.musicas) {
      const velho = antes.get(m.id);
      if (velho && velho.exportando && !m.exportando) {
        if (m.erro_exportar) status(`Erro ao gerar ${nomeMusica(m)}: ${m.erro_exportar}`, 'erro');
        else if (m.exportado) statusSalvo(m.exportado);
      }
      if (m.estado === 'analisando' || m.estado === 'na fila' || m.exportando) ocupado = true;
    }
    if (S.pendente && S.musicas.some((m) => m.id === S.pendente)) S.pendente = null;
    if (!S.sel && S.musicas.length) selecionar(S.musicas[0].id);
    else if (S.sel && S.sel !== S.pendente && !S.musicas.some((m) => m.id === S.sel)) {
      selecionar(S.musicas[0]?.id || null);
    }
    desenharLista();
    atualizarEditor();
  } catch (err) {
    ocupado = true;
  }
  consultaTempo = setTimeout(consultar, ocupado ? 700 : 2500);
}

// ------------------------------------------------------------------ adicionar músicas

async function adicionarPelaJanela() {
  try {
    const r = await api('escolher-arquivos', {});
    if (r.ids?.length) {
      selecionarDepois(r.ids[0]);
      consultar();
    }
  } catch (e) {
    if (e.status === 501) $('#arquivo').click();
    else aviso(e.message, true);
  }
}
$('#btn-adicionar').addEventListener('click', adicionarPelaJanela);
$('#btn-escolher').addEventListener('click', adicionarPelaJanela);
$('#arquivo').addEventListener('change', (e) => {
  enviar([...e.target.files]);
  e.target.value = '';
});

// música recém-adicionada: fica selecionada mesmo se uma consulta antiga chegar depois
function selecionarDepois(id) { S.pendente = id; selecionar(id); }

const EXT = /\.(mp3|flac|wav|aiff?|m4a|aac|ogg|opus|wma)$/i;
async function enviar(arquivos) {
  const audio = arquivos.filter((f) => EXT.test(f.name));
  if (!audio.length) {
    if (arquivos.length) aviso('Nenhum arquivo de áudio reconhecido.', true);
    return;
  }
  let primeiro = null;
  for (let i = 0; i < audio.length; i++) {
    const f = audio[i];
    status(`Recebendo ${i + 1} de ${audio.length}: ${f.name}`);
    try {
      const r = await fetch(`/api/enviar?nome=${encodeURIComponent(f.name)}`, {
        method: 'POST', headers: { 'X-Token': TOKEN, 'Content-Type': 'application/octet-stream' }, body: f,
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.erro || 'falhou');
      if (!primeiro) primeiro = d.id;
      consultar();
    } catch (e) {
      aviso(`${f.name}: ${e.message}`, true);
    }
  }
  status('');
  if (primeiro) selecionarDepois(primeiro);
}

// arrastar e soltar em qualquer lugar da janela (pastas também)
let contadorArrasto = 0;
window.addEventListener('dragenter', (e) => {
  if (!e.dataTransfer?.types?.includes('Files')) return;
  e.preventDefault();
  contadorArrasto++;
  $('#soltar').hidden = false;
});
window.addEventListener('dragover', (e) => { e.preventDefault(); });
window.addEventListener('dragleave', () => {
  contadorArrasto = Math.max(0, contadorArrasto - 1);
  if (!contadorArrasto) $('#soltar').hidden = true;
});
window.addEventListener('drop', async (e) => {
  e.preventDefault();
  contadorArrasto = 0;
  $('#soltar').hidden = true;
  const itens = [...(e.dataTransfer?.items || [])];
  const entradas = itens.map((i) => i.webkitGetAsEntry?.()).filter(Boolean);
  if (entradas.some((x) => x.isDirectory)) {
    const arquivos = [];
    await Promise.all(entradas.map((x) => lerEntrada(x, arquivos)));
    enviar(arquivos);
  } else {
    enviar([...(e.dataTransfer?.files || [])]);
  }
});
function lerEntrada(entrada, saida) {
  return new Promise((ok) => {
    if (entrada.isFile) {
      entrada.file((f) => { saida.push(f); ok(); }, () => ok());
    } else if (entrada.isDirectory) {
      const leitor = entrada.createReader();
      const todas = [];
      const ler = () => leitor.readEntries(async (lote) => {
        if (!lote.length) {
          await Promise.all(todas.map((x) => lerEntrada(x, saida)));
          ok();
        } else {
          todas.push(...lote);
          ler();
        }
      }, () => ok());
      ler();
    } else ok();
  });
}

// ------------------------------------------------------------------ editor

const ondaOriginal = new Onda($('#onda-original'), {
  aoBuscar: (t) => tocarEm('original', t),
  aoMoverRegiao: (lado, ini) => {
    const op = opcoesDe(S.sel)[lado];
    op.inicio = ini;
    desenharLados();
    pedirPrevia(true);
  },
});
const ondaExtended = new Onda($('#onda-extended'), {
  aoBuscar: (t) => tocarEm('extended', t),
  // alça » do intro ou « do outro: quantos compassos a mais (ou a menos) por cima da música
  aoMoverAlca: (lado, mais) => definirSobreposicao(lado, sobreValendo(lado) + mais, true),
  aoMoverFader: (lado, pontos) => {
    opcoesDe(S.sel)[lado].fader_pontos = pontos;
    desenharLados();
    pedirPrevia(true);
  },
});
window.__ondaOriginal = ondaOriginal;  // usados pelos testes automáticos da tela
window.__ondaExtended = ondaExtended;

const players = { original: new Audio(), extended: new Audio() };
for (const p of Object.values(players)) p.preload = 'auto';

function musicaSel() { return S.musicas.find((m) => m.id === S.sel) || null; }

async function selecionar(id) {
  if (id === S.sel && id !== null) { desenharLista(); return; }
  S.sel = id;
  for (const p of Object.values(players)) { p.pause(); p.removeAttribute('src'); p.load(); }
  ondaOriginal.limpar();
  ondaExtended.limpar();
  S.vistaExtended = null;
  $('#t-original').textContent = '0:00';
  $('#t-extended').textContent = '0:00';
  $('#x-duracao').textContent = '';
  desenharLista();
  atualizarEditor(true);
}

let carregando = null;
async function atualizarEditor(forcar) {
  const m = musicaSel();
  $('#vazio').hidden = !!m || S.musicas.length > 0;
  $('#editor').hidden = !m;
  if (!m) return;
  const r = m.resumo;
  $('#m-titulo').textContent = r?.titulo || m.nome.replace(/\.[^.]+$/, '');
  $('#m-artista').textContent = r?.artista || (r ? '' : m.nome);
  desenharChips(m);

  const pronta = m.estado === 'pronta';
  $('#m-espera').hidden = !(m.estado === 'analisando' || m.estado === 'na fila');
  $('#m-erro').hidden = m.estado !== 'erro';
  $('#m-conteudo').hidden = !pronta;
  if (m.estado === 'erro') $('#m-erro').textContent = `Não consegui analisar esta música: ${m.erro}`;
  if (!pronta) {
    $('#m-etapa').textContent = m.estado === 'na fila' ? 'Na fila, esperando a música anterior' :
      `${m.etapa ? m.etapa[0].toUpperCase() + m.etapa.slice(1) : 'Analisando'} (${Math.round(m.progresso * 100)}%)`;
    $('#m-progresso').style.width = `${Math.round(m.progresso * 100)}%`;
    $('#btn-gerar').disabled = true;
    return;
  }
  $('#btn-gerar').disabled = m.exportando;
  if ((forcar || !ondaOriginal.pronto) && carregando !== m.id) {
    carregando = m.id;
    try {
      await carregarMusica(m);
    } catch (e) {
      aviso(`Não consegui abrir ${nomeMusica(m)}: ${e.message}`, true);
    } finally {
      carregando = null;
    }
  }
}

function desenharChips(m) {
  const r = m.resumo;
  if (!r) { $('#m-chips').innerHTML = ''; return; }
  const bpm = r.variavel ? `${bpmTexto(r.bpm)}<small> (${num(r.bpm_min, 0)} a ${num(r.bpm_max, 0)})</small>` : bpmTexto(r.bpm);
  const estilo = r.estilos?.[0]?.estilo?.replace(/\s*\(.*\)$/, '') || '?';
  const voz = r.voz_compasso ? `compasso ${r.voz_compasso}` : 'sem voz';
  $('#m-chips').innerHTML = `
    <div class="chip"><small>BPM</small><b>${bpm}</b></div>
    <div class="chip"><small>Tom</small><b>${esc(r.tom.tom)}<span class="camelot" style="background:${corCamelot(r.tom.camelot)}">${esc(r.tom.camelot)}</span></b></div>
    <div class="chip" title="${esc((r.estilos || []).map((e) => e.estilo).join(', '))}"><small>Estilo</small><b>${esc(estilo)}</b></div>
    <div class="chip"><small>Batida</small><b>${esc(r.batida)}</b></div>
    <div class="chip"><small>Voz entra</small><b>${esc(voz)}</b></div>`;
}

async function carregarMusica(m) {
  const id = m.id;
  if (!S.detalhes.has(id)) {
    const d = await api(`musica/${id}`);
    S.detalhes.set(id, d.detalhes);
  }
  if (!S.ondas.has(id)) {
    const r = await fetch(`/api/musica/${id}/onda`, { headers: { 'X-Token': TOKEN } });
    S.ondas.set(id, await r.json());
  }
  if (S.sel !== id) return;
  const d = S.detalhes.get(id);
  ondaOriginal.definirDados(S.ondas.get(id), d.duracao);
  ondaOriginal.definirGrade(d.compassos, d.batidas_por_compasso, (k) => k - d.entrada + 1);
  // compassos com voz numa faixa embaixo
  const faixas = [];
  d.voz.forEach((v, k) => {
    if (v > 0.3) faixas.push({ t0: d.compassos[k], t1: ondaOriginal.fimCompasso(k), cor: COR.voz, alfa: Math.min(1, 0.35 + v), onde: 'base' });
  });
  ondaOriginal.definirFaixas(faixas);
  ondaOriginal.definirFundos([
    { t0: 0, t1: d.compassos[d.entrada] ?? 0, cor: 'rgba(0,0,0,0.35)' },
    { t0: ondaOriginal.fimCompasso(d.saida - 1), t1: d.duracao, cor: 'rgba(0,0,0,0.35)' },
  ]);
  players.original.src = `/audio/${id}/original?t=${TOKEN}`;
  desenharLados();
  pedirPrevia(true);
}

// ------------------------------------------------------------------ cartões de intro e outro

for (const sel of $$('.lado select[data-campo="modo"]')) {
  sel.innerHTML = MODOS.map(([v, n]) => `<option value="${v}">${n}</option>`).join('');
}

for (const cartao of $$('.lado')) {
  const lado = cartao.dataset.lado;
  cartao.addEventListener('click', (e) => {
    const b = e.target.closest('.seg button');
    const op = opcoesDe(S.sel)[lado];
    if (b && !b.disabled) {
      const campo = b.closest('.seg').dataset.campo;
      if (campo === 'fader') {
        op.fader = b.dataset.v;
        op.fader_pontos = null;   // escolher de novo volta a rampa automática
      } else {
        op[campo] = Number(b.dataset.v);
        if (op.compassos && op.loop > op.compassos) op.loop = op.compassos;
        if (campo === 'compassos') {
          op.sobrepor = Math.min(op.sobrepor, op.compassos);
          op.fader_pontos = null;
        }
      }
      salvarPadrao(lado, op);
      desenharLados();
      pedirPrevia();
      return;
    }
    const passo = e.target.closest('[data-passo]');
    if (passo && !passo.disabled) {
      definirSobreposicao(lado, Math.min(op.sobrepor, sobreMaximo(lado)) + Number(passo.dataset.passo));
      return;
    }
    if (e.target.closest('[data-acao="auto"]')) {
      op.inicio = null;
      desenharLados();
      pedirPrevia(true);
    }
    if (e.target.closest('[data-acao="fader-auto"]')) {
      op.fader_pontos = null;
      desenharLados();
      pedirPrevia(true);
    }
  });
  $('select[data-campo="modo"]', cartao).addEventListener('change', (e) => {
    const op = opcoesDe(S.sel)[lado];
    op.modo = e.target.value;
    salvarPadrao(lado, op);
    desenharLados();
    pedirPrevia(true);
  });
}

// ------------------------------------------------------------------ sobreposição e fader

// quanto o bloco pode entrar na música (a última prévia sabe o tamanho dela e do outro lado)
function sobreMaximo(lado) {
  const op = opcoesDe(S.sel)[lado];
  const mx = S.previas.get(S.sel)?.meta?.sobrepor_max?.[lado];
  return Math.min(op.compassos, mx ?? op.compassos);
}
// a sobreposição que valeu na última prévia (pode ter sido cortada para caber na música)
function sobreValendo(lado) {
  const m = S.previas.get(S.sel)?.meta?.[lado];
  return m ? m.sobrepor : opcoesDe(S.sel)[lado].sobrepor;
}
function definirSobreposicao(lado, n, imediato) {
  const op = opcoesDe(S.sel)[lado];
  const antes = Math.min(op.sobrepor, sobreMaximo(lado));
  const novo = Math.max(0, Math.min(sobreMaximo(lado), n));
  if (novo === antes && novo === op.sobrepor) { desenharLados(); return; }
  op.sobrepor = novo;
  // quando o bloco entra na música o fader já vem no sentido da mixagem: o intro baixa
  // enquanto a música entra, o outro sobe enquanto ela acaba. Saindo de cima dela, esse
  // fader automático desliga (senão a rampa passaria para o bloco inteiro)
  const natural = lado === 'intro' ? 'baixar' : 'subir';
  if (antes === 0 && novo > 0 && op.fader === 'sem') op.fader = natural;
  else if (antes > 0 && novo === 0 && op.fader === natural && !op.fader_pontos) op.fader = 'sem';
  salvarPadrao(lado, op);
  desenharLados();
  pedirPrevia(imediato);
}

function textoCompassos(n) {
  const v = Math.round(n * 4) / 4;
  return `${String(v).replace('.', ',')} ${v === 1 ? 'compasso' : 'compassos'}`;
}

function desenharLados() {
  const id = S.sel;
  if (!id) return;
  const ops = opcoesDe(id);
  const d = S.detalhes.get(id);
  const pv = S.previas.get(id);
  const regioes = [];
  for (const cartao of $$('.lado')) {
    const lado = cartao.dataset.lado;
    const op = ops[lado];
    cartao.classList.toggle('desligado', !op.compassos);
    for (const seg of $$('.seg', cartao)) {
      const campo = seg.dataset.campo;
      for (const b of $$('button', seg)) {
        const v = Number(b.dataset.v);
        b.classList.toggle('ativo', op[campo] === v);
        if (campo === 'loop') b.disabled = !op.compassos || v > op.compassos;
      }
    }
    $('select', cartao).value = op.modo;
    for (const b of $$('.seg[data-campo="fader"] button', cartao)) b.classList.toggle('ativo', op.fader === b.dataset.v);
    const sobre = Math.min(op.sobrepor, sobreMaximo(lado));
    $('.passo-valor', cartao).textContent = op.compassos ? sobre : 0;
    $('.passo', cartao).classList.toggle('ligado', sobre > 0);
    for (const b of $$('[data-passo]', cartao)) {
      const d = Number(b.dataset.passo);
      b.disabled = !op.compassos || (d < 0 ? sobre <= 0 : sobre >= sobreMaximo(lado));
    }

    const escolha = pv?.[lado];
    const res = $('.resultado', cartao);
    const trecho = $('.trecho', cartao);
    const plano = $('.plano', cartao);
    const info = $('.fader-info', cartao);
    if (!op.compassos) {
      res.textContent = 'desligado';
      trecho.innerHTML = '';
      plano.innerHTML = '';
      info.innerHTML = '';
      continue;
    }
    const curva = escolha?.curva;
    if (op.fader === 'sem' || !curva) {
      info.textContent = op.fader === 'sem' ? 'volume do loop fixo' : '';
    } else {
      const [[p0, n0], [p1, n1]] = curva;
      const pct = (v) => `${Math.round(v * 100)}%`;
      info.innerHTML = `<span>${pct(n0)} → ${pct(n1)} em ${textoCompassos(p1 - p0)}</span>` +
        (op.fader_pontos ? '<button class="link" data-acao="fader-auto">voltar ao automático</button>' : '');
    }
    res.textContent = escolha ? (op.modo === 'auto' ? `automático escolheu: ${NOME_MODO[escolha.modo] || escolha.modo}` : '') : '';
    const ini = op.inicio ?? escolha?.inicio;
    if (d && ini != null) {
      const n = ini - d.entrada + 1;
      const fixo = op.inicio != null;
      trecho.innerHTML = `Loop a partir do compasso <b>${n}</b> da música ${fixo ? '(escolhido por você)' : '(escolha automática)'}
        ${fixo ? '<button class="link" data-acao="auto">voltar ao automático</button>' : ''}`;
      regioes.push({
        id: lado, ini, tam: op.loop, cor: COR[lado], rotulo: lado === 'intro' ? 'loop do intro' : 'loop do outro',
        embaixo: lado === 'outro',
        arrastavel: true, min: 0, max: d.compassos.length - op.loop,
      });
    } else {
      trecho.textContent = '';
    }
    // plano de camadas: blocos seguidos com o que toca em cada parte (listrado: por cima da música)
    const camadas = escolha?.camadas || [];
    const s = escolha ? escolha.sobrepor : 0;
    const blocos = [];
    camadas.forEach((c, j) => {
      const sob = lado === 'intro' ? j >= camadas.length - s : j < s;
      const ult = blocos[blocos.length - 1];
      if (ult && ult.c === c && ult.sob === sob) ult.n++;
      else blocos.push({ c, n: 1, sob });
    });
    plano.innerHTML = blocos.map((b) => {
      const titulo = `${b.n} compassos: ${NOME_CAMADA[b.c]}${b.sob ? ', por cima da música' : ''}`;
      return `<span class="${b.sob ? 'sobre' : ''}" style="flex:${b.n};background-color:${COR_CAMADA[b.c]}" title="${titulo}">${b.n} · ${NOME_CAMADA[b.c]}</span>`;
    }).join('');
  }
  ondaOriginal.definirRegioes(regioes);
}

// ------------------------------------------------------------------ prévia

let previaTempo;
function pedirPrevia(imediato) {
  clearTimeout(previaTempo);
  previaTempo = setTimeout(fazerPrevia, imediato ? 0 : 220);
}

async function fazerPrevia() {
  const id = S.sel;
  if (!id) return;
  const ops = opcoesDe(id);
  if (!ops.intro.compassos && !ops.outro.compassos) {
    $('#x-erro').hidden = false;
    $('#x-erro').textContent = 'Escolha pelo menos um intro ou um outro.';
    return;
  }
  const seq = ++S.seq;
  $('#x-carregando').hidden = false;
  $('#x-erro').hidden = true;
  try {
    const r = await api(`musica/${id}/previa`, { opcoes: ops, seq });
    if (r.superada || seq !== S.seq || id !== S.sel) return;
    S.previas.set(id, r);
    aplicarPrevia(id, r);
  } catch (e) {
    if (seq === S.seq) {
      $('#x-erro').hidden = false;
      $('#x-erro').textContent = e.message;
    }
  } finally {
    if (seq === S.seq) $('#x-carregando').hidden = true;
  }
}

function aplicarPrevia(id, r) {
  const meta = r.meta;
  const p = players.extended;
  const tocando = !p.paused;
  const posicao = p.currentTime || 0;
  // com zoom, a vista e o cursor ficam no mesmo ponto da música quando ela anda
  // (o intro entrando nela encurta o começo do extended)
  const ant = S.vistaExtended?.id === id ? S.vistaExtended : null;
  const anda = ant ? meta.inicio_original_s - ant.ini : 0;
  const zoom = ant && ondaExtended.pronto && ondaExtended.v1 - ondaExtended.v0 < ondaExtended.duracao - 0.01
    ? [ondaExtended.v0 + anda, ondaExtended.v1 + anda] : null;
  ondaExtended.definirDados(r.onda, r.duracao);
  if (zoom) ondaExtended.mostrar(...zoom);
  S.vistaExtended = { id, ini: meta.inicio_original_s };
  ondaExtended.definirGrade(meta.compassos_s, r.batidas_por_compasso, (k) => k + 1);
  // em cima o loop, embaixo a original: onde as duas faixas aparecem, tocam juntos
  const musica = meta.musica_s || meta.camadas_s.map((c) => c === 'musica');
  const faixas = [];
  meta.compassos_s.forEach((t, i) => {
    const t1 = meta.compassos_s[i + 1] ?? r.duracao;
    const cam = meta.camadas_s[i];
    if (cam !== 'musica') faixas.push({ t0: t, t1, cor: COR_CAMADA[cam] || '#555', onde: 'topo' });
    if (musica[i]) faixas.push({ t0: t, t1, cor: COR_CAMADA.musica, onde: 'base' });
  });
  ondaExtended.definirFaixas(faixas);
  const fundos = [];
  if (meta.intro) fundos.push({ t0: 0, t1: meta.intro_s[1], cor: 'rgba(45,212,191,0.07)' });
  if (meta.outro) fundos.push({ t0: meta.outro_s[0], t1: r.duracao, cor: 'rgba(244,114,182,0.07)' });
  ondaExtended.definirFundos(fundos);
  const marcos = [];
  if (meta.intro) marcos.push({ t: meta.inicio_original_s, cor: COR.intro, rotulo: 'música' });
  if (meta.outro) marcos.push({ t: meta.inicio_outro_s, cor: COR.outro, rotulo: 'outro' });
  if (meta.outro?.sobrepor) marcos.push({ t: meta.fim_original_s, cor: COR.outro, rotulo: 'fim da música' });
  ondaExtended.definirMarcos(marcos);

  const n = meta.compassos_s.length;
  const blocos = [];
  const alcas = [];
  const envelopes = [];
  for (const lado of ['intro', 'outro']) {
    const e = meta[lado];
    if (!e) continue;
    const kIni = lado === 'intro' ? 0 : n - e.compassos;
    const kFim = kIni + e.compassos;
    const mx = meta.sobrepor_max[lado];
    blocos.push({ id: lado, kIni, kFim, cor: COR[lado] });
    alcas.push({
      id: lado, k: lado === 'intro' ? kFim : kIni, kIni, kFim, sentido: lado === 'intro' ? 1 : -1,
      min: -e.sobrepor, max: mx - e.sobrepor, sobre: e.sobrepor, cor: COR[lado], seta: lado === 'intro' ? '»' : '«',
    });
    if (e.curva) envelopes.push({ id: lado, kIni, kFim, cor: COR[lado], pontos: e.curva.map(([q, v]) => ({ p: q, nivel: v })) });
  }
  ondaExtended.definirMixagem({ blocos, alcas, envelopes });

  const orig = S.musicas.find((m) => m.id === id)?.resumo?.duracao || 0;
  const extra = r.duracao - orig;
  $('#x-duracao').textContent = `${tempo(r.duracao)} (${extra >= 0 ? '+' : '−'}${tempo(Math.abs(extra))})`;
  $('#x-duracao').title = 'Duração do extended e quanto ele tem a mais que a original';
  p.src = `/audio/${id}/previa?v=${r.versao}&t=${TOKEN}`;
  if (tocando || posicao > 0) {
    p.addEventListener('loadedmetadata', () => {
      p.currentTime = Math.max(0, Math.min(posicao + anda, r.duracao - 0.1));
      if (tocando) p.play().catch(() => {});
    }, { once: true });
  }
  desenharLados();
}

// ------------------------------------------------------------------ players

function tocarEm(qual, t) {
  const p = players[qual];
  if (!p.src) return;
  S.ultimoPlayer = qual;
  for (const [nome, outro] of Object.entries(players)) if (nome !== qual) outro.pause();
  p.currentTime = t;
  p.play().catch(() => {});
}

function alternar(qual) {
  const p = players[qual];
  if (!p.src) return;
  S.ultimoPlayer = qual;
  if (p.paused) {
    for (const [nome, outro] of Object.entries(players)) if (nome !== qual) outro.pause();
    p.play().catch(() => {});
  } else p.pause();
}

for (const b of $$('.tocar')) b.addEventListener('click', () => alternar(b.dataset.player));

function compassoTexto(onda, t, rotulo) {
  if (!onda.compassos.length) return '';
  const k = onda.compassoEm(t);
  const ini = onda.compassos[k];
  const fim = onda.fimCompasso(k);
  const batida = Math.floor(((t - ini) / (fim - ini)) * onda.batidasPorCompasso) + 1;
  if (t < onda.compassos[0]) return '';
  return ` · compasso ${rotulo(k)}.${Math.min(onda.batidasPorCompasso, Math.max(1, batida))}`;
}

function quadro() {
  const po = players.original;
  const pe = players.extended;
  if (po.src) {
    ondaOriginal.definirTempo(po.currentTime);
    const d = S.detalhes.get(S.sel);
    $('#t-original').textContent = `${tempo(po.currentTime, true)} / ${tempo(po.duration || 0)}` +
      (d ? compassoTexto(ondaOriginal, po.currentTime, (k) => k - d.entrada + 1) : '');
  }
  if (pe.src) {
    ondaExtended.definirTempo(pe.currentTime);
    $('#t-extended').textContent = `${tempo(pe.currentTime, true)} / ${tempo(pe.duration || 0)}` +
      compassoTexto(ondaExtended, pe.currentTime, (k) => k + 1);
  }
  for (const b of $$('.tocar')) b.classList.toggle('tocando', !players[b.dataset.player].paused);
  requestAnimationFrame(quadro);
}
requestAnimationFrame(quadro);

function oitoCompassosAntes(t) {
  const c = ondaExtended.compassos;
  const k = ondaExtended.compassoMaisPerto(t);
  return c[Math.max(0, k - 8)] ?? Math.max(0, t - 15);
}
$('#ir-entrada').addEventListener('click', () => {
  const r = S.previas.get(S.sel);
  if (r?.meta.intro) tocarEm('extended', oitoCompassosAntes(r.meta.inicio_original_s));
  else aviso('Este extended não tem intro.');
});
$('#ir-saida').addEventListener('click', () => {
  const r = S.previas.get(S.sel);
  if (r?.meta.outro) tocarEm('extended', oitoCompassosAntes(r.meta.inicio_outro_s));
  else aviso('Este extended não tem outro.');
});

window.addEventListener('keydown', (e) => {
  if (e.code !== 'Space' || e.target.closest('input, select, textarea')) return;
  e.preventDefault();
  alternar(S.ultimoPlayer);
});

// ------------------------------------------------------------------ exportar

function mostrarPasta(caminho) {
  // o botão corta o começo do caminho (direção rtl); as marcas LRM mantêm as barras no lugar
  $('#pasta').textContent = `\u200E${caminho}\u200E`;
  $('#pasta').title = caminho;
}

function status(texto, tipo) {
  const el = $('#status');
  el.className = 'status' + (tipo ? ' ' + tipo : '');
  el.innerHTML = '';
  el.textContent = texto;
}
function statusSalvo(caminho) {
  const el = $('#status');
  el.className = 'status ok';
  const nome = caminho.split(/[\\/]/).pop();
  el.innerHTML = `Salvo: ${esc(nome)} <button class="link">abrir pasta</button>`;
  $('button', el).addEventListener('click', () => api('abrir-pasta', { caminho }).catch((e) => aviso(e.message, true)));
}

$('#btn-gerar').addEventListener('click', async () => {
  const m = musicaSel();
  if (!m || m.estado !== 'pronta') return;
  try {
    await api(`musica/${m.id}/gerar`, { opcoes: opcoesDe(m.id), formato: $('#formato').value, pasta: S.config.pasta_saida });
    status(`Gerando ${nomeMusica(m)}...`);
    m.exportando = true;
    $('#btn-gerar').disabled = true;
    consultar();
  } catch (e) {
    status(e.message, 'erro');
  }
});

$('#btn-todas').addEventListener('click', async () => {
  const prontas = S.musicas.filter((m) => m.estado === 'pronta');
  const itens = prontas.map((m) => ({ id: m.id, opcoes: opcoesDe(m.id) }));
  try {
    const r = await api('gerar-todas', { itens, formato: $('#formato').value, pasta: S.config.pasta_saida });
    status(`Gerando ${r.na_fila} músicas...`);
    consultar();
  } catch (e) {
    status(e.message, 'erro');
  }
});

$('#formato').addEventListener('change', (e) => {
  S.config.formato = e.target.value;
  api('config', { formato: e.target.value }).catch(() => {});
});

$('#pasta').addEventListener('click', async () => {
  try {
    const r = await api('escolher-pasta', {});
    if (r.pasta) { S.config.pasta_saida = r.pasta; mostrarPasta(r.pasta); }
  } catch (e) {
    if (e.status !== 501) { aviso(e.message, true); return; }
    const nova = prompt('Pasta onde salvar os extended:', S.config.pasta_saida);
    if (nova) {
      const c = await api('config', { pasta_saida: nova });
      S.config.pasta_saida = c.pasta_saida;
      mostrarPasta(c.pasta_saida);
    }
  }
});

$('#btn-limpar').addEventListener('click', async () => {
  if (!confirm('Apagar os instrumentos separados das músicas que não estão abertas? Se elas voltarem, a separação é feita de novo.')) return;
  const r = await api('limpar-cache', {});
  aviso(`Liberados ${r.liberado_mb} MB.`);
  consultar();
});

consultar();
