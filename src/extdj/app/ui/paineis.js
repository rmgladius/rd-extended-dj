// Painéis por cima da janela: Sobre (versão, quem fez o programa e como falar com ele) e
// Apoiar (Pix). Abrem pelos botões com data-abrir; fecham com Esc, com o X ou com um clique
// no fundo escuro, fora do cartão. Um painel pode abrir o outro (o rodapé do Sobre abre o Apoiar).
// GitHub, Instagram e os links do projeto têm target="_blank": na janela do programa o
// pywebview manda esses para o navegador padrão, e no modo --navegador abrem numa aba nova.

let aberto = null; // o painel visível
let voltarPara = null; // o botão do topo que abriu, para o foco voltar a ele
const relogios = new Map(); // botão de copiar → tempo para o rótulo voltar ao normal

export const painelAberto = () => aberto !== null;

function abrir(id, origem) {
  if (aberto) esconder();
  else voltarPara = origem;
  aberto = document.getElementById(id);
  aberto.hidden = false;
  aberto.querySelector('.sobre-cartao').focus();
}

function esconder() {
  aberto.hidden = true;
  for (const botao of aberto.querySelectorAll('[data-copiar]')) voltarRotulo(botao);
  aberto = null;
}

function fechar() {
  esconder();
  voltarPara?.focus();
}

document.addEventListener('click', (e) => {
  const abre = e.target.closest('[data-abrir]');
  if (abre) {
    abrir(abre.dataset.abrir, abre);
    return;
  }
  if (aberto && (e.target === aberto || e.target.closest('[data-fechar]'))) fechar();
});

// Enquanto um painel está aberto, o teclado fica nele: Esc fecha e o Tab dá a volta nos
// botões do cartão. O app.js também deixa de tratar espaço e Ctrl+Z (ver painelAberto).
window.addEventListener('keydown', (e) => {
  if (!aberto) return;
  if (e.key === 'Escape') {
    e.preventDefault();
    fechar();
    return;
  }
  if (e.key !== 'Tab') return;
  const cartao = aberto.querySelector('.sobre-cartao');
  const alvos = [...cartao.querySelectorAll('button, a[href]')];
  const primeiro = alvos[0];
  const ultimo = alvos[alvos.length - 1];
  const atual = document.activeElement;
  if (e.shiftKey && (atual === primeiro || !cartao.contains(atual) || atual === cartao)) {
    e.preventDefault();
    ultimo.focus();
  } else if (!e.shiftKey && (atual === ultimo || !cartao.contains(atual))) {
    e.preventDefault();
    primeiro.focus();
  }
});

// E-mail, código Pix e chave copiam em vez de abrir alguma coisa. O e-mail não vira "mailto:":
// muita gente usa o e-mail no navegador e não tem programa de e-mail configurado no Windows.
async function copiar(texto, botao) {
  try {
    await navigator.clipboard.writeText(texto);
    return true;
  } catch {
    // sem permissão para a área de transferência: vai pelo jeito antigo
  }
  const area = document.createElement('textarea');
  area.value = texto;
  area.setAttribute('readonly', '');
  area.style.cssText = 'position:fixed;top:0;left:0;opacity:0;user-select:text';
  document.body.append(area);
  area.select();
  let ok = false;
  try {
    ok = document.execCommand('copy');
  } catch {
    ok = false;
  }
  area.remove();
  botao.focus();
  return ok;
}

// O rótulo pequeno da linha vira o aviso ("E-mail copiado") e volta ao normal em 2,5 s.
document.addEventListener('click', async (e) => {
  const botao = e.target.closest('[data-copiar]');
  if (!botao) return;
  const ok = await copiar(botao.dataset.copiar, botao);
  const rotulo = botao.querySelector('.contato-texto small');
  botao.dataset.rotulo ??= rotulo.textContent;
  rotulo.textContent = ok ? botao.dataset.copiado : 'Não deu para copiar';
  botao.classList.toggle('copiado', ok);
  botao.classList.toggle('falhou', !ok);
  clearTimeout(relogios.get(botao));
  relogios.set(botao, setTimeout(() => voltarRotulo(botao), 2500));
});

function voltarRotulo(botao) {
  clearTimeout(relogios.get(botao));
  relogios.delete(botao);
  if (botao.dataset.rotulo === undefined) return;
  botao.querySelector('.contato-texto small').textContent = botao.dataset.rotulo;
  botao.classList.remove('copiado', 'falhou');
}
