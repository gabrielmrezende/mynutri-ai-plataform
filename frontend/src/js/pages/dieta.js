(function () {
// Auth guard: loadUser() e fetchExistingDiet() redirecionam para /auth/ se a API retornar 401.
// Não fazemos redirect síncrono aqui para suportar o fluxo de redirect do Google OAuth,
// onde os cookies são setados pelo backend mas o localStorage ainda está vazio.

// ── Emojis por refeição ──
const MEAL_EMOJIS = ['🌅', '🥗', '🍽️', '🥤', '🌙', '🍎', '🥑', '🫐'];

// ── Paletas de cor por refeição (espelha data-meal-color dos cards) ──
// No modo escuro os fundos claros (mcl/mcg/mcb) são trocados por superfícies
// escuras — ver _applyModalPalette(). A cor de destaque (mc) é mantida.
const MODAL_PALETTE_DARK = {
  mcl: '#1f2937',
  mcg: 'linear-gradient(135deg,#161d2a 0%,#111827 100%)',
};
const MODAL_PALETTES = [
  { mc:'#ea580c', mcl:'#fff7ed', mcb:'#fed7aa', mcg:'linear-gradient(135deg,#fff7ed,#ffedd5)' },
  { mc:'#0d9488', mcl:'#f0fdfa', mcb:'#5eead4', mcg:'linear-gradient(135deg,#f0fdfa,#ccfbf1)' },
  { mc:'#16a34a', mcl:'#f0fdf4', mcb:'#86efac', mcg:'linear-gradient(135deg,#f0fdf4,#dcfce7)' },
  { mc:'#7c3aed', mcl:'#fdf4ff', mcb:'#c4b5fd', mcg:'linear-gradient(135deg,#fdf4ff,#f3e8ff)' },
  { mc:'#1d4ed8', mcl:'#eff6ff', mcb:'#93c5fd', mcg:'linear-gradient(135deg,#eff6ff,#dbeafe)' },
  { mc:'#be185d', mcl:'#fdf2f8', mcb:'#f9a8d4', mcg:'linear-gradient(135deg,#fdf2f8,#fce7f3)' },
  { mc:'#0369a1', mcl:'#f0f9ff', mcb:'#7dd3fc', mcg:'linear-gradient(135deg,#f0f9ff,#e0f2fe)' },
  { mc:'#6d28d9', mcl:'#f5f3ff', mcb:'#a78bfa', mcg:'linear-gradient(135deg,#f5f3ff,#ede9fe)' },
];

// ── Estado global ──
let dietData = null;

// ── Estado de regeneração ──
// A regeneração é aplicada no servidor assim que a API responde: a UI mostra a
// nova refeição imediatamente e oferece "Desfazer" (não há etapa de confirmação).
let _currentModalMealIndex = null;
let _currentModalMealId    = null;
let _regenHasUndo          = false;
let _lastRegen             = null;   // { mealIndex, beforeFoods, beforeKcal, afterFoods, afterKcal, remaining }
let _undoInFlight          = null;   // Promise do undo em andamento (troca de refeição aguarda)
let _selectedChip          = null;   // chip element atualmente selecionado
let _loadingMsgTimer       = null;   // intervalo das mensagens de loading

initUserMenu({ requireAuth: false, logoutRedirect: '/' });

/**
 * Nome da refeição para exibição. O backend grava "Almoço (12:30)" (formato
 * usado no PDF); na tela o horário já aparece num selo próprio, então o
 * sufixo é removido quando coincide com time_suggestion.
 */
function mealDisplayName(name, time) {
  const n = String(name || '');
  const suffix = time ? ` (${time})` : '';
  return suffix && n.endsWith(suffix) ? n.slice(0, -suffix.length) : n;
}

function _applyModalPalette(mealIndex) {
  const pal  = MODAL_PALETTES[mealIndex % MODAL_PALETTES.length];
  const dark = document.documentElement.classList.contains('dark');
  const box  = document.getElementById('modalBox');
  box.style.setProperty('--modal-mc',  pal.mc);
  box.style.setProperty('--modal-mcl', dark ? MODAL_PALETTE_DARK.mcl : pal.mcl);
  box.style.setProperty('--modal-mcb', dark ? pal.mc : pal.mcb);
  box.style.setProperty('--modal-mcg', dark ? MODAL_PALETTE_DARK.mcg : pal.mcg);
}

// Reaplica a paleta se o tema mudar com o modal aberto
new MutationObserver(() => {
  if (_currentModalMealIndex !== null && overlay.classList.contains('open')) {
    _applyModalPalette(_currentModalMealIndex);
  }
}).observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });

function _remainingText(n) {
  if (n == null || !Number.isFinite(Number(n))) return '';
  n = Number(n);
  if (n <= 0) return 'Você já usou todas as trocas de hoje para esta dieta.';
  return `${n} troca${n === 1 ? '' : 's'} restante${n === 1 ? '' : 's'} hoje`;
}

function _updateRegenAvailability() {
  const n   = dietData?.regenerations_remaining_today;
  const btn = document.getElementById('btn-regen-meal');
  const out = Number.isFinite(Number(n)) && n != null && Number(n) <= 0;
  if (btn) {
    btn.disabled = out;
    btn.setAttribute('aria-disabled', out ? 'true' : 'false');
  }
  document.getElementById('regen-remaining-text').textContent = _remainingText(n);
}

// ════════════════════════════════
//  SUBSTITUIÇÕES — EDIÇÃO
// ════════════════════════════════

// rawFoods da refeição aberta — necessário para re-filtrar subs no cancelar/salvar
let _currentModalRawFoods = [];

function _subIndexInDiet(food) {
  return (dietData.substitutions || []).findIndex(s => s.food === food);
}

function _computeSubsToShow() {
  const allSubs  = dietData.substitutions || [];
  const foodNames = _currentModalRawFoods.map(f => (f.name || '').toLowerCase());
  const relevant  = allSubs.filter(s =>
    foodNames.some(fn => fn.includes((s.food || '').toLowerCase().split(' ')[0]))
  );
  return relevant.length > 0 ? relevant : allSubs;
}

function renderSubstitutions(container) {
  const subsToShow = _computeSubsToShow();
  if (!subsToShow.length) {
    container.innerHTML = '<p class="sub-empty">Nenhuma substituição registrada para esta refeição.</p>';
    return;
  }

  container.innerHTML = subsToShow.map((s, i) => {
    const idx  = _subIndexInDiet(s.food);
    const alts = (s.alternatives || [])
      .map(a => `<span class="sub-tag">${escapeHtml(a)}</span>`).join('');
    const foodMatch = (s.food || '').match(/^(.*?)\s*\((\d+(?:g|ml|un)?)\)$/i);
    const foodLabel = foodMatch ? escapeHtml(foodMatch[1].trim()) : escapeHtml(s.food);
    const foodQty   = foodMatch ? `<span class="sub-from-qty">${escapeHtml(foodMatch[2])}</span>` : '';
    return `
      <div class="sub-row" data-sub-index="${idx}" style="animation-delay:${i * 0.07}s">
        <div class="sub-from-row">
          <div class="sub-from-wrap">
            <span class="sub-from">${foodLabel}</span>
            ${foodQty}
          </div>
          <button class="sub-edit-btn" data-sub-index="${idx}" title="Editar" aria-label="Editar substituição de ${escapeHtml(s.food)}">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
            </svg>
          </button>
        </div>
        <div class="sub-arrow-row">
          <div class="sub-arrow-line">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
            <span class="sub-by-label">por qualquer um de</span>
          </div>
        </div>
        <div class="sub-tags">${alts}</div>
      </div>`;
  }).join('');

  container.querySelectorAll('.sub-edit-btn').forEach(btn => {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      _openSubEdit(parseInt(btn.dataset.subIndex), container);
    });
  });
}

