(function () {
  // --- Mobile nav ---
  const mobileToggle = document.getElementById('mobile-toggle');
  const nav = document.getElementById('nav');
  function setNavOpen(open) {
    nav.classList.toggle('open', open);
    mobileToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    mobileToggle.setAttribute('aria-label', open ? 'Fechar menu' : 'Abrir menu');
    const spans = mobileToggle.querySelectorAll('span');
    spans[0].style.transform = open ? 'rotate(45deg) translate(5px, 5px)' : '';
    spans[1].style.opacity   = open ? '0' : '';
    spans[2].style.transform = open ? 'rotate(-45deg) translate(5px, -5px)' : '';
  }
  mobileToggle.addEventListener('click', function () {
    setNavOpen(!nav.classList.contains('open'));
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && nav.classList.contains('open')) {
      setNavOpen(false);
      mobileToggle.focus();
    }
  });

  // --- User menu ---
  initUserMenu({
    requireAuth: false,
    logoutRedirect: '/',
    onUserLoaded: function (user) {
      const nomeField  = document.getElementById('contact-nome');
      const emailField = document.getElementById('contact-email');
      if (nomeField  && !nomeField.value)  nomeField.value  = user.nome  || '';
      if (emailField && !emailField.value) emailField.value = user.email || '';
    },
  });

  // --- Contact form ---
  document.getElementById('contact-form').addEventListener('submit', async function (e) {
    e.preventDefault();

    const form     = e.target;
    const btn      = document.getElementById('btn-contact-submit');
    const nome     = document.getElementById('contact-nome').value.trim();
    const email    = document.getElementById('contact-email').value.trim();
    const assunto  = document.getElementById('contact-assunto').value;
    const mensagem = document.getElementById('contact-mensagem').value.trim();

    function showFormError(msg) {
      let el = document.getElementById('contact-form-error');
      if (!el) {
        el = document.createElement('p');
        el.id = 'contact-form-error';
        el.className = 'contact-form-error';
        el.setAttribute('role', 'alert');
        btn.parentElement.insertBefore(el, btn);
      }
      el.textContent = msg;
    }

    function clearFormError() {
      const el = document.getElementById('contact-form-error');
      if (el) el.textContent = '';
    }

    clearFormError();

    if (!nome || !email || !assunto || !mensagem) {
      showFormError('Por favor, preencha todos os campos obrigatórios.');
      return;
    }
    if (mensagem.length < 10) {
      showFormError('A mensagem deve ter pelo menos 10 caracteres.');
      return;
    }

    btn.disabled = true;
    const originalBtnHTML = btn.innerHTML;
    btn.innerHTML = 'Enviando…';

    try {
      const res = await apiFetch(`${API_BASE}/contact`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nome, email, assunto, mensagem }),
        redirectOn401: false,
        skipRefresh: true,
      });

      if (res.ok) {
        document.getElementById('contact-form-title').style.display = 'none';
        form.style.display = 'none';
        document.getElementById('contact-success').style.display = 'flex';
      } else {
        const data = await safeJson(res);
        showFormError(apiErrorMessage(res.status, data, 'Não foi possível enviar. Tente novamente.'));
      }
    } catch {
      showFormError(friendlyMessage('network'));
    } finally {
      btn.disabled = false;
      btn.innerHTML = originalBtnHTML;
    }
  });

  // --- "Enviar nova mensagem" (antes era onclick inline — proibido pela CSP) ---
  document.getElementById('btn-new-message').addEventListener('click', function () {
    document.getElementById('contact-success').style.display = 'none';
    const form = document.getElementById('contact-form');
    form.style.display = 'flex';
    document.getElementById('contact-form-title').style.display = 'block';
    form.reset();
    document.getElementById('contact-nome').focus();
  });

  // --- FAQ Accordion ---
  document.querySelectorAll('.faq-question').forEach(function (btn) {
    btn.addEventListener('click', function () {
      const item = btn.parentElement;
      const isOpen = item.classList.contains('open');
      document.querySelectorAll('.faq-item').forEach(function (i) {
        i.classList.remove('open');
        const q = i.querySelector('.faq-question');
        if (q) q.setAttribute('aria-expanded', 'false');
      });
      if (!isOpen) item.classList.add('open');
      btn.setAttribute('aria-expanded', !isOpen ? 'true' : 'false');
    });
  });
})();
