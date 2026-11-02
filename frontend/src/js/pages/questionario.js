(function () {
  let _user = null;
  try { _user = JSON.parse(localStorage.getItem('mynutri_user') || 'null'); } catch { _user = null; }

  initUserMenu({ requireAuth: false, logoutRedirect: '/' });

  const totalSteps = 6;
  let currentStep = 1;

  const form      = document.getElementById('questionnaire-form');
  const btnNext   = document.getElementById('btn-next');
  const btnBack   = document.getElementById('btn-back');
  const btnSubmit = document.getElementById('btn-submit');
  const stepInfo  = document.getElementById('step-info');

  // Rascunho salvo a cada alteração (sobrevive a refresh / ida ao login)
  const DRAFT_KEY = 'mynutri_quest_draft';

  // Condições que exigem acompanhamento profissional (contrato C5 com o backend)
  const HEALTH_NONE = 'nenhuma';

  // --- Validation per step ---
  function validateStep(step) {
    let valid = true;
    clearErrors(step);

    if (step === 1) {
      valid = validateNumber('idade', 18, 120) && valid;
      valid = validateRequired('sexo') && valid;
      valid = validateNumber('peso', 20, 400) && valid;
      valid = validateNumber('altura', 100, 250) && valid;
      if (valid) valid = validateBmi() && valid;
    }

    if (step === 2) {
      valid = validateHealth() && valid;
    }

    if (step === 3) {
      const selected = form.querySelector('input[name="objetivo"]:checked');
      if (!selected) {
        showError('objetivo');
        valid = false;
      } else if (selected.value === 'perda_peso') {
        const bmi = currentBmi();
        if (bmi !== null && bmi < 18.5) {
          showError('objetivo', 'Seu IMC já está abaixo de 18,5. Para sua segurança, não geramos planos de emagrecimento nesse caso — escolha outro objetivo ou procure um nutricionista.');
          valid = false;
        }
      }
    }

    if (step === 4) {
      const selected = form.querySelector('input[name="atividade"]:checked');
      if (!selected) { showError('atividade'); valid = false; }
    }

    if (step === 6) {
      valid = validateRequired('refeicoes') && valid;
    }

    if (!valid) focusFirstError(step);
    return valid;
  }

  function currentBmi() {
    const peso   = parseFloat(document.getElementById('peso').value);
    const altura = parseFloat(document.getElementById('altura').value);
    if (!peso || !altura) return null;
    return peso / Math.pow(altura / 100, 2);
  }

  // IMC muito baixo (< 16) indica risco: o backend também rejeita (C5)
  function validateBmi() {
    const bmi = currentBmi();
    if (bmi !== null && bmi < 16) {
      markInvalid('peso', 'Com esse peso e altura o IMC fica abaixo de 16, o que indica risco à saúde. Procure um nutricionista ou médico para um plano acompanhado.');
      return false;
    }
    return true;
  }

  function validateHealth() {
    const checked = Array.prototype.map.call(
      form.querySelectorAll('input[name="health_conditions"]:checked'), function (c) { return c.value; });
    const riskMsg = document.getElementById('health-risk-msg');
    riskMsg.hidden = true;
    if (!checked.length) {
      showError('health_conditions');
      return false;
    }
    if (checked.some(function (v) { return v !== HEALTH_NONE; })) {
      // Caso de risco: orienta a procurar profissional e NÃO permite enviar
      riskMsg.hidden = false;
      return false;
    }
    return true;
  }

  function validateRequired(id) {
    const el = document.getElementById(id);
    if (!el.value.trim()) {
      markInvalid(id);
      return false;
    }
    return true;
  }

  function validateNumber(id, min, max) {
    const el = document.getElementById(id);
    const val = parseFloat(el.value);
    if (!el.value.trim() || isNaN(val) || val < min || val > max) {
      markInvalid(id);
      return false;
    }
    return true;
  }

  function markInvalid(id, message) {
    const el = document.getElementById(id);
    if (el) {
      el.classList.add('error');
      el.setAttribute('aria-invalid', 'true');
    }
    showError(id, message);
  }

  // Mensagens padrão dos spans de erro (para restaurar após uma mensagem do backend)
  const _defaultErrorText = {};
  form.querySelectorAll('.form-error').forEach(function (el) { _defaultErrorText[el.id] = el.textContent; });

  function showError(id, message) {
    const err = document.getElementById(id + '-error');
    if (!err) return false;
    err.textContent = message || _defaultErrorText[err.id] || 'Verifique este campo.';
    err.classList.add('visible');
    // radios/checkboxes: marca o grupo como inválido
    form.querySelectorAll(`input[name="${id}"]`).forEach(function (i) { i.setAttribute('aria-invalid', 'true'); });
    return true;
  }

  function clearErrors(step) {
    const stepEl = form.querySelector(`.form-step[data-step="${step}"]`);
    if (!stepEl) return;
    stepEl.querySelectorAll('.form-input, .form-select, .form-textarea, input').forEach(function (el) {
      el.classList.remove('error');
      el.removeAttribute('aria-invalid');
    });
    stepEl.querySelectorAll('.form-error').forEach(function (el) {
      el.classList.remove('visible');
      el.textContent = _defaultErrorText[el.id] || '';
    });
  }

  function focusFirstError(step) {
    const stepEl = form.querySelector(`.form-step[data-step="${step}"]`);
    if (!stepEl) return;
    const target = stepEl.querySelector('[aria-invalid="true"]');
    if (target) target.focus();
  }

  form.querySelectorAll('.form-input, .form-select, .form-textarea').forEach(function (el) {
    const clear = function () {
      el.classList.remove('error');
      el.removeAttribute('aria-invalid');
      const err = document.getElementById(el.id + '-error');
      if (err) err.classList.remove('visible');
    };
    el.addEventListener('input', clear);
    el.addEventListener('change', clear);
  });

  form.querySelectorAll('input[type="radio"], input[type="checkbox"]').forEach(function (input) {
    input.addEventListener('change', function () {
      const err = document.getElementById(input.name + '-error');
      if (err) err.classList.remove('visible');
      form.querySelectorAll(`input[name="${input.name}"]`).forEach(function (i) { i.removeAttribute('aria-invalid'); });
    });
  });

  // "Nenhuma destas" é exclusiva: desmarca as demais (e vice-versa)
  form.querySelectorAll('input[name="health_conditions"]').forEach(function (cb) {
    cb.addEventListener('change', function () {
      if (!cb.checked) return;
      form.querySelectorAll('input[name="health_conditions"]').forEach(function (other) {
        if (other === cb) return;
        if (cb.value === HEALTH_NONE || other.value === HEALTH_NONE) other.checked = false;
      });
      const riskMsg = document.getElementById('health-risk-msg');
      riskMsg.hidden = cb.value === HEALTH_NONE;
    });
  });

  // --- Navigation ---
  function goToStep(step, moveFocus) {
    const currentEl = form.querySelector(`.form-step[data-step="${currentStep}"]`);
    if (currentEl) currentEl.classList.remove('active');

    currentStep = step;

    const nextEl = form.querySelector(`.form-step[data-step="${step}"]`);
    if (nextEl) nextEl.classList.add('active');

    updateProgress();

    btnBack.classList.toggle('hidden', currentStep === 1);

    if (currentStep === totalSteps) {
      btnNext.style.display = 'none';
      btnSubmit.style.display = 'inline-flex';
    } else {
      btnNext.style.display = 'inline-flex';
      btnSubmit.style.display = 'none';
    }

    // Região aria-live anuncia "Etapa X de N"
    stepInfo.innerHTML = `Etapa <strong>${currentStep}</strong> de <strong>${totalSteps}</strong>`;

    // Foco no título da etapa para leitores de tela e teclado
    if (moveFocus !== false && nextEl) {
      const title = nextEl.querySelector('.form-step-title');
      if (title) title.focus();
    }
  }

  function updateProgress() {
    for (let i = 1; i <= totalSteps; i++) {
      const stepEl = document.querySelector(`.progress-step[data-step="${i}"]`);
      if (!stepEl) continue;
      stepEl.classList.remove('active', 'completed');
      if (i < currentStep) stepEl.classList.add('completed');
      else if (i === currentStep) stepEl.classList.add('active');
    }

    for (let i = 1; i < totalSteps; i++) {
      const connector = document.querySelector(`.progress-connector[data-connector="${i}"]`);
      if (!connector) continue;
      if (i < currentStep) connector.classList.add('completed');
      else connector.classList.remove('completed');
    }
  }

  btnNext.addEventListener('click', function () {
    if (validateStep(currentStep)) goToStep(currentStep + 1);
  });

  btnBack.addEventListener('click', function () {
    if (currentStep > 1) goToStep(currentStep - 1);
  });

  // --- Form Submit ---
  function showSubmitError(msg) {
    const el = document.getElementById('submit-error');
    el.hidden = false;
    el.textContent = msg;
    el.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'center' });
  }

  function hideSubmitError() {
    document.getElementById('submit-error').hidden = true;
  }

  const SUBMIT_LABEL_HTML = btnSubmit.innerHTML;

  function setSubmitBusy(label) {
    btnSubmit.textContent = label;
    btnSubmit.disabled = true;
    btnSubmit.setAttribute('aria-busy', 'true');
  }

  function resetSubmitBtn() {
    btnSubmit.innerHTML = SUBMIT_LABEL_HTML;
    btnSubmit.disabled = false;
    btnSubmit.removeAttribute('aria-busy');
  }

  const SEXO_MAP      = { masculino: 'M', feminino: 'F', outro: 'O' };
  const OBJETIVO_MAP  = { perda_peso: 'lose', manutencao: 'maintain', ganho_massa: 'gain', saude: 'maintain' };
  const ATIVIDADE_MAP = { sedentario: 'sedentary', leve: 'light', moderado: 'moderate', intenso: 'intense', atleta: 'athlete' };

  function readRaw() {
    const formData = new FormData(form);
    const raw = {};
    for (const [key, value] of formData.entries()) {
      if (raw[key] !== undefined) {
        raw[key] = Array.isArray(raw[key]) ? [...raw[key], value] : [raw[key], value];
      } else {
        raw[key] = value;
      }
    }
    return raw;
  }

  function asList(v) {
    if (v === undefined || v === null || v === '') return [];
    return Array.isArray(v) ? v : [v];
  }

  function collectFormData() {
    const raw = readRaw();

    // Restrições: tipo de dieta + texto livre
    const restricoesList = [];
    if (raw.tipo_dieta && raw.tipo_dieta !== 'onivoro') restricoesList.push(raw.tipo_dieta);
    if (raw.outras_restricoes && raw.outras_restricoes.trim()) {
      restricoesList.push(raw.outras_restricoes.trim());
    }

    // Alergias: checkboxes do questionário + alimentos a evitar (texto separado por vírgula).
    // O backend reconhece os valores dos checkboxes (gluten, lactose, ovo, ...) — contrato C5.
    const allergiesList = asList(raw.alergias).slice();
    (raw.alimentos_evitar || '').split(',').map(function (s) { return s.trim(); })
      .filter(Boolean).forEach(function (s) { if (!allergiesList.includes(s)) allergiesList.push(s); });

    const favs = raw.alimentos_favoritos || '';
    const obs  = (raw.observacoes || '').trim();
    const food_preferences = obs
      ? (favs ? `${favs}\nObservações: ${obs}` : `Observações: ${obs}`)
      : favs;

    return {
      idade: parseInt(raw.idade, 10),
      sexo: SEXO_MAP[raw.sexo] || raw.sexo,
      peso: parseFloat(raw.peso),
      altura: parseFloat(raw.altura),
      objetivo: OBJETIVO_MAP[raw.objetivo] || raw.objetivo,
      nivel_atividade: ATIVIDADE_MAP[raw.atividade] || raw.atividade,
      meals_per_day: parseInt(raw.refeicoes, 10) || 3,
      restricoes: restricoesList.join(', '),
      food_preferences,
      allergies: allergiesList.join(', '),
      health_conditions: asList(raw.health_conditions),
    };
  }

  // Campo do backend → [etapa, id do campo/grupo no formulário]
  const BACKEND_FIELD_MAP = {
    idade:             [1, 'idade'],
    sexo:              [1, 'sexo'],
    peso:              [1, 'peso'],
    altura:            [1, 'altura'],
    health_conditions: [2, 'health_conditions'],
    objetivo:          [3, 'objetivo'],
    nivel_atividade:   [4, 'atividade'],
    restricoes:        [5, 'restricoes'],
    allergies:         [5, 'allergies'],
    meals_per_day:     [6, 'refeicoes'],
    food_preferences:  [6, 'food_preferences'],
  };

  /** Mostra os erros 400 do backend no campo correspondente e leva o usuário até ele. */
  function showBackendErrors(errors) {
    if (!errors || typeof errors !== 'object') return false;
    let firstStep = null;
    const generic = [];
    Object.keys(errors).forEach(function (field) {
      const raw = errors[field];
      const msg = Array.isArray(raw) ? raw.filter(function (m) { return typeof m === 'string'; }).join(' ') : (typeof raw === 'string' ? raw : '');
      if (!msg) return;
      const target = BACKEND_FIELD_MAP[field];
      if (target) {
        const [step, id] = target;
        const el = document.getElementById(id);
        if (el) { el.classList.add('error'); el.setAttribute('aria-invalid', 'true'); }
        if (!showError(id, msg)) generic.push(msg);
        if (firstStep === null || step < firstStep) firstStep = step;
      } else {
        generic.push(msg);
      }
    });
    if (generic.length) showSubmitError(generic.join('\n'));
    if (firstStep !== null) {
      goToStep(firstStep, false);
      if (firstStep === 2) document.getElementById('health-risk-msg').hidden = false;
      focusFirstError(firstStep);
      return true;
    }
    return generic.length > 0;
  }

  let _submitting = false;

  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    if (_submitting) return;

    // Revalida todas as etapas (o usuário pode ter voltado e alterado algo)
    for (let s = 1; s <= totalSteps; s++) {
      if (!validateStep(s)) { if (s !== currentStep) { goToStep(s, false); validateStep(s); } return; }
    }

    hideSubmitError();
    const payload = collectFormData();

    if (!_user) {
      sessionStorage.setItem('anamneseData', JSON.stringify(payload));
      setSubmitBusy('Redirecionando...');
      window.location.href = '/auth/?intent=save_diet';
      return;
    }

    _submitting = true;
    setSubmitBusy('Enviando questionário...');

    try {
      const anamneseRes = await apiFetch(`${API_BASE}/anamnese`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!anamneseRes.ok) {
        const err = await safeJson(anamneseRes);
        if (!(anamneseRes.status === 400 && showBackendErrors(err))) {
          showSubmitError(apiErrorMessage(anamneseRes.status, err, 'Não foi possível salvar o questionário. Tente novamente.'));
        }
        resetSubmitBtn();
        _submitting = false;
        return;
      }

      clearDraft();
      window.location.href = '/dieta/?generate=1';
    } catch {
      showSubmitError(friendlyMessage('network'));
      resetSubmitBtn();
      _submitting = false;
    }
  });

  // --- Tags & Autocomplete ---
  const ALIMENTOS_BRASIL = [
    "Frango", "Frango Grelhado", "Frango Assado", "Frango Empanado", "Frango Desfiado",
    "Carne Bovina", "Carne Moída", "Bife", "Alcatra", "Picanha", "Costela", "Churrasco",
    "Linguiça", "Calabresa", "Salsicha", "Presunto", "Peito de Peru",
    "Peixe", "Tilápia", "Salmão", "Atum", "Sardinha",
    "Ovo", "Ovo Frito", "Ovo Cozido", "Omelete",
    "Hambúrguer",
    "Leite", "Leite Integral", "Leite Desnatado", "Leite Condensado",
    "Iogurte", "Iogurte Natural", "Iogurte Grego",
    "Queijo Mussarela", "Queijo Prato", "Queijo Minas", "Queijo Coalho",
    "Requeijão", "Cream Cheese",
    "Arroz Branco", "Arroz Integral", "Macarrão", "Lasanha", "Nhoque",
    "Pão Francês", "Pão de Forma", "Pão Integral", "Pão de Queijo",
    "Batata", "Batata Frita", "Batata Doce", "Purê de Batata",
    "Mandioca", "Farofa", "Cuscuz", "Tapioca", "Milho", "Polenta",
    "Alface", "Tomate", "Cenoura", "Brócolis", "Couve", "Repolho",
    "Pepino", "Beterraba", "Abobrinha", "Berinjela",
    "Banana", "Maçã", "Laranja", "Uva", "Morango", "Manga",
    "Mamão", "Melancia", "Melão", "Abacaxi", "Maracujá",
    "Limão", "Pera", "Goiaba", "Açaí",
    "Chocolate", "Chocolate Amargo", "Brigadeiro", "Beijinho",
    "Bolo de Chocolate", "Bolo de Cenoura", "Bolo de Fubá",
    "Sorvete", "Doce de Leite", "Pudim", "Gelatina",
    "Açaí com Granola",
    "Café", "Café com Leite", "Chá",
    "Suco Natural", "Suco de Laranja", "Suco de Uva",
    "Refrigerante", "Refrigerante Zero",
    "Água de Coco", "Leite com Chocolate",
    "Pizza", "Hambúrguer Artesanal", "X-Burguer", "X-Salada",
    "Batata Frita com Cheddar", "Hot Dog",
    "Coxinha", "Pastel", "Esfiha", "Kibe", "Empada",
    "Feijão", "Feijão Preto", "Feijoada",
    "Arroz com Feijão", "Arroz Carreteiro",
    "Estrogonofe de Frango", "Estrogonofe de Carne",
    "Risoto", "Panqueca", "Macarronada",
    "Frango com Batata", "Carne com Batata",
    "Sanduíche Natural", "Misto Quente", "Torrada",
    "Pão com Ovo", "Pão com Manteiga",
    "Pão com Presunto e Queijo",
    "Wrap", "Crepioca",
    "Amendoim", "Castanha de Caju", "Castanha do Pará",
    "Pasta de Amendoim", "Granola", "Mel",
    "Azeite", "Manteiga", "Maionese", "Ketchup", "Mostarda",
  ];

  function setupTagsInput(wrapperId, dropdownId, hiddenId, isAvoid) {
    isAvoid = isAvoid || false;
    const wrapper     = document.getElementById(wrapperId);
    const input       = wrapper.querySelector('.tags-input-inner');
    const dropdown    = document.getElementById(dropdownId);
    const hiddenField = document.getElementById(hiddenId);
    const tags        = [];
    let highlightedIndex = -1;

    function updateHiddenValue() {
      hiddenField.value = tags.join(', ');
      saveDraft();
    }

    // Texto do usuário vai sempre por textContent (nunca innerHTML) → sem XSS
    function renderTags() {
      wrapper.querySelectorAll('.tag-badge').forEach(function (el) { el.remove(); });
      tags.forEach(function (tagText, index) {
        const badge = document.createElement('div');
        badge.className = `tag-badge ${isAvoid ? 'badge-avoid' : ''}`;
        badge.appendChild(document.createTextNode(tagText + ' '));

        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'tag-badge-remove';
        removeBtn.dataset.index = String(index);
        removeBtn.setAttribute('aria-label', `Remover ${tagText}`);
        removeBtn.innerHTML = '<svg aria-hidden="true" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>';
        badge.appendChild(removeBtn);

        wrapper.insertBefore(badge, input);
      });
      updateHiddenValue();
    }

    function addTag(text) {
      const formatted = text.trim().slice(0, 60);
      if (formatted && !tags.includes(formatted) && tags.length < 30) {
        tags.push(formatted);
        renderTags();
      }
      input.value = '';
      closeDropdown();
    }

    function setTags(list) {
      tags.length = 0;
      (list || []).forEach(function (t) {
        const v = String(t).trim();
        if (v && !tags.includes(v)) tags.push(v);
      });
      renderTags();
    }

    function removeTag(index) { tags.splice(index, 1); renderTags(); input.focus(); }

    function closeDropdown() {
      dropdown.classList.remove('active');
      dropdown.innerHTML = '';
      highlightedIndex = -1;
      input.removeAttribute('aria-activedescendant');
    }

    function showDropdown(matches) {
      dropdown.innerHTML = '';
      if (matches.length === 0) { closeDropdown(); return; }
      matches.forEach(function (match, index) {
        const item = document.createElement('div');
        item.className = 'autocomplete-item';
        item.id = `${dropdownId}-opt-${index}`;
        item.setAttribute('role', 'option');
        item.textContent = match;
        item.addEventListener('mousedown', function (e) { e.preventDefault(); addTag(match); });
        dropdown.appendChild(item);
      });
      dropdown.classList.add('active');
    }

    function highlight(items) {
      items.forEach(function (item, idx) {
        const on = idx === highlightedIndex;
        item.classList.toggle('selected', on);
        item.setAttribute('aria-selected', on ? 'true' : 'false');
      });
      if (highlightedIndex >= 0 && items[highlightedIndex]) {
        input.setAttribute('aria-activedescendant', items[highlightedIndex].id);
      }
    }

    wrapper.addEventListener('click', function (e) {
      if (e.target.closest('.tag-badge-remove')) {
        const idx = parseInt(e.target.closest('.tag-badge-remove').getAttribute('data-index'), 10);
        removeTag(idx);
        return;
      }
      input.focus();
    });

    input.addEventListener('focus', function () { wrapper.classList.add('focused'); });

    input.addEventListener('blur', function () {
      wrapper.classList.remove('focused');
      setTimeout(function () {
        if (input.value.trim().length > 0) addTag(input.value);
        closeDropdown();
      }, 150);
    });

    input.addEventListener('input', function () {
      const val = input.value.trim().toLowerCase();
      if (!val) { closeDropdown(); return; }
      // Vírgula também adiciona a tag
      if (input.value.includes(',')) {
        input.value.split(',').forEach(function (part) { if (part.trim()) addTag(part); });
        return;
      }
      const normalize = function (str) { return str.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase(); };
      const normalVal = normalize(val);
      const matches = ALIMENTOS_BRASIL.filter(function (item) {
        return normalize(item).includes(normalVal) && !tags.includes(item);
      }).slice(0, 8);
      showDropdown(matches);
    });

    input.addEventListener('keydown', function (e) {
      const items = dropdown.querySelectorAll('.autocomplete-item');
      if (e.key === 'Backspace' && input.value === '' && tags.length > 0) {
        removeTag(tags.length - 1);
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (highlightedIndex >= 0 && items.length > 0) {
          addTag(items[highlightedIndex].textContent);
        } else if (input.value.trim().length > 0) {
          addTag(input.value);
        }
      } else if (e.key === 'Escape') {
        closeDropdown();
      } else if (e.key === 'ArrowDown' && items.length > 0) {
        e.preventDefault();
        highlightedIndex = Math.min(highlightedIndex + 1, items.length - 1);
        highlight(items);
      } else if (e.key === 'ArrowUp' && items.length > 0) {
        e.preventDefault();
        highlightedIndex = Math.max(highlightedIndex - 1, 0);
        highlight(items);
      }
    });

    return { addTag: addTag, setTags: setTags };
  }

  const favTags   = setupTagsInput('wrapper-favoritos', 'dropdown-favoritos', 'alimentos-favoritos', false);
  const avoidTags = setupTagsInput('wrapper-evitar', 'dropdown-evitar', 'alimentos-evitar', true);

  // --- Rascunho (sessionStorage) ---
  let _restoring = false;

  function saveDraft() {
    if (_restoring) return;
    try {
      const raw = readRaw();
      raw.__step = currentStep;
      sessionStorage.setItem(DRAFT_KEY, JSON.stringify(raw));
    } catch { /* storage indisponível */ }
  }

  function clearDraft() {
    try { sessionStorage.removeItem(DRAFT_KEY); } catch { /* ignore */ }
  }

  function setValue(id, value) {
    const el = document.getElementById(id);
    if (el && value != null && String(value) !== '') el.value = value;
  }

  function setChecked(name, values) {
    const list = asList(values).map(String);
    form.querySelectorAll(`input[name="${name}"]`).forEach(function (i) {
      i.checked = list.includes(i.value);
    });
  }

  function splitList(str) {
    return String(str || '').split(',').map(function (s) { return s.trim(); }).filter(Boolean);
  }

  function restoreDraft() {
    let raw = null;
    try { raw = JSON.parse(sessionStorage.getItem(DRAFT_KEY) || 'null'); } catch { raw = null; }
    if (!raw || typeof raw !== 'object') return false;
    _restoring = true;
    setValue('idade', raw.idade);
    setValue('sexo', raw.sexo);
    setValue('peso', raw.peso);
    setValue('altura', raw.altura);
    setChecked('health_conditions', raw.health_conditions);
    if (raw.objetivo)   setChecked('objetivo', raw.objetivo);
    if (raw.atividade)  setChecked('atividade', raw.atividade);
    if (raw.tipo_dieta) setChecked('tipo_dieta', raw.tipo_dieta);
    setChecked('alergias', raw.alergias);
    setValue('outras-restricoes', raw.outras_restricoes);
    setValue('refeicoes', raw.refeicoes);
    setValue('observacoes', raw.observacoes);
    favTags.setTags(splitList(raw.alimentos_favoritos));
    avoidTags.setTags(splitList(raw.alimentos_evitar));
    _restoring = false;
    return true;
  }

  form.addEventListener('input', saveDraft);
  form.addEventListener('change', saveDraft);

  // --- Pré-preenchimento a partir da última anamnese ---
  const SEXO_REVERSE      = { M: 'masculino', F: 'feminino' };
  const OBJETIVO_REVERSE  = { lose: 'perda_peso', gain: 'ganho_massa', maintain: 'manutencao' };
  const ATIVIDADE_REVERSE = { sedentary: 'sedentario', light: 'leve', moderate: 'moderado', intense: 'intenso', athlete: 'intenso' };
  const ALLERGY_VALUES    = Array.prototype.map.call(
    form.querySelectorAll('input[name="alergias"]'), function (i) { return i.value; });

  function _applyPrefill(data) {
    _restoring = true;
    if (data.idade)  setValue('idade', data.idade);
    if (data.sexo && SEXO_REVERSE[data.sexo]) setValue('sexo', SEXO_REVERSE[data.sexo]);
    if (data.peso)   setValue('peso', data.peso);
    if (data.altura) setValue('altura', data.altura);
    if (data.objetivo && OBJETIVO_REVERSE[data.objetivo]) setChecked('objetivo', OBJETIVO_REVERSE[data.objetivo]);
    if (data.nivel_atividade && ATIVIDADE_REVERSE[data.nivel_atividade]) setChecked('atividade', ATIVIDADE_REVERSE[data.nivel_atividade]);
    if (data.meals_per_day) setValue('refeicoes', String(data.meals_per_day));

    // Restrições: tipo de dieta + resto como texto livre
    const restr = splitList(data.restricoes);
    const tipo  = restr.find(function (r) { return r === 'vegetariano' || r === 'vegano'; });
    setChecked('tipo_dieta', tipo || 'onivoro');
    const outras = restr.filter(function (r) { return r !== tipo && !ALLERGY_VALUES.includes(r); });
    if (outras.length) setValue('outras-restricoes', outras.join(', '));

    // Alergias: valores conhecidos → checkboxes; o restante → "evitar"
    const allergies = splitList(data.allergies).concat(restr.filter(function (r) { return ALLERGY_VALUES.includes(r); }));
    setChecked('alergias', allergies.filter(function (a) { return ALLERGY_VALUES.includes(a); }));
    avoidTags.setTags(allergies.filter(function (a) { return !ALLERGY_VALUES.includes(a); }));

    // Preferências: "favoritos\nObservações: ..."
    const prefs = String(data.food_preferences || '');
    const obsIdx = prefs.indexOf('Observações:');
    const favPart = obsIdx >= 0 ? prefs.slice(0, obsIdx) : prefs;
    const obsPart = obsIdx >= 0 ? prefs.slice(obsIdx + 'Observações:'.length).trim() : '';
    favTags.setTags(splitList(favPart.replace(/\n/g, ',')));
    if (obsPart) setValue('observacoes', obsPart);
    _restoring = false;
    saveDraft();
  }

  async function _prefillFromAnamnese() {
    if (!_user) return;
    try {
      const res = await apiFetch(`${API_BASE}/anamnese/last`, { redirectOn401: false });
      if (!res.ok) return;
      const data = await res.json();
      _applyPrefill(data);
      const notice = document.getElementById('prefill-notice');
      if (notice) notice.hidden = false;
    } catch { /* falha silenciosa */ }
  }

  // O rascunho (mais recente) tem prioridade sobre a última anamnese salva
  if (restoreDraft()) {
    const notice = document.getElementById('prefill-notice');
    const text   = document.getElementById('prefill-notice-text');
    if (notice && text) {
      text.textContent = 'Recuperamos as respostas que você estava preenchendo.';
      notice.hidden = false;
    }
  } else {
    _prefillFromAnamnese();
  }

  // --- Keyboard navigation ---
  // Enter avança de etapa só em campos de texto/número; nunca envia na última etapa
  // (o envio exige clicar em "Gerar minha dieta").
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter' || e.shiftKey || e.isComposing) return;
    const t = e.target;
    if (!form.contains(t) || t.tagName !== 'INPUT') return;
    if (!['text', 'number', 'email', 'tel'].includes(t.type)) return;
    if (t.classList.contains('tags-input-inner')) return;   // Enter adiciona a tag
    e.preventDefault();
    if (currentStep < totalSteps) btnNext.click();
  });
})();