function _openSubEdit(idx, container) {
  const s   = (dietData.substitutions || [])[idx];
  if (!s) return;
  const row = container.querySelector(`.sub-row[data-sub-index="${idx}"]`);
  if (!row) return;

  row.outerHTML = `
    <div class="sub-row sub-row--editing" data-sub-index="${idx}">
      <div class="sub-edit-fields">
        <div class="sub-edit-field">
          <span class="sub-edit-label">Alimento</span>
          <input class="sub-edit-input" id="sub-food-${idx}" type="text"
                 value="${escapeHtml(s.food)}" maxlength="100" placeholder="Nome do alimento" />
        </div>
        <div class="sub-edit-field">
          <span class="sub-edit-label">Substituições</span>
          <input class="sub-edit-input" id="sub-alts-${idx}" type="text"
                 value="${escapeHtml((s.alternatives || []).join(', '))}" maxlength="500"
                 placeholder="Ex: Batata, Macarrão, Mandioca" />
          <span class="sub-edit-hint">Separe as opções por vírgula.</span>
        </div>
      </div>
      <div class="sub-edit-actions">
        <button class="sub-btn-save"   id="sub-save-${idx}">Salvar</button>
        <button class="sub-btn-cancel" id="sub-cancel-${idx}">Cancelar</button>
      </div>
    </div>`;

  const foodInput = document.getElementById(`sub-food-${idx}`);
  const altsInput = document.getElementById(`sub-alts-${idx}`);
  const saveBtn   = document.getElementById(`sub-save-${idx}`);
  const cancelBtn = document.getElementById(`sub-cancel-${idx}`);

  foodInput.focus();

  saveBtn.addEventListener('click', () => _saveSubEdit(idx, foodInput, altsInput, saveBtn, container));
  cancelBtn.addEventListener('click', () => renderSubstitutions(container));

  [foodInput, altsInput].forEach(input => {
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter')  { e.preventDefault(); saveBtn.click(); }
      if (e.key === 'Escape') { e.stopPropagation(); cancelBtn.click(); }
    });
  });
}

async function _saveSubEdit(idx, foodInput, altsInput, saveBtn, container) {
  const food = foodInput.value.trim();
  const alts = altsInput.value.split(',').map(a => a.trim()).filter(Boolean);

  if (!food) {
    foodInput.classList.add('invalid');
    foodInput.focus();
    setTimeout(() => foodInput.classList.remove('invalid'), 2000);
    return;
  }
  if (!alts.length) {
    altsInput.classList.add('invalid');
    altsInput.focus();
    setTimeout(() => altsInput.classList.remove('invalid'), 2000);
    return;
  }

  saveBtn.disabled     = true;
  saveBtn.textContent  = 'Salvando…';

  const updatedSubs = [...(dietData.substitutions || [])];
  updatedSubs[idx]  = { food, alternatives: alts };

  try {
    const res = await apiFetch(`${API_BASE}/diet/${dietData.id}/substitutions`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ substitutions: updatedSubs }),
    });

    if (!res.ok) throw new Error('server');

    const data = await res.json();
    dietData.substitutions = data.substitutions;
    renderSubstitutions(container);
    showToast('Substituição atualizada com sucesso!', 'success');
  } catch {
    saveBtn.disabled    = false;
    saveBtn.textContent = 'Salvar';
    showToast('Não foi possível salvar. Tente novamente.', 'error');
  }
}

// ════════════════════════════════
//  MODAL
// ════════════════════════════════
const overlay   = document.getElementById('modal');
const modalBox  = document.getElementById('modalBox');
const closeBtn  = document.getElementById('modalClose');

// ── Chat helpers ──
function _addChatMessage(text, role = 'bot', isTyping = false) {
  const container = document.getElementById('chat-messages');
  const msg = document.createElement('div');
  msg.className = `chat-msg chat-msg--${role}${isTyping ? ' chat-msg--typing' : ''}`;
  msg.innerHTML = `<div class="chat-bubble">${escapeHtml(text)}</div>`;
  container.appendChild(msg);
  container.scrollTop = container.scrollHeight;
  return msg;
}

function _clearChatMessages() {
  const container = document.getElementById('chat-messages');
  if (container) container.innerHTML = '';
}

