(function () {
  const setLoading = setLoadingBtn;

  // --- Google OAuth error param ---
  const googleErrorParam = new URLSearchParams(window.location.search).get('google_error');
  if (googleErrorParam) {
    const googleErrorMessages = {
      csrf: 'Falha de segurança no login com Google. Tente novamente.',
      invalid_token: 'Não foi possível validar sua conta Google. Tente novamente.',
      no_email: 'Não foi possível obter o e-mail da conta Google.',
      service_unavailable: 'Login com Google indisponível no momento. Tente mais tarde.',
      no_credential: 'Não recebemos a confirmação do Google. Tente novamente.',
    };
    const msg = googleErrorMessages[googleErrorParam] || 'Não foi possível entrar com Google. Tente novamente.';
    requestAnimationFrame(function () { showError(msg); });
  }

  // --- Tabs acessíveis (role=tab, aria-selected, setas/Home/End) ---
  const tabs  = Array.prototype.slice.call(document.querySelectorAll('.auth-tab'));
  const forms = document.querySelectorAll('.auth-form');

  function activateTab(tab, moveFocus) {
    tabs.forEach(function (t) {
      const selected = t === tab;
      t.classList.toggle('active', selected);
      t.setAttribute('aria-selected', selected ? 'true' : 'false');
      t.tabIndex = selected ? 0 : -1;
    });
    forms.forEach(function (f) {
      const active = f.id === tab.getAttribute('data-target');
      f.classList.toggle('active', active);
      f.hidden = !active;
    });
    clearError();
    if (moveFocus) tab.focus();
  }

  tabs.forEach(function (tab, i) {
    tab.addEventListener('click', function () { activateTab(tab, false); });
    tab.addEventListener('keydown', function (e) {
      let next = null;
      if (e.key === 'ArrowRight') next = tabs[(i + 1) % tabs.length];
      else if (e.key === 'ArrowLeft') next = tabs[(i - 1 + tabs.length) % tabs.length];
      else if (e.key === 'Home') next = tabs[0];
      else if (e.key === 'End') next = tabs[tabs.length - 1];
      if (next) { e.preventDefault(); activateTab(next, true); }
    });
  });

  // --- Intent param ---
  const urlParams = new URLSearchParams(window.location.search);
  const intent = urlParams.get('intent');

  if (intent === 'save_diet') {
    document.getElementById('intent-message').classList.add('visible');
    activateTab(tabs[1], false);
    document.querySelector('.auth-title').textContent = 'Quase lá!';
    document.querySelector('.auth-subtitle').textContent = 'Crie sua conta para gerarmos sua dieta.';
  }

  // --- Helpers ---
  function showError(msg) {
    const el = document.getElementById('auth-error');
    if (el) el.textContent = msg;
  }

  function clearError() {
    const el = document.getElementById('auth-error');
    if (el) el.textContent = '';
    document.querySelectorAll('.auth-form [aria-invalid]').forEach(function (i) { i.removeAttribute('aria-invalid'); });
  }

  function markInvalid(input) {
    if (!input) return;
    input.setAttribute('aria-invalid', 'true');
    const described = (input.getAttribute('aria-describedby') || '').split(' ').filter(Boolean);
    if (!described.includes('auth-error')) described.push('auth-error');
    input.setAttribute('aria-describedby', described.join(' '));
    input.focus();
  }

  function saveSession(data) {
    // Tokens ficam apenas em cookies HttpOnly (o servidor não os devolve no JSON).
    // Só salvamos metadados do usuário no localStorage — não contém credenciais.
    if (data && data.user) localStorage.setItem('mynutri_user', JSON.stringify(data.user));
  }

  function afterAuth() {
    if (intent === 'save_diet' && sessionStorage.getItem('anamneseData')) {
      window.location.href = '/dieta/?generate=1';
      return;
    }
    const ref = document.referrer;
    let refUrl = null;
    try { refUrl = ref ? new URL(ref) : null; } catch { refUrl = null; }
    const skip = ['/', '/auth/'];
    if (refUrl && !skip.includes(refUrl.pathname) && refUrl.origin === window.location.origin) {
      window.location.href = refUrl.href;
    } else {
      window.location.href = '/dieta/';
    }
  }

  async function postAuth(path, payload) {
    return apiFetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      skipRefresh: true,
      redirectOn401: false,
    });
  }

  // --- Login ---
  document.getElementById('login-form').addEventListener('submit', async function (e) {
    e.preventDefault();
    clearError();
    const btn        = e.target.querySelector('button[type="submit"]');
    const emailInput = document.getElementById('login-email');
    const passInput  = document.getElementById('login-password');
    const email      = emailInput.value.trim();
    const senha      = passInput.value;

    if (!email || !emailInput.checkValidity()) { showError('Informe um e-mail válido.'); markInvalid(emailInput); return; }
    if (!senha) { showError('Informe sua senha.'); markInvalid(passInput); return; }

    setLoading(btn, true);
    btn.textContent = 'Entrando...';

    try {
      const res  = await postAuth('/auth/login', { email, password: senha });
      const data = await safeJson(res);

      if (!res.ok) {
        showError(res.status === 401 || res.status === 400
          ? 'E-mail ou senha inválidos.'
          : apiErrorMessage(res.status, data));
        setLoading(btn, false);
        return;
      }

      saveSession(data);
      afterAuth();
    } catch {
      showError(friendlyMessage('network'));
      setLoading(btn, false);
    }
  });

  // --- Cadastro ---
  document.getElementById('register-form').addEventListener('submit', async function (e) {
    e.preventDefault();
    clearError();
    const btn        = e.target.querySelector('button[type="submit"]');
    const nameInput  = document.getElementById('register-name');
    const emailInput = document.getElementById('register-email');
    const passInput  = document.getElementById('register-password');
    const termsInput = document.getElementById('register-terms');
    const nome   = nameInput.value.trim();
    const email  = emailInput.value.trim();
    const senha  = passInput.value;

    if (!nome) { showError('Informe seu nome.'); markInvalid(nameInput); return; }
    if (!email || !emailInput.checkValidity()) { showError('Informe um e-mail válido.'); markInvalid(emailInput); return; }
    if (senha.length < 8) { showError('A senha deve ter pelo menos 8 caracteres.'); markInvalid(passInput); return; }
    if (!termsInput.checked) {
      showError('Para criar a conta, aceite os Termos de Uso e a Política de Privacidade.');
      markInvalid(termsInput);
      return;
    }

    setLoading(btn, true);
    btn.textContent = 'Criando conta...';

    try {
      const res  = await postAuth('/auth/register', { nome, email, senha, accepted_terms: true });
      const data = await safeJson(res);

      if (!res.ok) {
        showError(apiErrorMessage(res.status, data, 'Não foi possível criar a conta.'));
        setLoading(btn, false);
        return;
      }

      saveSession(data);
      afterAuth();
    } catch {
      showError(friendlyMessage('network'));
      setLoading(btn, false);
    }
  });

  // --- Google Sign-In ---
  const GOOGLE_CLIENT_ID = '806980657199-js2h4t4o9cq8577c7geulvgosdt777t2.apps.googleusercontent.com';

  async function handleGoogleCredential(response) {
    clearError();
    if (!response || !response.credential) {
      showError('Não recebemos a confirmação do Google. Tente novamente.');
      return;
    }
    try {
      const res  = await postAuth('/auth/google', { id_token: response.credential });
      const data = await safeJson(res);

      if (!res.ok) {
        showError(apiErrorMessage(res.status, data, 'Não foi possível entrar com Google. Tente novamente.'));
        return;
      }

      saveSession(data);
      afterAuth();
    } catch {
      showError(friendlyMessage('network'));
    }
  }

  function initGoogleSignIn() {
    if (!window.google) return;
    const loginUri = `${window.location.origin}/api/v1/auth/google/callback`;
    google.accounts.id.initialize({
      client_id: GOOGLE_CLIENT_ID,
      auto_select: false,
      ux_mode: 'redirect',
      login_uri: loginUri,
    });
    const container = document.getElementById('google-btn-hidden');
    const width = Math.min(container.parentElement.offsetWidth || 400, 400);
    google.accounts.id.renderButton(container, { theme: 'outline', size: 'large', width, locale: 'pt-BR' });
  }

  // handleGoogleCredential precisa ser global para o callback da SDK do Google
  window.handleGoogleCredential = handleGoogleCredential;

  if (window.google) {
    initGoogleSignIn();
  } else {
    const gsiScript = document.querySelector('script[src*="accounts.google.com"]');
    if (gsiScript) gsiScript.addEventListener('load', initGoogleSignIn);
  }
})();
