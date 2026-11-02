/**
 * Page Transitions — MyNutri AI
 *
 * Adiciona uma classe `page-leaving` no <body> antes de navegar para outra
 * página, permitindo animação de saída via CSS (fade-out, etc.).
 * Ignora links externos, âncoras (#), mailto e links sem href.
 */
(function () {
  function navigateTo(url) {
    const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduce) { window.location.href = url; return; }
    document.body.classList.add('page-leaving');
    setTimeout(() => { window.location.href = url; }, 260);
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('a[href]').forEach(function (link) {
      const href = link.getAttribute('href');
      if (!href || href.startsWith('#') || href.startsWith('http') || href.startsWith('mailto')) return;
      if (link.target === '_blank' || link.hasAttribute('download')) return;
      link.addEventListener('click', function (e) {
        // Respeita ctrl/cmd/shift+clique (abrir em nova aba) e botão do meio
        if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        e.preventDefault();
        navigateTo(href);
      });
    });
  });

  window.navigateTo = navigateTo;
})();