// ── Chat Dock helpers (declarados cedo para uso em _initChat) ──
function openChatDock() {
  const toggle = document.getElementById('chat-dock-toggle');
  const panel  = document.getElementById('chat-dock-panel');
  if (!toggle || !panel) return;
  toggle.setAttribute('aria-expanded', 'true');
  panel.classList.add('open');
  requestAnimationFrame(() => panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' }));
}

function closeChatDock() {
  const toggle = document.getElementById('chat-dock-toggle');
  const panel  = document.getElementById('chat-dock-panel');
  if (!toggle || !panel) return;
  toggle.setAttribute('aria-expanded', 'false');
  panel.classList.remove('open');
}

function _setDockHint(text) {
  const el = document.getElementById('chat-dock-hint');
  if (el) el.textContent = text;
}

function _initChat() {
  _clearChatMessages();
  _addChatMessage('Olá! Não gostou desta refeição? Me diga o motivo e gero uma nova opção pra você.', 'bot');
  _setDockHint('Não gostou? Posso trocar esta refeição');
  closeChatDock();
}

function _resetRegenSection(keepUndo) {
  document.getElementById('regen-idle-state').style.display    = 'block';
  document.getElementById('regen-loading-state').style.display = 'none';
  document.getElementById('regen-diff-state').style.display    = 'none';
  clearInterval(_loadingMsgTimer);
  if (!keepUndo) {
    document.getElementById('regen-reason').value               = '';
    document.getElementById('btn-undo-meal').style.display      = 'none';
    document.querySelectorAll('.chat-chip').forEach(c => c.classList.remove('selected'));
    _regenHasUndo = false;
    _lastRegen    = null;
    _selectedChip = null;
    _initChat();
  } else {
    document.getElementById('btn-undo-meal').style.display = 'inline-flex';
  }
  _updateRegenAvailability();
}

function _startLoadingMessages() {
  const msgs = [
    'Analisando seus macros...',
    'Buscando alternativas nutritivas...',
    'Equilibrando proteínas e carboidratos...',
    'Quase pronto...',
  ];
  let i = 0;
  const el = document.getElementById('regen-loading-text');
  if (el) el.textContent = msgs[0];
  _loadingMsgTimer = setInterval(() => {
    i = (i + 1) % msgs.length;
    if (el) el.textContent = msgs[i];
  }, 1600);
}

function _addUserMessageToChat(reason) {
  const text = reason || 'Gerar nova sugestão';
  _addChatMessage(text, 'user');
}

function _showRegenDiff(beforeFoods, beforeKcal, afterFoods, afterKcal, remaining) {
  document.getElementById('regen-idle-state').style.display = 'none';
  document.getElementById('regen-diff-state').style.display = 'block';

  function buildList(foods, kcal) {
    const MAX   = 5;
    const slice = foods.slice(0, MAX);
    const more  = foods.length - MAX;
    const kcalNum = Number(kcal);
    return slice.map(f => {
      const qty = toNumber(f.quantity_g, 0);
      return `<div class="regen-diff-food">
        <span class="regen-diff-dot" aria-hidden="true"></span>
        ${escapeHtml(f.name || '')}${qty ? `<span class="regen-diff-qty">${qty}g</span>` : ''}
      </div>`;
    }).join('') +
    (more > 0 ? `<div class="regen-diff-food regen-diff-more">+${more} mais</div>` : '') +
    `<div class="regen-diff-kcal"><span aria-hidden="true">🔥</span> ${Number.isFinite(kcalNum) ? kcalNum : '—'} kcal</div>`;
  }

  document.getElementById('regen-diff-before').innerHTML = buildList(beforeFoods, beforeKcal);
  document.getElementById('regen-diff-after').innerHTML  = buildList(afterFoods,  afterKcal);

  document.getElementById('regen-diff-remaining').textContent = _remainingText(remaining);
}

let _modalTrigger = null;   // elemento que abriu o modal (recebe o foco de volta)

async function openModal(mealIndex) {
  // Um "Desfazer" em andamento precisa terminar antes de trocar de refeição,
  // senão o estado local e o do servidor ficam dessincronizados.
  if (_undoInFlight) {
    try { await _undoInFlight; } catch { /* erro já exibido */ }
  }

  // Troca de refeição → a troca anterior já está salva; só some o botão de desfazer
  if (_currentModalMealIndex !== mealIndex) {
    _regenHasUndo = false;
    _lastRegen    = null;
  }
  _currentModalMealIndex = mealIndex;
  _currentModalMealId    = dietData.refeicoes[mealIndex]?.id ?? null;

  const refeicao  = dietData.refeicoes[mealIndex];
  const rawMeal   = (dietData.meals_raw || [])[mealIndex] || {};
  const emoji     = MEAL_EMOJIS[mealIndex % MEAL_EMOJIS.length];

  // ── Aplicar paleta de cor no modal ──
  _applyModalPalette(mealIndex);

  // ── Header ──
  document.getElementById('modal-emoji').textContent     = emoji;
  document.getElementById('modal-order').textContent     = `Refeição ${mealIndex + 1}`;
  document.getElementById('modal-title').textContent     = mealDisplayName(refeicao.nome_refeicao, rawMeal.time_suggestion);
  document.getElementById('modal-kcal-text').textContent = `${toNumber(refeicao.calorias_estimadas, 0)} kcal`;

  const timeSuggestion = rawMeal.time_suggestion || '';
  const timeEl = document.getElementById('modal-time');
  if (timeSuggestion) {
    document.getElementById('modal-time-text').textContent = timeSuggestion;
    timeEl.style.display = 'inline-flex';
  } else {
    timeEl.style.display = 'none';
  }

  // ── Food items ──
  const foodsContainer = document.getElementById('foods-tbody');
  const rawFoods = rawMeal.foods || [];

  if (rawFoods.length > 0) {
    foodsContainer.innerHTML = rawFoods.map((f, idx) => {
      const hasMacros = f.protein_g != null || f.carbs_g != null || f.fat_g != null;
      const macrosHTML = hasMacros ? `
        <div class="food-item-macros">
          <div class="food-mpill p">
            <span class="food-mpill-val">${Math.round(f.protein_g || 0)}<small>g</small></span>
            <span class="food-mpill-lbl">Prot</span>
          </div>
          <div class="food-mpill c">
            <span class="food-mpill-val">${Math.round(f.carbs_g || 0)}<small>g</small></span>
            <span class="food-mpill-lbl">Carb</span>
          </div>
          <div class="food-mpill f">
            <span class="food-mpill-val">${Math.round(f.fat_g || 0)}<small>g</small></span>
            <span class="food-mpill-lbl">Gord</span>
          </div>
        </div>` : '';
      const kcal = f.calories != null && Number.isFinite(Number(f.calories)) ? Number(f.calories) : null;
      const inner = `
            <span class="food-item-info">
              <span class="food-item-name">${escapeHtml(f.name || '—')}</span>
              ${f.quantity ? `<span class="food-item-qty">${escapeHtml(f.quantity)}</span>` : ''}
            </span>
            <span class="food-item-right">
              ${kcal != null ? `<span class="food-item-kcal">${kcal}<span> kcal</span></span>` : ''}
              ${hasMacros ? `<svg class="food-item-chevron" aria-hidden="true" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>` : ''}
            </span>`;
      // Itens com macros são expansíveis: o cabeçalho é um <button> com aria-expanded
      const main = hasMacros
        ? `<button type="button" class="food-item-main food-item-toggle" aria-expanded="false" aria-controls="food-macros-${idx}">${inner}</button>`
        : `<div class="food-item-main">${inner}</div>`;
      return `
        <div class="food-item" style="animation-delay:${idx * 0.06}s" data-has-macros="${hasMacros}">
          ${main}
          ${hasMacros ? macrosHTML.replace('class="food-item-macros"', `class="food-item-macros" id="food-macros-${idx}"`) : ''}
        </div>`;
    }).join('');

    foodsContainer.querySelectorAll('.food-item-toggle').forEach(btn => {
      btn.addEventListener('click', () => {
        const item     = btn.closest('.food-item');
        const expanded = item.classList.toggle('fi-expanded');
        btn.setAttribute('aria-expanded', expanded ? 'true' : 'false');
      });
    });

  } else {
    const lines = (refeicao.descricao_refeicao || '').split('\n').filter(l => l.trim().startsWith('•'));
    if (lines.length > 0) {
      foodsContainer.innerHTML = lines.map((line, idx) => {
        const clean = line.replace(/^•\s*/, '').trim();
        const [name, qty = ''] = clean.split(/\s+—\s+/);
        return `<div class="food-item" style="animation-delay:${idx * 0.06}s">
          <div class="food-item-main">
            <div class="food-item-info">
              <span class="food-item-name">${escapeHtml(name)}</span>
              ${qty ? `<span class="food-item-qty">${escapeHtml(qty)}</span>` : ''}
            </div>
          </div>
        </div>`;
      }).join('');
    } else {
      foodsContainer.innerHTML = `<p class="food-item-empty">Informação não disponível</p>`;
    }
  }

  // ── Macros no header ──
  let protein = 0, carbs = 0, fat = 0, hasMacros = false;
  rawFoods.forEach(f => {
    if (f.protein_g != null || f.carbs_g != null || f.fat_g != null) {
      hasMacros = true;
      protein += f.protein_g || 0;
      carbs   += f.carbs_g   || 0;
      fat     += f.fat_g     || 0;
    }
  });

  if (!hasMacros && dietData.macros && dietData.calorias_totais) {
    const share = (refeicao.calorias_estimadas || 0) / dietData.calorias_totais;
    protein = Math.round((dietData.macros.protein_g || 0) * share);
    carbs   = Math.round((dietData.macros.carbs_g   || 0) * share);
    fat     = Math.round((dietData.macros.fat_g     || 0) * share);
    hasMacros = true;
  }

  const headerMacros = document.getElementById('modal-header-macros');
  if (hasMacros) {
    document.getElementById('mhm-protein').textContent = Math.round(protein);
    document.getElementById('mhm-carbs').textContent   = Math.round(carbs);
    document.getElementById('mhm-fat').textContent     = Math.round(fat);
    headerMacros.style.display = 'flex';
  } else {
    headerMacros.style.display = 'none';
  }

  // ── Substituições ──
  _currentModalRawFoods = rawFoods;
  renderSubstitutions(document.getElementById('modal-subs'));

  // ── Dicas da refeição (meal_notes individual > fallback notas globais) ──
  const mealNotes   = rawMeal.meal_notes || '';
  const globalNotes = dietData.notes || '';
  const notesText   = mealNotes || globalNotes;
  const notesSection = document.getElementById('modal-notes-section');
  if (notesText) {
    notesSection.style.display = 'block';
    document.getElementById('modal-notes-text').textContent = notesText;
  } else {
    notesSection.style.display = 'none';
  }

  // ── Regeneração — reset (preserva undo se já estava aberto) ──
  _resetRegenSection(_regenHasUndo);

  // Se acabou de haver uma troca nesta refeição, reexibe o comparativo (ex: modal fechado e reaberto)
  if (_lastRegen && _lastRegen.mealIndex === mealIndex) {
    _showRegenDiff(
      _lastRegen.beforeFoods, _lastRegen.beforeKcal,
      _lastRegen.afterFoods,  _lastRegen.afterKcal,
      _lastRegen.remaining,
    );
  }

  if (overlay.classList.contains('open')) return;   // só atualizou o conteúdo

  // ── Scroll to top and open ──
  _modalTrigger = document.activeElement;
  document.getElementById('modal-body').scrollTop = 0;
  overlay.inert = false;
  overlay.classList.add('open');

  // Scroll lock seguro: overflow:hidden no <html> não quebra position:fixed.
  // (position:fixed no body criaria um novo containing block quebrando o overlay)
  document.documentElement.classList.add('modal-open');

  closeBtn.focus();
}

function closeModal() {
  overlay.classList.remove('open');
  overlay.inert = true;
  document.documentElement.classList.remove('modal-open');
  if (_modalTrigger && document.contains(_modalTrigger)) _modalTrigger.focus();
  _modalTrigger = null;
}

overlay.inert = true;
closeBtn.addEventListener('click', closeModal);
overlay.addEventListener('click', e => { if (e.target === overlay) closeModal(); });
document.addEventListener('keydown', e => {
  if (!overlay.classList.contains('open')) return;
  if (e.key === 'Escape') {
    // ESC dentro de campo de edição de substituição é tratado pelo próprio campo
    if (e.target.classList && e.target.classList.contains('sub-edit-input')) return;
    closeModal();
    return;
  }
  trapFocus(e, modalBox);
});

// ════════════════════════════════
//  REGENERAÇÃO DE REFEIÇÃO
// ════════════════════════════════

function _isOffTopicReason(text) {
  if (!text) return false;
  // Rejeita mensagens que claramente não são sobre a refeição.
  // Heurística: presença de palavras-chave de outros domínios sem nenhuma
  // palavra relacionada a comida/dieta.
  const foodWords = [
    'refeição','comida','alimento','ingrediente','proteína','caloria','dieta',
    'café','almoço','jantar','lanche','frango','carne','peixe','ovo','arroz',
    'feijão','massa','salada','fruta','iogurte','pão','queijo','sabor','gosto',
    'prático','simples','barato','caro','ingrediente','receita','preparo',
  ];
  const lc = text.toLowerCase();
  const hasFoodWord = foodWords.some(w => lc.includes(w));
  if (hasFoodWord) return false;

  const offTopicPatterns = [
    /f[oó]rmula/i, /equa[cç][aã]o/i, /matem[aá]tica/i, /f[ií]sica/i,
    /qu[ií]mica/i, /hist[oó]ria/i, /geograf[ií]a/i, /pol[ií]tica/i,
    /programa[cç][aã]o/i, /c[oó]digo/i, /javascript/i, /python/i,
    /me (informe|explique|ensine|conte|diga)/i,
    /o que [eé]/i, /como funciona/i, /quem [eé]/i,
    /baskara/i, /pitagoras/i,
  ];
  return offTopicPatterns.some(p => p.test(text));
}

async function regenerateMeal() {
  if (!_currentModalMealId || !dietData?.id) return;

  const reason = (document.getElementById('regen-reason').value || '').trim();
  const idx    = _currentModalMealIndex;

  // Bloqueia mensagens fora do contexto de refeição antes de chamar a API
  if (_isOffTopicReason(reason)) {
    openChatDock();
    _addUserMessageToChat(reason);
    _addChatMessage(
      'Só consigo ajudar com a sua refeição. Me diga, por exemplo, se quer algo mais prático, se não tem algum ingrediente ou se prefere outro sabor.',
      'bot',
    );
    return;
  }

  // Snapshot "antes" — exibido no comparativo após a troca
  const beforeRaw   = (dietData.meals_raw || [])[idx] || {};
  const beforeFoods = (beforeRaw.foods || []).slice(0, 6);
  const beforeKcal  = dietData.refeicoes[idx]?.calorias_estimadas ?? '—';

  // Adiciona mensagem do usuário e abre o dock
  openChatDock();
  _addUserMessageToChat(reason || 'Gerar nova sugestão');
  _setDockHint('Gerando nova sugestão...');

  document.getElementById('regen-idle-state').style.display    = 'none';
  document.getElementById('regen-loading-state').style.display = 'block';
  _startLoadingMessages();

  try {
    const res = await apiFetch(
      `${API_BASE}/diet/${dietData.id}/meal/${_currentModalMealId}/regenerate`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason }),
      },
    );

    const data = await safeJson(res);
    clearInterval(_loadingMsgTimer);

    if (!res.ok || !data || !data.meal) {
      document.getElementById('regen-loading-state').style.display = 'none';
      document.getElementById('regen-idle-state').style.display    = 'block';
      let msg;
      if (res.status === 429) {
        msg = 'Você já usou todas as trocas de hoje para esta dieta. Tente novamente amanhã.';
        dietData.regenerations_remaining_today = 0;
        _updateRegenAvailability();
      } else {
        msg = apiErrorMessage(res.status, data, 'Não consegui gerar uma nova sugestão. Tente novamente.');
      }
      _addChatMessage(msg, 'bot');
      _setDockHint('Não gostou? Posso trocar esta refeição');
      showToast(msg, 'error');
      return;
    }

    // A troca JÁ foi salva no servidor: aplica na UI imediatamente e oferece "Desfazer"
    const afterRaw   = data.meals_raw_entry || {};
    const afterFoods = (afterRaw.foods || []).slice(0, 6);
    const afterKcal  = toNumber(data.meal.calories, 0);
    const remaining  = data.regenerations_remaining != null ? toNumber(data.regenerations_remaining, 0) : null;
    if (remaining != null) dietData.regenerations_remaining_today = remaining;

    _applyMealUpdate(idx, data);

    _lastRegen    = { mealIndex: idx, beforeFoods, beforeKcal, afterFoods, afterKcal, remaining };
    _regenHasUndo = true;

    _flashMealCard(idx);
    openModal(idx);   // modal já aberto: só atualiza o conteúdo e reexibe o comparativo

    _addChatMessage(`Pronto! Troquei esta refeição por uma opção com ${afterKcal} kcal. A troca já foi salva no seu plano — se preferir a anterior, use "Desfazer troca".`, 'bot');
    _setDockHint('Troca aplicada — você pode desfazer');
    showToast('Refeição trocada e salva.', 'success');

  } catch {
    clearInterval(_loadingMsgTimer);
    document.getElementById('regen-loading-state').style.display = 'none';
    document.getElementById('regen-idle-state').style.display    = 'block';
    _addChatMessage(friendlyMessage('network'), 'bot');
    showToast(friendlyMessage('network'), 'error');
  }
}

