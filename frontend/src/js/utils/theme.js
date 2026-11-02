/**
 * Dark Mode System — MyNutri AI
 *
 * Auto-executa ao carregar:
 *   1. Aplica tema salvo em localStorage, ou preferência do sistema, ou claro.
 *   2. Liga o toggle (#theme-toggle) se existir na página.
 *   3. Sincroniza com mudanças na preferência do sistema (se usuário não escolheu).
 *
 * Deve ser incluído no <head> SEM defer/async (arquivo externo bloqueante) para
 * aplicar a classe `dark` antes da primeira pintura e evitar FOUC.
 */
(function () {
  const THEME_KEY = 'mynutri_theme';
  const html = document.documentElement;

  function readSaved() {
    try { return localStorage.getItem(THEME_KEY); } catch { return null; }
  }

  function applyTheme(theme) {
    html.classList.toggle('dark', theme === 'dark');
    const toggle = document.getElementById('theme-toggle');
    if (toggle) toggle.setAttribute('aria-pressed', theme === 'dark' ? 'true' : 'false');
  }

  // Só persiste quando o usuário escolhe explicitamente (toggle).
  function setTheme(theme) {
    applyTheme(theme);
    try { localStorage.setItem(THEME_KEY, theme === 'dark' ? 'dark' : 'light'); } catch { /* ignore */ }
  }

  function systemPrefersDark() {
    return !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
  }

  function initializeTheme() {
    const saved = readSaved();
    applyTheme(saved || (systemPrefersDark() ? 'dark' : 'light'));
  }

  function toggleTheme() {
    setTheme(html.classList.contains('dark') ? 'light' : 'dark');
  }

  initializeTheme();

  document.addEventListener('DOMContentLoaded', function () {
    const themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) {
      themeToggle.setAttribute('aria-pressed', html.classList.contains('dark') ? 'true' : 'false');
      themeToggle.addEventListener('click', toggleTheme);
    }
  });

  if (window.matchMedia) {
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function (e) {
      if (!readSaved()) applyTheme(e.matches ? 'dark' : 'light');
    });
  }

  window.MyNutriTheme = { setTheme: setTheme, toggleTheme: toggleTheme };
})();
