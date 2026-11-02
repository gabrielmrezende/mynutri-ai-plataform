(function () {
  function show(id)     { document.getElementById(id).style.display = ''; }
  function hide(id)     { document.getElementById(id).style.display = 'none'; }
  function showFlex(id) { document.getElementById(id).style.display = 'flex'; }

  // Paginação da API (/diet/list?page=N → { results, count, page, total_pages })
  let _page       = 0;
  let _totalPages = 1;
  let _loading    = false;

  const loadMoreBtn = document.getElementById('btnLoadMore');

  function buildCard(plan) {
    const macros = plan.macros || {};
    const kcal   = toNumber(plan.calorias_totais, 0);
    const prot   = toNumber(macros.protein_g, 0);
    const carb   = toNumber(macros.carbs_g, 0);
    const fat    = toNumber(macros.fat_g, 0);
    const id     = toNumber(plan.id, 0);
    const date   = formatDate(plan.created_at);

    const card = document.createElement('a');
    card.href = `/dieta/?id=${id}`;
    card.className = 'diet-card';
    card.setAttribute('aria-label', `Ver dieta de ${date}`);

    // Textos vindos da API sempre escapados antes de ir para innerHTML
    card.innerHTML = `
      <div class="diet-card-left">
        <div class="diet-icon" aria-hidden="true">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 3h18v4H3zM3 10h18v4H3zM3 17h18v4H3z"/>
          </svg>
        </div>
        <div class="diet-info">
          <div class="diet-date">${escapeHtml(date)}</div>
          <div class="diet-goal">${escapeHtml(goalLabel(plan.goal_description))}</div>
        </div>
      </div>

      <div class="diet-card-meta">
        ${kcal ? `<span class="meta-pill calories">
          <svg aria-hidden="true" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
          ${kcal} kcal
        </span>` : ''}
        ${prot ? `<span class="meta-pill protein">${prot}g prot</span>` : ''}
        ${carb ? `<span class="meta-pill carbs">${carb}g carb</span>`   : ''}
        ${fat  ? `<span class="meta-pill fat">${fat}g gord</span>`       : ''}
      </div>

      <svg class="diet-card-arrow" aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="9 18 15 12 9 6"/>
      </svg>
    `;
    return card;
  }

  function updateLoadMore() {
    if (!loadMoreBtn) return;
    loadMoreBtn.hidden = _page >= _totalPages;
    loadMoreBtn.disabled = _loading;
    loadMoreBtn.setAttribute('aria-busy', _loading ? 'true' : 'false');
    loadMoreBtn.textContent = _loading ? 'Carregando…' : 'Carregar mais';
  }

  async function fetchPage(page) {
    const res = await apiFetch(`${API_BASE}/diet/list?page=${page}`, { redirectOn401: false });
    if (res.status === 401) return { unauthorized: true };
    if (!res.ok) {
      const err = new Error('http');
      err.status = res.status;
      throw err;
    }
    return { data: await res.json() };
  }

  async function loadHistory() {
    hide('stateEmpty');
    hide('stateError');
    hide('stateList');
    showFlex('stateLoading');
    _page = 0;
    _totalPages = 1;

    try {
      const result = await fetchPage(1);

      if (result.unauthorized) {
        localStorage.removeItem('mynutri_user');
        hide('stateLoading');
        const empty = document.getElementById('stateEmpty');
        empty.querySelector('.state-title').textContent = 'Faça login para ver seu histórico';
        empty.querySelector('.state-subtitle').textContent = 'Entre na sua conta para acessar seus planos alimentares gerados.';
        empty.querySelector('a').href = '/auth/';
        empty.querySelector('a').textContent = 'Entrar na conta';
        showFlex('stateEmpty');
        return;
      }

      const data  = result.data;
      const plans = Array.isArray(data) ? data : (data.results || []);   // suporte ao formato legado
      hide('stateLoading');

      if (!plans.length) {
        showFlex('stateEmpty');
        return;
      }

      _page       = toNumber(data.page, 1) || 1;
      _totalPages = toNumber(data.total_pages, 1) || 1;

      const count = toNumber(data.count, plans.length);
      document.getElementById('countText').textContent = `${count} ${count === 1 ? 'dieta gerada' : 'dietas geradas'}`;

      const list = document.getElementById('historyList');
      list.innerHTML = '';
      plans.forEach(function (plan) { list.appendChild(buildCard(plan)); });

      show('stateList');
      updateLoadMore();

    } catch (err) {
      hide('stateLoading');
      document.getElementById('errorMsg').textContent =
        friendlyMessage(err && err.status ? err.status : 'network', 'Não foi possível carregar o histórico.');
      showFlex('stateError');
    }
  }

  async function loadMore() {
    if (_loading || _page >= _totalPages) return;
    _loading = true;
    updateLoadMore();
    try {
      const result = await fetchPage(_page + 1);
      if (result.unauthorized) { window.location.href = '/auth/'; return; }
      const data  = result.data;
      const plans = data.results || [];
      const list  = document.getElementById('historyList');
      let firstNew = null;
      plans.forEach(function (plan) {
        const card = buildCard(plan);
        if (!firstNew) firstNew = card;
        list.appendChild(card);
      });
      _page       = toNumber(data.page, _page + 1);
      _totalPages = toNumber(data.total_pages, _totalPages);
      // Leva o foco para o primeiro item novo (usuário de teclado continua de onde parou)
      if (firstNew) firstNew.focus();
    } catch (err) {
      showToast(friendlyMessage(err && err.status ? err.status : 'network'), 'error');
    } finally {
      _loading = false;
      updateLoadMore();
    }
  }

  if (loadMoreBtn) loadMoreBtn.addEventListener('click', loadMore);
  document.getElementById('btnRetry').addEventListener('click', loadHistory);

  initUserMenu({ requireAuth: false, logoutRedirect: '/' });
  loadHistory();
})();