/** Atualiza o estado local e a página com a refeição devolvida pela API (regenerar/desfazer). */
function _applyMealUpdate(idx, apiData) {
  dietData.refeicoes[idx] = {
    id:                 apiData.meal.id,
    nome_refeicao:      apiData.meal.meal_name,
    descricao_refeicao: apiData.meal.description,
    calorias_estimadas: apiData.meal.calories,
    order:              apiData.meal.order,
  };
  if (dietData.meals_raw && apiData.meals_raw_entry) dietData.meals_raw[idx] = apiData.meals_raw_entry;
  if (apiData.total_calories != null) dietData.calorias_totais = apiData.total_calories;
  if (apiData.macros) dietData.macros = apiData.macros;

  renderMealCards(dietData.refeicoes);
  renderMacrosBar(dietData.macros, dietData.calorias_totais);
  document.getElementById('stat-calories').textContent =
    toNumber(dietData.calorias_totais, 0).toLocaleString('pt-BR');
}

function _flashMealCard(idx) {
  requestAnimationFrame(() => {
    const card = document.querySelectorAll('.meal-card')[idx];
    if (card) {
      card.classList.remove('regen-flash');
      void card.offsetWidth;
      card.classList.add('regen-flash');
      setTimeout(() => card.classList.remove('regen-flash'), 1100);
    }
  });
}

/** Fecha o comparativo mantendo a troca (já salva) e o botão de desfazer. */
function _dismissRegenDiff() {
  _lastRegen = null;
  document.getElementById('regen-diff-state').style.display = 'none';
  document.getElementById('regen-idle-state').style.display = 'block';
  document.getElementById('btn-undo-meal').style.display    = _regenHasUndo ? 'inline-flex' : 'none';
  _setDockHint('Não gostou? Posso trocar esta refeição');
  _updateRegenAvailability();
}

function _setUndoButtonsBusy(busy) {
  ['btn-diff-undo', 'btn-undo-meal', 'btn-diff-keep'].forEach(id => {
    const b = document.getElementById(id);
    if (b) b.disabled = busy;
  });
}

function undoRegeneration() {
  if (_undoInFlight) return _undoInFlight;
  if (!_currentModalMealId || !dietData?.id) return Promise.resolve();

  const idx    = _currentModalMealIndex;
  const mealId = _currentModalMealId;
  _setUndoButtonsBusy(true);
  _setDockHint('Desfazendo a troca...');

  _undoInFlight = (async () => {
    try {
      const res  = await apiFetch(
        `${API_BASE}/diet/${dietData.id}/meal/${mealId}/undo`,
        { method: 'POST' },
      );
      const data = await safeJson(res);

      if (!res.ok || !data || !data.meal) {
        const msg = apiErrorMessage(res.status, data, 'Não foi possível desfazer. Tente novamente.');
        showToast(msg, 'error');
        _setDockHint('Troca aplicada — você pode desfazer');
        return;
      }

      _applyMealUpdate(idx, data);
      _regenHasUndo = false;
      _lastRegen    = null;
      _flashMealCard(idx);
      showToast('Troca desfeita. A refeição anterior voltou ao seu plano.', 'success');

      // Atualiza o modal se ainda estiver nesta refeição
      if (overlay.classList.contains('open') && _currentModalMealIndex === idx) {
        _resetRegenSection(false);
        // re-renderiza o conteúdo do modal sem perder o foco
        _undoInFlight = null;
        await openModal(idx);
      }
    } catch {
      showToast(friendlyMessage('network'), 'error');
    } finally {
      _setUndoButtonsBusy(false);
    }
  })().finally(() => { _undoInFlight = null; });

  return _undoInFlight;
}

document.getElementById('btn-regen-meal').addEventListener('click', regenerateMeal);
document.getElementById('btn-undo-meal').addEventListener('click', undoRegeneration);

// ── Chips de motivo ──
document.getElementById('regen-chips').addEventListener('click', e => {
  const chip = e.target.closest('.chat-chip');
  if (!chip) return;

  if (_selectedChip === chip) {
    chip.classList.remove('selected');
    _selectedChip = null;
    document.getElementById('regen-reason').value = '';
  } else {
    if (_selectedChip) _selectedChip.classList.remove('selected');
    chip.classList.add('selected');
    _selectedChip = chip;
    document.getElementById('regen-reason').value = chip.dataset.reason;
    document.getElementById('regen-reason').focus();
  }
});

