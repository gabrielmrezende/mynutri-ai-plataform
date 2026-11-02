/**
 * HTTP utils — MyNutri AI
 *
 * API_BASE   Prefixo de todas as chamadas à API (sempre relativo: o frontend é
 *            servido pelo próprio Django, então a API está na mesma origem).
 * apiFetch   Wrapper sobre fetch que:
 *              - envia sempre `X-Requested-With: XMLHttpRequest` (exigido pelo
 *                backend em requisições autenticadas por cookie — anti-CSRF);
 *              - usa credentials 'same-origin' (cookies HttpOnly de sessão);
 *              - tenta renovar o JWT uma vez em caso de 401.
 *
 * Opções extras aceitas em `opts` (removidas antes de chamar fetch):
 *   redirectOn401 {boolean} Redireciona para /auth/ se o refresh falhar. Default: true.
 *   skipRefresh   {boolean} Não tenta refresh em 401 (login/registro). Default: false.
 */

const API_BASE = '/api/v1';

let _refreshing = null;

function _buildFetchOpts(opts) {
  const headers = new Headers(opts.headers || {});
  headers.set('X-Requested-With', 'XMLHttpRequest');
  return Object.assign({}, opts, { headers, credentials: 'same-origin' });
}

async function apiFetch(url, opts = {}) {
  const redirectOn401 = opts.redirectOn401 !== false;
  const skipRefresh   = opts.skipRefresh === true;
  opts = Object.assign({}, opts);
  delete opts.redirectOn401;
  delete opts.skipRefresh;

  const fetchOpts = _buildFetchOpts(opts);

  let res = await fetch(url, fetchOpts);
  if (res.status !== 401 || skipRefresh) return res;

  if (!_refreshing) {
    _refreshing = fetch(`${API_BASE}/auth/token/refresh`, _buildFetchOpts({ method: 'POST' }))
      .finally(() => { _refreshing = null; });
  }

  let refreshRes;
  try {
    refreshRes = await _refreshing;
  } catch {
    return res;
  }
  if (!refreshRes.ok) {
    localStorage.removeItem('mynutri_user');
    if (redirectOn401) window.location.href = '/auth/';
    return res;
  }

  return fetch(url, fetchOpts);
}
