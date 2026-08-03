document.addEventListener('DOMContentLoaded', function () {
  const btn = document.getElementById('sidebarToggle');
  const wrapper = document.getElementById('wrapper');
  const sidebar = document.getElementById('sidebar-wrapper');
  if (!btn || !wrapper || !sidebar) return;

  let overlay = document.getElementById('sidebarOverlay');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.id = 'sidebarOverlay';
    document.body.appendChild(overlay);
  }

  function setSidebar(open) {
    var isDesktop = window.innerWidth >= 769;
    if (isDesktop) {
      if (open) wrapper.classList.remove('collapsed'); else wrapper.classList.add('collapsed');
      overlay.classList.remove('visible');
    } else {
      wrapper.classList.toggle('show-sidebar', open);
      overlay.classList.toggle('visible', open);
    }
  }

  btn.addEventListener('click', function () {
    var isDesktop = window.innerWidth >= 769;
    var isShown = isDesktop ? !wrapper.classList.contains('collapsed') : wrapper.classList.contains('show-sidebar');
    setSidebar(!isShown);
    try { localStorage.setItem('seoul_sidebar_open', (!isShown) ? '1' : '0'); } catch(e){}
  });

  overlay.addEventListener('click', function () {
    setSidebar(false);
  });

  sidebar.addEventListener('click', function (e) {
    const isMobile = window.innerWidth < 768;
    if (isMobile && e.target && e.target.tagName === 'A') setSidebar(false);
  });

  // Cerrar sidebar al hacer clic en cualquier parte fuera de él (solo en móvil)
  document.addEventListener('click', function (e) {
    const isMobile = window.innerWidth < 768;
    if (!isMobile) return;
    if (!wrapper.classList.contains('show-sidebar')) return;
    if (sidebar.contains(e.target) || btn.contains(e.target) || overlay.contains(e.target)) return;
    setSidebar(false);
  });

  // If the page contains invoice/actions area, nudge FAB to the left (if present)
  const fabWrapper = document.querySelector('.contact-fab-wrapper');
  if (fabWrapper) {
    function adjustFabForInvoice() {
      try {
        const hasInvoice = Boolean(document.querySelector('.invoice-card') || document.querySelector('.invoice-actions'));
        if (hasInvoice) fabWrapper.classList.add('invoice-left'); else fabWrapper.classList.remove('invoice-left');
      } catch (e) {}
    }
    adjustFabForInvoice();
    window.addEventListener('resize', adjustFabForInvoice);
  }
});