// ── Auto-resize do textarea ──
document.getElementById('regen-reason').addEventListener('input', function() {
  this.style.height = 'auto';
  this.style.height = Math.min(this.scrollHeight, 96) + 'px';
  // Deseleciona chip se o usuário digitou algo diferente
  if (_selectedChip && this.value !== _selectedChip.dataset.reason) {
    _selectedChip.classList.remove('selected');
    _selectedChip = null;
  }
});

// ── Enter para enviar (Shift+Enter nova linha) ──
document.getElementById('regen-reason').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    document.getElementById('btn-regen-meal').click();
  }
});

// ── Botões do painel diff ──
document.getElementById('btn-diff-keep').addEventListener('click', _dismissRegenDiff);
document.getElementById('btn-diff-undo').addEventListener('click', undoRegeneration);

// Previne touchmove no fundo do overlay (scroll lock para iOS Safari)
// passive: false é necessário para poder chamar preventDefault()
overlay.addEventListener('touchmove', e => {
  // Permite scroll DENTRO do modal-body, bloqueia fundo
  if (!e.target.closest('#modal-body')) {
    e.preventDefault();
  }
}, { passive: false });

// ════════════════════════════════
//  MODAL DE TRANSPARÊNCIA (IA)
// ════════════════════════════════
const overlayExplain   = document.getElementById('modal-explain');
const closeBtnExplain  = document.getElementById('modalExplainClose');

const EXPLAIN_SECTIONS = [
  {
    key:   'calorie_calculation',
    icon:  '🔥',
    cls:   'calories',
    title: 'Cálculo de Calorias',
    fallback: (d) => {
      const kcal = d.calorias_totais;
      const goal = (d.goal_description || '').toLowerCase();
      const adj  = goal.includes('emagrecimento') ? 'déficit de ~400 kcal'
                 : goal.includes('hipertrofia')   ? 'superávit de ~350 kcal'
                 : 'sem ajuste (manutenção)';
      return `Seu plano foi calculado com base no seu peso, altura, idade e nível de atividade, usando a equação de Mifflin-St Jeor. Com o ajuste para ${adj}, chegamos a ${kcal?.toLocaleString('pt-BR') || '—'} kcal diárias.`;
    },
  },
  {
    key:   'macro_distribution',
    icon:  '📊',
    cls:   'macros',
    title: 'Distribuição de Macros',
    fallback: (d) => {
      const m = d.macros;
      if (!m) return 'Os macronutrientes foram distribuídos de forma equilibrada para atender ao seu objetivo nutricional.';
      return `Seu plano contém ${m.protein_g}g de proteína, ${m.carbs_g}g de carboidratos e ${m.fat_g}g de gordura. Essa distribuição foi ajustada de acordo com seu objetivo para garantir equilíbrio energético e nutricional.`;
    },
  },
  {
    key:   'food_choices',
    icon:  '🥗',
    cls:   'foods',
    title: 'Escolha dos Alimentos',
    fallback: (_) => 'Os alimentos foram selecionados priorizando seus alimentos preferidos, combinados com outros ingredientes para garantir variedade nutricional e praticidade no dia a dia brasileiro.',
  },
  {
    key:   'meal_structure',
    icon:  '🕐',
    cls:   'structure',
    title: 'Estrutura das Refeições',
    fallback: (d) => {
      const n = d.refeicoes?.length || '—';
      return `Seu plano foi dividido em ${n} refeições distribuídas ao longo do dia para manter o metabolismo ativo, controlar o apetite e facilitar a adesão à dieta no cotidiano.`;
    },
  },
  {
    key:   'goal_alignment',
    icon:  '🎯',
    cls:   'goal',
    title: 'Alinhamento com seu Objetivo',
    fallback: (d) => {
      const goal = d.goal_description || 'seu objetivo';
      return `Este plano foi montado especificamente para: ${goal}. Com consistência no dia a dia, ele ajuda você a caminhar nessa direção — ajuste com um profissional sempre que precisar.`;
    },
  },
];

// Converte texto longo em parágrafos separados.
// Quebra em ". " seguido de letra maiúscula, preservando frações decimais (1,55 × 1,5 etc.)
// O texto vem da IA/API: sempre escapado antes de ir para innerHTML.
function textToParas(text) {
  if (!text) return '<p class="explain-text explain-text--empty">Informação não disponível.</p>';
  // Divide nos pontos que terminam frases (". " + maiúscula), preservando "Ex:", decimais etc.
  const sentences = String(text).split(/(?<=\w\.) (?=[A-ZÁÉÍÓÚÂÊÎÔÛÃẼĨÕŨÀÈÌÒÙÇ])/u);
  // Agrupa em parágrafos de 2 frases cada para leitura mais fácil
  const paras = [];
  for (let i = 0; i < sentences.length; i += 2) {
    const chunk = [sentences[i], sentences[i + 1]].filter(Boolean).join(' ');
    paras.push(`<p class="explain-text">${escapeHtml(chunk)}</p>`);
  }
  return paras.join('');
}

let _explainTrigger = null;

function openExplainModal() {
  const expl = dietData?.explanation;
  const body = document.getElementById('modal-explain-body');

  body.innerHTML = EXPLAIN_SECTIONS.map(sec => {
    const text = (expl && expl[sec.key]) ? expl[sec.key] : sec.fallback(dietData);
    return `
      <div class="explain-section">
        <div class="explain-section-header">
          <div class="explain-icon ${sec.cls}" aria-hidden="true">${sec.icon}</div>
          <h3 class="explain-section-title">${sec.title}</h3>
        </div>
        ${textToParas(text)}
      </div>
    `;
  }).join('');

  body.scrollTop = 0;
  _explainTrigger = document.activeElement;
  overlayExplain.inert = false;
  overlayExplain.classList.add('open');
  document.documentElement.classList.add('modal-open');
  closeBtnExplain.focus();
}

function closeExplainModal() {
  overlayExplain.classList.remove('open');
  overlayExplain.inert = true;
  document.documentElement.classList.remove('modal-open');
  if (_explainTrigger && document.contains(_explainTrigger)) _explainTrigger.focus();
  _explainTrigger = null;
}

overlayExplain.inert = true;
document.getElementById('btn-explain').addEventListener('click', openExplainModal);
closeBtnExplain.addEventListener('click', closeExplainModal);
overlayExplain.addEventListener('click', e => { if (e.target === overlayExplain) closeExplainModal(); });
document.addEventListener('keydown', e => {
  if (!overlayExplain.classList.contains('open')) return;
  if (e.key === 'Escape') { closeExplainModal(); return; }
  trapFocus(e, document.getElementById('modalExplainBox'));
});

overlayExplain.addEventListener('touchmove', e => {
  if (!e.target.closest('#modal-explain-body')) e.preventDefault();
}, { passive: false });

// ════════════════════════════════
//  RENDER PAGE
// ════════════════════════════════

// Esconde o botão de sair durante a geração
function hideCancelButton() {
  const btn = document.getElementById('btn-cancel-generation');
  if (btn) btn.style.display = 'none';
}

// Exibe o botão "Sair e voltar depois" (mostrado durante a geração)
function showCancelButton() {
  const btn = document.getElementById('btn-cancel-generation');
  if (btn) btn.style.display = '';
}

/**
 * @param {string} msg
 * @param {string|null} ctaHref    - href do link secundário (ex: '/questionario/')
 * @param {string|null} ctaLabel   - label do link secundário
 * @param {boolean} showRetry      - exibe botão de nova tentativa (para erros de geração)
 * @param {string} [retryLabel]    - texto do botão de nova tentativa
 */
function showError(msg, ctaHref, ctaLabel, showRetry = false, retryLabel = 'Tentar novamente') {
  stopLoadingTips();
  hideCancelButton();
  _setGenProgressVisible(false);
  document.getElementById('state-loading').style.display = 'none';
  document.getElementById('state-error').style.display   = 'flex';
  document.getElementById('error-msg').textContent = msg;

  const retryBtn = document.getElementById('btn-retry-generation');
  if (retryBtn) retryBtn.style.display = showRetry ? '' : 'none';
  const retryLbl = document.getElementById('btn-retry-label');
  if (retryLbl) retryLbl.textContent = retryLabel;

  const cta = document.getElementById('error-cta');
  if (cta && ctaHref) {
    cta.href          = ctaHref;
    cta.textContent   = ctaLabel || 'Continuar';
    cta.style.display = '';
  } else if (cta) {
    cta.style.display = 'none';
  }
}

