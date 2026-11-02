(function () {
  // --- User menu ---
  initUserMenu({ requireAuth: false, logoutRedirect: '/' });

  // --- Header scroll effect ---
  const header = document.getElementById('header');
  window.addEventListener('scroll', function () {
    header.classList.toggle('scrolled', window.scrollY > 40);
  });

  // --- Mobile nav toggle (aria-expanded + ESC fecha) ---
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

  nav.querySelectorAll('.nav-link').forEach(function (link) {
    link.addEventListener('click', function () { setNavOpen(false); });
  });

  // --- Smooth scroll for anchor links ---
  document.querySelectorAll('a[href^="#"]').forEach(function (anchor) {
    anchor.addEventListener('click', function (e) {
      const target = document.querySelector(this.getAttribute('href'));
      if (target) {
        e.preventDefault();
        const y = target.getBoundingClientRect().top + window.pageYOffset - 80;
        window.scrollTo({ top: y, behavior: prefersReducedMotion() ? 'auto' : 'smooth' });
      }
    });
  });

  // --- Testimonials carousel ---
  const grid       = document.getElementById('testimonials-grid');
  const prevBtn    = document.getElementById('carousel-prev');
  const nextBtn    = document.getElementById('carousel-next');
  const dotsEl     = document.getElementById('carousel-dots');
  const formBox    = document.getElementById('testimonial-form-box');
  const section    = document.getElementById('depoimentos');
  let isLoggedIn = false;
  try { isLoggedIn = !!localStorage.getItem('mynutri_user'); } catch { isLoggedIn = false; }

  const PER_PAGE = 3;
  let currentPage = 0;
  let allTestimonials = [];

  // Só exibimos depoimentos reais vindos da API; sem dados, a seção fica escondida.
  function setSectionVisible(visible) {
    section.hidden = !visible;
    ['nav-depoimentos', 'footer-depoimentos'].forEach(function (id) {
      const el = document.getElementById(id);
      if (el) el.hidden = !visible;
    });
    const carousel = document.getElementById('testimonials-carousel');
    if (carousel) carousel.hidden = allTestimonials.length === 0;
    dotsEl.hidden = allTestimonials.length === 0;
    // Seção revelada depois do scroll-reveal ter rodado: mostra sem animação
    section.querySelectorAll('.reveal').forEach(function (el) { el.classList.add('visible'); });
  }

  function numPages() { return Math.max(1, Math.ceil(allTestimonials.length / PER_PAGE)); }

  function starsText(rating) {
    const r = Math.max(0, Math.min(5, Math.round(Number(rating) || 0)));
    return '★'.repeat(r) + '☆'.repeat(5 - r);
  }

  function buildCard(t) {
    const card = document.createElement('div');
    card.className = 'testimonial-card';

    const starsEl = document.createElement('div');
    starsEl.className = 'testimonial-stars';
    starsEl.textContent = starsText(t.rating);
    starsEl.setAttribute('role', 'img');
    starsEl.setAttribute('aria-label', `Nota ${Math.round(Number(t.rating) || 0)} de 5`);

    const textEl = document.createElement('p');
    textEl.className = 'testimonial-text';
    textEl.textContent = '"' + t.text + '"';

    const avatarEl = document.createElement('div');
    avatarEl.className = 'testimonial-avatar';
    avatarEl.textContent = t.avatar || initials(t.nome);
    avatarEl.setAttribute('aria-hidden', 'true');

    const nameEl = document.createElement('strong');
    nameEl.textContent = t.nome || 'Usuário';

    const authorInfo = document.createElement('div');
    authorInfo.className = 'testimonial-author-info';
    authorInfo.appendChild(nameEl);

    const author = document.createElement('div');
    author.className = 'testimonial-author';
    author.appendChild(avatarEl);
    author.appendChild(authorInfo);

    card.appendChild(starsEl);
    card.appendChild(textEl);
    card.appendChild(author);
    return card;
  }

  function renderPage(page, direction) {
    const slice = allTestimonials.slice(page * PER_PAGE, (page + 1) * PER_PAGE);

    function swap() {
      grid.innerHTML = '';
      slice.forEach(function (t) { grid.appendChild(buildCard(t)); });
    }

    if (prefersReducedMotion()) {
      swap();
    } else if (direction === 0) {
      grid.style.transition = 'opacity 0.3s ease';
      grid.style.opacity = '0';
      setTimeout(function () { swap(); grid.style.opacity = '1'; }, 250);
    } else {
      grid.style.transition = 'opacity 0.25s ease, transform 0.25s ease';
      grid.style.opacity = '0';
      grid.style.transform = `translateX(${direction > 0 ? '-40px' : '40px'})`;

      setTimeout(function () {
        swap();
        grid.style.transition = 'none';
        grid.style.transform = `translateX(${direction > 0 ? '40px' : '-40px'})`;
        requestAnimationFrame(function () {
          requestAnimationFrame(function () {
            grid.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
            grid.style.opacity = '1';
            grid.style.transform = 'translateX(0)';
          });
        });
      }, 240);
    }

    currentPage = page;
    updateControls();
  }

  function updateControls() {
    const pages = numPages();
    prevBtn.disabled = currentPage === 0;
    nextBtn.disabled = currentPage >= pages - 1;

    dotsEl.innerHTML = '';
    if (pages > 1) {
      for (let i = 0; i < pages; i++) {
        const dot = document.createElement('button');
        dot.className = 'carousel-dot' + (i === currentPage ? ' active' : '');
        dot.setAttribute('aria-label', `Página ${i + 1} de depoimentos`);
        dot.addEventListener('click', function () {
          if (i !== currentPage) renderPage(i, i > currentPage ? 1 : -1);
        });
        dotsEl.appendChild(dot);
      }
    }
  }

  prevBtn.addEventListener('click', function () {
    if (currentPage > 0) renderPage(currentPage - 1, -1);
  });

  nextBtn.addEventListener('click', function () {
    if (currentPage < numPages() - 1) renderPage(currentPage + 1, 1);
  });

  // ←/→ navegam no carrossel só quando o foco NÃO está num campo editável
  document.addEventListener('keydown', function (e) {
    if (section.hidden || allTestimonials.length === 0) return;
    const t = e.target;
    if (t && (t.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName))) return;
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    const rect = section.getBoundingClientRect();
    const inView = rect.top < window.innerHeight && rect.bottom > 0;
    if (!inView) return;
    if (e.key === 'ArrowLeft' && currentPage > 0)                renderPage(currentPage - 1, -1);
    if (e.key === 'ArrowRight' && currentPage < numPages() - 1) renderPage(currentPage + 1, 1);
  });

  async function loadTestimonials() {
    try {
      const res = await apiFetch(`${API_BASE}/testimonials`, { redirectOn401: false, skipRefresh: true });
      if (!res.ok) { setSectionVisible(isLoggedIn); return; }
      const data = await res.json();
      const list = Array.isArray(data) ? data : (data.results || []);
      allTestimonials = list;
      if (list.length) renderPage(0, 0);
      updateControls();
      setSectionVisible(list.length > 0 || isLoggedIn);
    } catch {
      // Servidor offline — sem depoimentos para mostrar
      setSectionVisible(isLoggedIn);
    }
  }

  function buildForm() {
    formBox.innerHTML = '';

    const title = document.createElement('h3');
    title.id = 'testimonial-form-title';
    title.textContent = 'Deixe seu depoimento';

    const subtitle = document.createElement('p');
    subtitle.textContent = 'Compartilhe sua experiência com o MyNutri AI.';

    const ratingLabel = document.createElement('p');
    ratingLabel.style.cssText = 'display:block;font-size:.875rem;font-weight:600;color:var(--text-primary);margin-bottom:8px;';
    ratingLabel.textContent = 'Sua nota';

    const starRating = document.createElement('fieldset');
    starRating.className = 'star-rating';
    const legend = document.createElement('legend');
    legend.className = 'sr-only';
    legend.textContent = 'Nota de 1 a 5 estrelas';
    starRating.appendChild(legend);
    for (let i = 5; i >= 1; i--) {
      const input = document.createElement('input');
      input.type = 'radio'; input.name = 'rating';
      input.id = `star${i}`; input.value = i;
      if (i === 5) input.checked = true;
      const label = document.createElement('label');
      label.htmlFor = `star${i}`;
      label.textContent = '★';
      label.setAttribute('aria-label', `${i} estrela${i > 1 ? 's' : ''}`);
      starRating.appendChild(input);
      starRating.appendChild(label);
    }

    const textLabel = document.createElement('label');
    textLabel.htmlFor = 'testimonial-text';
    textLabel.style.cssText = 'display:block;font-size:.875rem;font-weight:600;color:var(--text-primary);margin-bottom:8px;';
    textLabel.textContent = 'Seu depoimento';

    const textarea = document.createElement('textarea');
    textarea.id = 'testimonial-text';
    textarea.className = 'testimonial-textarea';
    textarea.placeholder = 'Conte como o MyNutri AI ajudou você…';
    textarea.maxLength = 500;

    const charCount = document.createElement('div');
    charCount.className = 'testimonial-char-count';
    charCount.textContent = '0 / 500';
    textarea.addEventListener('input', function () {
      const len = textarea.value.length;
      charCount.textContent = `${len} / 500`;
      charCount.classList.toggle('over', len > 500);
    });

    const submitRow = document.createElement('div');
    submitRow.className = 'testimonial-submit-row';
    const feedback = document.createElement('span');
    feedback.className = 'testimonial-feedback';
    feedback.setAttribute('role', 'status');
    const btn = document.createElement('button');
    btn.type = 'submit';
    btn.className = 'btn btn-primary';
    btn.textContent = 'Enviar depoimento';
    submitRow.appendChild(feedback);
    submitRow.appendChild(btn);

    const form = document.createElement('form');
    form.noValidate = true;
    form.appendChild(ratingLabel);
    form.appendChild(starRating);
    form.appendChild(textLabel);
    form.appendChild(textarea);
    form.appendChild(charCount);
    form.appendChild(submitRow);

    formBox.appendChild(title);
    formBox.appendChild(subtitle);
    formBox.appendChild(form);

    form.addEventListener('submit', async function (e) {
      e.preventDefault();
      feedback.textContent = '';
      feedback.className = 'testimonial-feedback';

      const text = textarea.value.trim();
      const ratingInput = form.querySelector('input[name="rating"]:checked');
      const rating = ratingInput ? parseInt(ratingInput.value, 10) : 5;

      if (!text || text.length < 10) {
        feedback.textContent = 'O depoimento deve ter pelo menos 10 caracteres.';
        feedback.classList.add('error');
        textarea.focus();
        return;
      }

      btn.disabled = true;
      btn.textContent = 'Enviando…';

      try {
        const res = await apiFetch(`${API_BASE}/testimonials`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text, rating }),
          redirectOn401: false,
        });
        const payload = await safeJson(res);

        if (res.status === 401) {
          feedback.textContent = friendlyMessage(401);
          feedback.classList.add('error');
          return;
        }
        if (!res.ok || !payload) {
          feedback.textContent = apiErrorMessage(res.status, payload, 'Não foi possível enviar. Tente novamente.');
          feedback.classList.add('error');
          return;
        }

        // Depoimentos podem depender de aprovação: só entram no carrossel se vierem aprovados
        if (payload.approved !== false) {
          allTestimonials.unshift(payload);
          renderPage(0, 0);
          setSectionVisible(true);
        }

        textarea.value = '';
        charCount.textContent = '0 / 500';
        feedback.textContent = 'Depoimento enviado! Obrigado pela sua avaliação.';
        feedback.classList.add('success');
      } catch {
        feedback.textContent = friendlyMessage('network');
        feedback.classList.add('error');
      } finally {
        btn.disabled = false;
        btn.textContent = 'Enviar depoimento';
      }
    });
  }

  // Carrega depoimentos reais (a seção começa escondida no HTML)
  updateControls();
  loadTestimonials();

  if (isLoggedIn) buildForm();
})();
