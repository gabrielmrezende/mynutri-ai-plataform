/**
 * Helpers compartilhados — MyNutri AI
 *
 * Funções utilitárias usadas em múltiplas páginas.
 * Disponibilizadas no escopo global (sem módulos ES): os scripts das páginas
 * são arquivos clássicos carregados com defer (a CSP proíbe scripts inline).
 */

/** Retorna as iniciais de um nome (até 2 palavras). */
function initials(name) {
  if (!name) return '?';
  return name.trim().split(/\s+/).slice(0, 2).map(w => w[0].toUpperCase()).join('');
}

/** Escapa HTML para evitar XSS ao inserir strings em innerHTML. */
function escapeHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** Converte para número finito (ou o fallback) — use antes de interpolar números da API em HTML. */
function toNumber(value, fallback = 0) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

/** Formata uma string ISO em data por extenso (pt-BR). Ex: "02 de maio de 2026". */
function formatDate(iso) {
  const d = new Date(iso);
  return d.toLocaleDateString('pt-BR', { day: '2-digit', month: 'long', year: 'numeric' });
}

/**
 * Infere um rótulo legível para o objetivo de uma dieta a partir da
 * string armazenada no banco (goal_description).
 */
function goalLabel(raw) {
  if (!raw) return 'Plano alimentar';
  const lower = raw.toLowerCase();
  if (lower.includes('emagrecimento') || lower.includes('perda')  || lower.includes('loss'))     return 'Emagrecimento';
  if (lower.includes('ganho')         || lower.includes('hipertrofia') || lower.includes('gain')) return 'Ganho de Massa';
  if (lower.includes('manutenção')    || lower.includes('manutencao')  || lower.includes('maintain')) return 'Manutenção';
  return raw;
}

/**
 * Gerencia estado de carregamento de um botão passado por referência.
 * Usado em auth.html (login, register).
 * @param {HTMLElement} btn
 * @param {boolean} loading
 */
function setLoadingBtn(btn, loading) {
  btn.disabled = loading;
  btn.style.opacity = loading ? '0.7' : '1';
  btn.style.pointerEvents = loading ? 'none' : '';
  if (loading) btn.dataset.original = btn.textContent;
  else btn.textContent = btn.dataset.original || btn.textContent;
}

/**
 * Gerencia estado de carregamento via IDs de botão e spinner.
 * Usado em perfil.html (salvar dados, trocar senha).
 * @param {string} btnId
 * @param {string} spinnerId
 * @param {boolean} loading
 */
function setLoadingById(btnId, spinnerId, loading) {
  const btn = document.getElementById(btnId);
  const sp  = document.getElementById(spinnerId);
  if (btn) btn.disabled = loading;
  if (sp)  sp.style.display = loading ? 'block' : 'none';
}

/**
 * Exibe um toast temporário no elemento #sub-toast da página.
 * @param {string} msg
 * @param {'success'|'error'|'warning'} type
 */
function showToast(msg, type = 'success') {
  const t = document.getElementById('sub-toast');
  if (!t) return;
  t.textContent = msg;
  t.className = `sub-toast ${type} show`;
  clearTimeout(t._hideTimer);
  t._hideTimer = setTimeout(() => t.classList.remove('show'), 2800);
}

// ════════════════════════════════
//  MENSAGENS DE ERRO AMIGÁVEIS
// ════════════════════════════════

/**
 * Dicionário único de mensagens exibidas ao usuário por status HTTP / tipo de erro.
 * Nunca mostre detalhes técnicos (stack, str(exc), "servidor rodando" etc.) na UI.
 */
const FRIENDLY_MESSAGES = {
  network: 'Não foi possível conectar. Verifique sua internet e tente novamente.',
  timeout: 'A operação está demorando mais que o normal. Tente novamente em instantes.',
  400:     'Alguns dados não estão corretos. Revise e tente novamente.',
  401:     'Sua sessão expirou. Entre novamente para continuar.',
  403:     'Não foi possível confirmar esta ação. Recarregue a página e tente novamente.',
  404:     'Não encontramos o que você procurava.',
  409:     'Esta ação entrou em conflito com outra em andamento. Recarregue a página.',
  413:     'Os dados enviados são grandes demais.',
  429:     'Você atingiu o limite de tentativas por agora. Aguarde um pouco e tente novamente.',
  500:     'Tivemos um problema do nosso lado. Tente novamente em instantes.',
  502:     'O serviço está temporariamente indisponível. Tente novamente em instantes.',
  503:     'O serviço está temporariamente indisponível. Tente novamente em instantes.',
  504:     'O serviço demorou para responder. Tente novamente em instantes.',
  default: 'Algo deu errado. Tente novamente.',
};