/**
 * @param macros     gramas de proteína/carboidrato/gordura do plano
 * @param planKcal   total de kcal do plano (soma das kcal de cada alimento na
 *                   base nutricional). Os % usam o fator Atwater (4/4/9 kcal/g),
 *                   que difere um pouco desse total — por isso o total exibido é
 *                   o do plano, igual ao do topo da página.
 */
function renderMacrosBar(macros, planKcal) {
  if (!macros) return;
  const bar = document.getElementById('macros-bar');
  bar.classList.add('visible');

  // Números da API sempre passam por Number() antes de ir para o HTML
  const pg = Math.round(toNumber(macros.protein_g, 0));
  const cg = Math.round(toNumber(macros.carbs_g, 0));
  const fg = Math.round(toNumber(macros.fat_g, 0));

  const pkcal = pg * 4;
  const ckcal = cg * 4;
  const fkcal = fg * 9;
  const total = pkcal + ckcal + fkcal || 1;
  const displayTotal = Math.round(toNumber(planKcal, 0)) || total;

  const ppct = Math.round(pkcal / total * 100);
  const cpct = Math.round(ckcal / total * 100);
  const fpct = 100 - ppct - cpct;

  const items = [
    { cls: 'p', emoji: '🥩', name: 'Proteína',     g: pg, kcal: pkcal, pct: ppct },
    { cls: 'c', emoji: '🌾', name: 'Carboidratos', g: cg, kcal: ckcal, pct: cpct },
    { cls: 'f', emoji: '🥑', name: 'Gordura',      g: fg, kcal: fkcal, pct: fpct },
  ];
  const describe = m => `${m.name}: ${m.g} g, ${m.kcal} kcal (${m.pct}% das calorias)`;

  bar.innerHTML = `
    <div class="mb-top">
      <span class="mb-label">Macros do dia</span>
      <span class="mb-total" id="mb-total-kcal">0 kcal</span>
    </div>
    <div class="mb-split-bar" id="mb-split-bar" role="img" aria-label="${escapeHtml(items.map(describe).join('; '))}">
      <div class="mb-seg p" data-idx="0" style="flex:${ppct}"></div>
      <div class="mb-seg c" data-idx="1" style="flex:${cpct}"></div>
      <div class="mb-seg f" data-idx="2" style="flex:${fpct}"></div>
    </div>
    <div class="mb-legend" aria-hidden="true">
      ${items.map(m => `
        <span class="mb-legend-item">
          <span class="mb-legend-dot ${m.cls}"></span>${m.name} ${m.pct}%
        </span>
      `).join('')}
    </div>
    <div class="mb-cards">
      ${items.map((m, i) => `
        <div class="mb-card ${m.cls}" data-idx="${i}" tabindex="0" aria-label="${escapeHtml(describe(m))}">
          <p class="mb-card-name" aria-hidden="true">${m.emoji} ${m.name}</p>
          <p class="mb-card-value" aria-hidden="true"><span class="mb-count-g" data-target="${m.g}">0</span><span class="mb-card-unit">g</span></p>
          <div class="mb-card-footer" aria-hidden="true">
            <span class="mb-card-kcal"><span class="mb-count-kcal" data-target="${m.kcal}">0</span> kcal</span>
            <span class="mb-card-pct">${m.pct}%</span>
          </div>
          <div class="mb-card-bar"></div>
        </div>
      `).join('')}
    </div>
  `;

  // ── Animated counters (desligados com prefers-reduced-motion) ──
  function easeOut(t) { return 1 - Math.pow(1 - t, 3); }
  function animateCounter(el, target, duration) {
    if (prefersReducedMotion()) { el.textContent = Math.round(target).toLocaleString('pt-BR'); return; }
    const start = performance.now();
    function tick(now) {
      const t = Math.min((now - start) / duration, 1);
      el.textContent = Math.round(easeOut(t) * target).toLocaleString('pt-BR');
      if (t < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  }

  const DURATION = 900;
  bar.querySelectorAll('.mb-count-g').forEach(el =>
    animateCounter(el, toNumber(el.dataset.target, 0), DURATION));
  bar.querySelectorAll('.mb-count-kcal').forEach(el =>
    animateCounter(el, toNumber(el.dataset.target, 0), DURATION));

  // Animate total kcal display
  animateCounter(document.getElementById('mb-total-kcal'), displayTotal, DURATION);
  // Append " kcal" suffix after animation ends
  setTimeout(() => {
    const el = document.getElementById('mb-total-kcal');
    if (el) el.textContent = displayTotal.toLocaleString('pt-BR') + ' kcal';
  }, prefersReducedMotion() ? 0 : DURATION + 50);

  // ── Tooltip + focus/dim interactions (mouse e teclado) ──
  const tooltip = document.getElementById('mb-tooltip');
  const splitBar = document.getElementById('mb-split-bar');
  const segs = splitBar.querySelectorAll('.mb-seg');
  const cards = bar.querySelectorAll('.mb-card');

  function focusMacro(idx) {
    bar.classList.add('has-focus');
    splitBar.classList.add('has-focus');
    segs.forEach((s, i) => s.classList.toggle('mb-focus', i === idx));
    cards.forEach((c, i) => c.classList.toggle('mb-focus', i === idx));
  }
  function clearFocus() {
    bar.classList.remove('has-focus');
    splitBar.classList.remove('has-focus');
    segs.forEach(s => s.classList.remove('mb-focus'));
    cards.forEach(c => c.classList.remove('mb-focus'));
    tooltip.classList.remove('show');
  }

  function showTooltip(idx, x, y) {
    const m = items[idx];
    tooltip.textContent = `${m.name} — ${m.g}g · ${m.kcal} kcal (${m.pct}%)`;
    tooltip.classList.add('show');
    tooltip.style.left = (x + 14) + 'px';
    tooltip.style.top  = (y - 36) + 'px';
  }

  segs.forEach((seg, i) => {
    seg.addEventListener('mouseenter', () => focusMacro(i));
    seg.addEventListener('mouseleave', clearFocus);
    seg.addEventListener('mousemove', e => showTooltip(i, e.clientX, e.clientY));
  });

  cards.forEach((card, i) => {
    card.addEventListener('mouseenter', () => focusMacro(i));
    card.addEventListener('mouseleave', clearFocus);
    card.addEventListener('focus', () => {
      focusMacro(i);
      const r = card.getBoundingClientRect();
      showTooltip(i, r.left, r.top);
    });
    card.addEventListener('blur', clearFocus);
  });
}

function renderMealCards(refeicoes) {
  const grid = document.getElementById('meals-grid');
  grid.innerHTML = '';

  const badge = document.getElementById('meals-count-badge');
  if (badge) badge.textContent = refeicoes.length;

  refeicoes.forEach((r, i) => {
    const rawMeal  = (dietData.meals_raw || [])[i] || {};
    const time     = rawMeal.time_suggestion || null;
    const rawFoods = rawMeal.foods || [];
    const colorIdx = i % 8;
    const kcal     = toNumber(r.calorias_estimadas, 0);

    // Build food chips
    const MAX_CHIPS = 4;
    let chipsHTML = '';
    if (rawFoods.length > 0) {
      const chipItems = rawFoods.slice(0, MAX_CHIPS);
      const moreCount = rawFoods.length - MAX_CHIPS;
      chipsHTML = chipItems.map(f => `<span class="meal-chip">${escapeHtml(f.name)}</span>`).join('');
      if (moreCount > 0) chipsHTML += `<span class="meal-chip-more">+${moreCount}</span>`;
    } else {
      const fallbackItems = (r.descricao_refeicao || '').replace(/•\s*/g, '').split(/[,\n]/).map(s => s.trim()).filter(Boolean).slice(0, 4);
      chipsHTML = fallbackItems.map(s => `<span class="meal-chip">${escapeHtml(s)}</span>`).join('');
    }

    const card = document.createElement('div');
    card.className = 'meal-card';
    card.dataset.mealColor = colorIdx;
    card.style.animationDelay = `${i * 0.08}s`;
    card.tabIndex = 0;
    card.setAttribute('role', 'button');
    card.setAttribute('aria-haspopup', 'dialog');
    const displayName = mealDisplayName(r.nome_refeicao, time) || `Refeição ${i + 1}`;
    card.setAttribute('aria-label', `Ver detalhes de ${displayName}, ${kcal} kcal`);
    card.innerHTML = `
      <div class="meal-card-header">
        <div class="meal-card-header-top">
          <div class="meal-emoji-wrap" aria-hidden="true">${MEAL_EMOJIS[i % MEAL_EMOJIS.length]}</div>
          <span class="meal-kcal-badge">
            <svg aria-hidden="true" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a7 7 0 0 0-7 7c0 5 7 13 7 13s7-8 7-13a7 7 0 0 0-7-7z"/></svg>
            ${kcal} kcal
          </span>
        </div>
        <div class="meal-card-header-bottom">
          <p class="meal-order-label">
            <span class="meal-order-dot"></span>
            Refeição ${i + 1}
          </p>
          <p class="meal-name">${escapeHtml(displayName)}</p>
          ${time ? `<span class="meal-time-tag">
            <svg aria-hidden="true" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            ${escapeHtml(time)}
          </span>` : ''}
        </div>
      </div>
      <div class="meal-card-body">
        <div class="meal-chips">${chipsHTML}</div>
      </div>
      <div class="meal-card-sep"></div>
      <div class="meal-card-footer">
        <div class="meal-detail-link">
          <span>Ver detalhes</span>
          <span class="meal-detail-arrow" aria-hidden="true">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>
          </span>
        </div>
      </div>
    `;
    card.addEventListener('click',   () => openModal(i));
    card.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openModal(i); } });
    grid.appendChild(card);
  });

}

