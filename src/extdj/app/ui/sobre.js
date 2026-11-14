// Painel Sobre: versão, quem fez o programa e como falar com ele.
// Fecha com Esc, com o X ou com um clique no fundo escuro, fora do cartão.
// GitHub, Instagram e os links do projeto têm target="_blank": na janela do programa o
// pywebview manda esses para o navegador padrão, e no modo --navegador abrem numa aba nova.

const painel = document.getElementById('sobre');
const cartao = painel.querySelector('.sobre-cartao');
const botaoSobre = document.getElementById('btn-sobre');
const botaoEmail = document.getElementById('contato-email');
const rotuloEmail = document.getElementById('email-rotulo');
let voltarTempo;

export const sobreAberto = () => !painel.hidden;

function abrir() {
  painel.hidden = false;
  cartao.focus();
}

function fechar() {
  painel.hidden = true;
  voltarRotuloDoEmail();
  botaoSobre.focus();
}

botaoSobre.addEventListener('click', abrir);
painel.addEventListener('click', (e) => {
  if (e.target === painel || e.target.closest('[data-fechar]')) fechar();
});

// Enquanto o painel está aberto, o teclado fica nele: Esc fecha e o Tab dá a volta nos
// botões do cartão. O app.js também deixa de tratar espaço e Ctrl+Z (ver sobreAberto).
window.addEventListener('keydown', (e) => {
  if (!sobreAberto()) return;
  if (e.key === 'Escape') {
    e.preventDefault();
    fechar();
    return;
  }
  if (e.key !== 'Tab') return;
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

// Copia em vez de abrir um "mailto:": muita gente usa o e-mail no navegador e não tem
// programa de e-mail configurado no Windows, e aí o clique não faria nada.
async function copiar(texto) {
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
  botaoEmail.focus();
  return ok;
}

botaoEmail.addEventListener('click', async () => {
  const ok = await copiar(botaoEmail.dataset.email);
  rotuloEmail.textContent = ok ? 'E-mail copiado' : 'Não deu para copiar';
  botaoEmail.classList.toggle('copiado', ok);
  botaoEmail.classList.toggle('falhou', !ok);
  clearTimeout(voltarTempo);
  voltarTempo = setTimeout(voltarRotuloDoEmail, 2500);
});

function voltarRotuloDoEmail() {
  clearTimeout(voltarTempo);
  rotuloEmail.textContent = 'E-mail';
  botaoEmail.classList.remove('copiado', 'falhou');
}