/** Mensagem amigável para um status HTTP (ou 'network' / 'timeout'). */
function friendlyMessage(statusOrType, fallback) {
  if (FRIENDLY_MESSAGES[statusOrType]) return FRIENDLY_MESSAGES[statusOrType];
  if (typeof statusOrType === 'number' && statusOrType >= 500) return FRIENDLY_MESSAGES[500];
  return fallback || FRIENDLY_MESSAGES.default;
}

/**
 * Extrai uma mensagem legível do corpo de erro da API.
 * - 4xx (exceto 401/403/429): usa a mensagem de validação do backend, se for texto curto.
 * - demais: usa o dicionário amigável.
 * @param {number} status
 * @param {object|null} data  corpo JSON já parseado (ou null)
 * @param {string} [fallback]
 */
function apiErrorMessage(status, data, fallback) {
  const useBackend = status >= 400 && status < 500 && ![401, 403, 429].includes(status);
  if (useBackend && data && typeof data === 'object') {
    const first = _firstErrorString(data);
    if (first && first.length <= 300) return first;
  }
  return friendlyMessage(status, fallback);
}

function _firstErrorString(data) {
  if (typeof data === 'string') return data;
  if (Array.isArray(data)) {
    for (const item of data) {
      const s = _firstErrorString(item);
      if (s) return s;
    }
    return null;
  }
  if (data && typeof data === 'object') {
    for (const key of ['error', 'detail', 'non_field_errors', 'errors']) {
      if (data[key]) {
        const s = _firstErrorString(data[key]);
        if (s) return s;
      }
    }
    for (const key of Object.keys(data)) {
      const s = _firstErrorString(data[key]);
      if (s) return s;
    }
  }
  return null;
}

/** Lê o JSON de uma Response sem lançar em corpo vazio/não-JSON. */
async function safeJson(res) {
  try { return await res.json(); } catch { return null; }
}

// ════════════════════════════════
//  ARMAZENAMENTO LOCAL
// ════════════════════════════════

/** Chaves do app em localStorage/sessionStorage (o tema `mynutri_theme` é preservado). */
const APP_STORAGE_KEYS = {
  local:   ['mynutri_user'],
  session: ['anamneseData', 'mynutri_quest_draft', 'mynutri_diet_job'],
};

/** Remove os dados do usuário guardados no navegador, preservando preferências (tema). */
function clearAppStorage() {
  APP_STORAGE_KEYS.local.forEach(function (k) { try { localStorage.removeItem(k); } catch { /* ignore */ } });
  APP_STORAGE_KEYS.session.forEach(function (k) { try { sessionStorage.removeItem(k); } catch { /* ignore */ } });
}

// ════════════════════════════════
//  ACESSIBILIDADE
// ════════════════════════════════

/** true quando o usuário pediu redução de movimento no sistema. */
function prefersReducedMotion() {
  return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
}

const FOCUSABLE_SELECTOR = [
  'a[href]', 'button:not([disabled])', 'textarea:not([disabled])',
  'input:not([type="hidden"]):not([disabled])', 'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

/**
 * Mantém o foco de teclado (Tab / Shift+Tab) dentro de `container`.
 * Chame dentro de um listener de keydown enquanto o modal estiver aberto.
 */
function trapFocus(e, container) {
  if (e.key !== 'Tab' || !container) return;
  const items = Array.prototype.filter.call(
    container.querySelectorAll(FOCUSABLE_SELECTOR),
    function (el) { return el.offsetParent !== null || el === document.activeElement; }
  );
  if (!items.length) { e.preventDefault(); return; }
  const first = items[0];
  const last  = items[items.length - 1];
  if (e.shiftKey && (document.activeElement === first || !container.contains(document.activeElement))) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && (document.activeElement === last || !container.contains(document.activeElement))) {
    e.preventDefault();
    first.focus();
  }
}

/** Data local no formato AAAA-MM-DD (para nomes de arquivo). */
function isoDateStamp(date) {
  const d = date ? new Date(date) : new Date();
  const pad = function (n) { return String(n).padStart(2, '0'); };
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