function renderDiet(diet) {
  dietData = diet;
  stopLoadingTips();
  hideCancelButton();
  _setGenProgressVisible(false);
  document.getElementById('state-loading').style.display = 'none';
  document.getElementById('state-error').style.display   = 'none';
  document.getElementById('diet-content').style.display  = 'block';

  const totalKcal = toNumber(diet.calorias_totais, 0);
  document.getElementById('stat-calories').textContent =
    totalKcal ? totalKcal.toLocaleString('pt-BR') : '—';
  document.getElementById('stat-meals').textContent =
    diet.refeicoes?.length || '—';
  document.getElementById('goal-desc').textContent =
    diet.goal_description || 'Plano personalizado';

  if (diet.created_at) {
    const d = new Date(diet.created_at);
    document.getElementById('diet-date').textContent =
      `Dieta gerada em ${d.toLocaleDateString('pt-BR', { day:'2-digit', month:'long', year:'numeric' })}`;
  }

  renderMacrosBar(diet.macros, diet.calorias_totais);
  renderMealCards(diet.refeicoes || []);

  if (diet.notes) {
    document.getElementById('notes-box').classList.add('visible');
    document.getElementById('notes-box-text').textContent = diet.notes;
  }

  // Sempre mostra o botão — o modal tem fallback para dietas antigas sem explanation
  document.getElementById('btn-explain').style.display = 'inline-flex';
}

// ════════════════════════════════
//  LOAD — geração assíncrona com polling
// ════════════════════════════════

// job_id da geração em andamento: guardado na sessão para que um refresh
// retome o polling em vez de disparar outra geração (que gastaria a cota diária).
const JOB_STORAGE_KEY = 'mynutri_diet_job';

function _getStoredJob() {
  try {
    const v = sessionStorage.getItem(JOB_STORAGE_KEY);
    return v && /^\d+$/.test(v) ? v : null;
  } catch { return null; }
}
function _storeJob(jobId) {
  try { sessionStorage.setItem(JOB_STORAGE_KEY, String(jobId)); } catch { /* ignore */ }
}
function _clearStoredJob() {
  try { sessionStorage.removeItem(JOB_STORAGE_KEY); } catch { /* ignore */ }
}

/** Troca a URL sem recarregar, mantendo sempre a rota /dieta/. */
function _setDietUrl(params) {
  const qs = new URLSearchParams(params || {}).toString();
  history.replaceState(null, '', '/dieta/' + (qs ? `?${qs}` : ''));
}

// Mensagens rotativas exibidas enquanto a IA processa
const LOADING_TIPS = [
  'Calculando seu metabolismo basal...',
  'Ajustando macronutrientes ao seu objetivo...',
  'Selecionando alimentos compatíveis com suas restrições...',
  'Distribuindo refeições ao longo do dia...',
  'Verificando equilíbrio calórico...',
  'Montando o plano personalizado...',
  'Finalizando sua dieta...',
];
let _tipIndex = 0;
let _tipInterval = null;

function startLoadingTips() {
  stopLoadingTips();
  const msgEl = document.getElementById('loading-tip');
  if (!msgEl) return;
  _tipIndex = 0;
  msgEl.textContent = LOADING_TIPS[0];
  _tipInterval = setInterval(() => {
    _tipIndex = (_tipIndex + 1) % LOADING_TIPS.length;
    msgEl.textContent = LOADING_TIPS[_tipIndex];
  }, 5000);
}

function stopLoadingTips() {
  if (_tipInterval) { clearInterval(_tipInterval); _tipInterval = null; }
}

// ── Progresso por etapas da geração ──
const GEN_STEPS = ['sent', 'queued', 'processing', 'done'];

function _setGenProgressVisible(visible) {
  const el = document.getElementById('gen-progress');
  if (el) el.hidden = !visible;
}

function _setGenStep(step) {
  const list = document.getElementById('gen-progress');
  if (!list) return;
  const current = GEN_STEPS.indexOf(step);
  list.querySelectorAll('[data-gen-step]').forEach(li => {
    const i = GEN_STEPS.indexOf(li.dataset.genStep);
    li.classList.toggle('is-done', i < current);
    li.classList.toggle('is-current', i === current);
    if (i === current) li.setAttribute('aria-current', 'step'); else li.removeAttribute('aria-current');
  });
  const STEP_TITLES = {
    sent:       'Enviando suas respostas...',
    queued:     'Sua dieta está na fila de geração...',
    processing: 'A IA está montando suas refeições...',
    done:       'Finalizando...',
  };
  document.getElementById('loading-msg').textContent = STEP_TITLES[step] || 'Gerando sua dieta...';
}

function _showGeneratingState() {
  document.getElementById('state-error').style.display   = 'none';
  document.getElementById('diet-content').style.display  = 'none';
  document.getElementById('state-loading').style.display = 'flex';
  document.getElementById('loading-subtitle').textContent =
    'Costuma levar de 1 a 3 minutos. Você pode sair desta página: a geração continua e sua dieta aparecerá em "Minha Dieta" e no Histórico quando ficar pronta.';
  _setGenProgressVisible(true);
  showCancelButton();
  startLoadingTips();
}

let _pollController = null;

function stopPolling() {
  if (_pollController) { _pollController.abort(); _pollController = null; }
}

// Para o polling ao sair da página (evita requisições órfãs)
window.addEventListener('pagehide', stopPolling);
// Voltou pelo histórico (bfcache) no meio de uma geração → retoma o polling
window.addEventListener('pageshow', e => {
  if (e.persisted && !_pollController && _getStoredJob() &&
      document.getElementById('state-loading').style.display !== 'none') {
    loadDiet();
  }
});

class GenerationError extends Error {
  constructor(message, kind) { super(message); this.kind = kind; }
}

function _sleep(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal.aborted) { reject(new DOMException('Aborted', 'AbortError')); return; }
    const t = setTimeout(resolve, ms);
    signal.addEventListener('abort', () => {
      clearTimeout(t);
      reject(new DOMException('Aborted', 'AbortError'));
    }, { once: true });
  });
}

/**
 * Polling do status do job com setTimeout encadeado + backoff + AbortController.
 * Resolve com o diet_plan_id quando o job termina; rejeita com GenerationError.
 */
async function pollJobStatus(jobId) {
  stopPolling();
  const controller = new AbortController();
  _pollController  = controller;
  const signal     = controller.signal;

  const MAX_WAIT_MS   = 5 * 60 * 1000;   // depois disso, oferece "continuar aguardando"
  const MAX_ERRORS    = 5;               // falhas de rede/servidor seguidas toleradas
  const startedAt     = Date.now();
  let delay           = 1500;
  let errors          = 0;

  try {
    for (;;) {
      await _sleep(delay, signal);

      let res;
      try {
        res = await apiFetch(`${API_BASE}/diet/status/${jobId}`, { signal });
      } catch (err) {
        if (err.name === 'AbortError') throw err;
        if (++errors >= MAX_ERRORS) throw new GenerationError(friendlyMessage('network'), 'network');
        delay = Math.min(delay * 2, 15000);
        continue;
      }

      if (res.status === 401) throw new GenerationError(friendlyMessage(401), 'auth');
      if (res.status === 404) {
        throw new GenerationError('Não encontramos esta geração de dieta. Ela pode ter expirado.', 'not_found');
      }
      if (!res.ok) {
        if (++errors >= MAX_ERRORS) throw new GenerationError(friendlyMessage(res.status), 'server');
        delay = Math.min(delay * 2, 15000);
        continue;
      }

      errors = 0;
      const data = await safeJson(res) || {};

      if (data.status === 'done' && data.diet_plan_id) return data.diet_plan_id;
      if (data.status === 'failed') {
        throw new GenerationError(data.error || 'Não foi possível gerar sua dieta. Tente novamente.', 'failed');
      }

      _setGenStep(data.status === 'processing' ? 'processing' : 'queued');

      if (Date.now() - startedAt > MAX_WAIT_MS) {
        throw new GenerationError(
          'A geração está demorando mais que o normal. Você pode continuar aguardando ou voltar mais tarde — sua dieta aparecerá no Histórico quando ficar pronta.',
          'timeout',
        );
      }

      // Backoff suave: 1,5s → … → no máximo 8s entre consultas
      delay = Math.min(Math.round(delay * 1.3), 8000);
    }
  } finally {
    if (_pollController === controller) _pollController = null;
  }
}

/** Busca o plano pronto, renderiza e fixa a URL em /dieta/?id=<id>. */
async function _finishWithPlan(planId) {
  _clearStoredJob();
  _setGenStep('done');
  const planRes = await apiFetch(`${API_BASE}/diet/${planId}`);
  if (!planRes.ok) {
    showError('Sua dieta foi gerada, mas não conseguimos exibi-la agora. Abra o Histórico para vê-la.', '/historico/', 'Ver histórico');
    return;
  }
  renderDiet(await planRes.json());
  _setDietUrl({ id: planId });
}

/** Acompanha um job (novo ou retomado) até terminar e trata os erros. */
async function _followJob(jobId) {
  _storeJob(jobId);
  _setDietUrl({ job: jobId });
  _showGeneratingState();
  _setGenStep('queued');

  try {
    const planId = await pollJobStatus(jobId);
    await _finishWithPlan(planId);
  } catch (err) {
    if (err && err.name === 'AbortError') return;   // saiu da página
    const kind = err && err.kind;
    if (kind === 'auth') { window.location.href = '/auth/'; return; }
    if (kind === 'failed' || kind === 'not_found') {
      _clearStoredJob();
      _setDietUrl({});
    }
    showError(
      (err && err.message) || friendlyMessage('default'),
      '/questionario/', 'Refazer questionário',
      true,
      kind === 'timeout' || kind === 'network' || kind === 'server' ? 'Continuar aguardando' : 'Tentar novamente',
    );
  }
}

async function generateDiet() {
  _showGeneratingState();
  _setGenStep('sent');

  let jobData;
  try {
    const dr = await apiFetch(`${API_BASE}/diet/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    });
    jobData = await safeJson(dr);
    if (!dr.ok || !jobData || !jobData.job_id) {
      if (dr.status === 429) {
        showError('Você já gerou o máximo de dietas permitido por hoje. Suas dietas anteriores continuam disponíveis no Histórico.', '/historico/', 'Ver histórico');
      } else {
        showError(apiErrorMessage(dr.status, jobData, 'Não foi possível iniciar a geração. Tente novamente.'), '/questionario/', 'Refazer questionário', true);
      }
      return;
    }
  } catch {
    showError(friendlyMessage('network'), '/questionario/', 'Refazer questionário', true);
    return;
  }

  // Modo síncrono (dev sem Redis): job já está done
  if (jobData.status === 'done' && jobData.diet_plan_id) {
    await _finishWithPlan(jobData.diet_plan_id);
    return;
  }

  await _followJob(jobData.job_id);
}

/**
 * "Tentar novamente" / "Continuar aguardando": antes de gerar outra dieta,
 * verifica o job atual — se ainda estiver em andamento (ou pronto), reaproveita.
 */
async function retryGeneration() {
  const jobId = _getStoredJob();
  if (!jobId) { await generateDiet(); return; }

  _showGeneratingState();
  try {
    const res  = await apiFetch(`${API_BASE}/diet/status/${jobId}`);
    const data = await safeJson(res);
    if (res.ok && data) {
      if (data.status === 'done' && data.diet_plan_id) { await _finishWithPlan(data.diet_plan_id); return; }
      if (data.status === 'pending' || data.status === 'processing') { await _followJob(jobId); return; }
    }
    if (res.status === 401) { window.location.href = '/auth/'; return; }
  } catch {
    showError(friendlyMessage('network'), '/questionario/', 'Refazer questionário', true, 'Continuar aguardando');
    return;
  }
  // Job falhou ou não existe mais → gera um novo
  _clearStoredJob();
  await generateDiet();
}

async function loadDiet() {
  const params   = new URLSearchParams(window.location.search);
  const generate = params.get('generate');
  const jobParam = params.get('job');
  const idParam  = params.get('id');

  // 1. Retoma uma geração em andamento (refresh ou volta à página)
  const resumeJob = (jobParam && /^\d+$/.test(jobParam)) ? jobParam
                  : (!idParam && generate !== '1' ? _getStoredJob() : null);
  if (resumeJob) {
    await _followJob(resumeJob);
    return;
  }

  if (generate === '1') {
    _showGeneratingState();
    _setGenStep('sent');

    // 2. Envia anamnese pendente se houver (fluxo de login intermediário)
    const pending = sessionStorage.getItem('anamneseData');
    if (pending) {
      try {
        const ar = await apiFetch(`${API_BASE}/anamnese`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: pending,
        });
        if (!ar.ok) {
          const e = await safeJson(ar);
          showError(apiErrorMessage(ar.status, e, 'Não foi possível salvar o questionário.'), '/questionario/', 'Voltar ao questionário');
          return;
        }
        sessionStorage.removeItem('anamneseData');
        sessionStorage.removeItem('mynutri_quest_draft');
      } catch {
        showError(friendlyMessage('network'), '/questionario/', 'Voltar ao questionário');
        return;
      }
    }

    // 3. Inicia geração (a URL passa a ser /dieta/?job=<id>)
    await generateDiet();
    return;
  }

  await fetchExistingDiet(idParam && /^\d+$/.test(idParam) ? idParam : null);
}

/** Carrega a dieta indicada por ?id= ou, sem id, a mais recente. */
async function fetchExistingDiet(dietId) {
  const url = dietId ? `${API_BASE}/diet/${dietId}` : `${API_BASE}/diet`;
  try {
    // 401 sem refresh válido → apiFetch redireciona para /auth/ (auth guard)
    const res = await apiFetch(url);
    if (res.status === 401) return;
    if (res.status === 404) {
      if (dietId) showError('Não encontramos esta dieta. Ela pode ter sido removida.', '/historico/', 'Ver histórico');
      else        showError('Você ainda não possui um plano alimentar.', '/questionario/', 'Fazer questionário');
      return;
    }
    if (!res.ok) { showError(friendlyMessage(res.status, 'Não foi possível carregar sua dieta.')); return; }
    renderDiet(await res.json());
  } catch {
    showError(friendlyMessage('network'));
  }
}

// ════════════════════════════════
//  DOWNLOAD PDF
// ════════════════════════════════
document.getElementById('btn-download-pdf').addEventListener('click', async () => {
  const dietId = dietData?.id;
  if (!dietId) return;

  const btn   = document.getElementById('btn-download-pdf');
  const label = document.getElementById('btn-pdf-label');
  btn.disabled  = true;
  btn.setAttribute('aria-busy', 'true');
  label.textContent = 'Gerando PDF...';

  try {
    const res = await apiFetch(`${API_BASE}/diet/${dietId}/pdf`);

    if (!res.ok) {
      showToast(friendlyMessage(res.status, 'Não foi possível gerar o PDF. Tente novamente.'), 'error');
      return;
    }

    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = `mynutri-dieta-${isoDateStamp(dietData.created_at)}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    showToast('PDF baixado.', 'success');
  } catch {
    showToast(friendlyMessage('network'), 'error');
  } finally {
    btn.disabled      = false;
    btn.removeAttribute('aria-busy');
    label.textContent = 'Baixar PDF';
  }
});

// ════════════════════════════════
//  CHAT DOCK — toggle listener
// ════════════════════════════════
document.getElementById('chat-dock-toggle').addEventListener('click', () => {
  const panel = document.getElementById('chat-dock-panel');
  panel.classList.contains('open') ? closeChatDock() : openChatDock();
});

// ════════════════════════════════
//  BOTÕES DE LOADING / ERRO
// ════════════════════════════════
// "Sair e voltar depois": a geração continua no servidor; o job fica salvo na sessão.
document.getElementById('btn-cancel-generation').addEventListener('click', () => {
  stopPolling();
  window.location.href = '/';
});

document.getElementById('btn-retry-generation').addEventListener('click', () => {
  retryGeneration();
});

loadDiet();

})();
