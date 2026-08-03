document.addEventListener('DOMContentLoaded', function () {
  const btn = document.getElementById('sidebarToggle');
  const wrapper = document.getElementById('wrapper');
  const sidebar = document.getElementById('sidebar-wrapper');
  if (!btn || !wrapper || !sidebar) return;

  // Aplicar estado inicial: mantener COLAPSADA por defecto siempre (no abrir automáticamente)
  // La preferencia previa en localStorage se ignorará al cargar para evitar abrir la sidebar automáticamente.
  wrapper.classList.add('collapsed');

  // Crear overlay si no existe
  let overlay = document.getElementById('sidebarOverlay');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.id = 'sidebarOverlay';
    document.body.appendChild(overlay);
  }

  function setSidebar(open) {
    var isDesktop = window.innerWidth >= 769;
    if (isDesktop) {
      // On desktop, use 'collapsed' class to hide sidebar
      if (open) wrapper.classList.remove('collapsed'); else wrapper.classList.add('collapsed');
      // ensure overlay not visible on desktop
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

  // Click fuera (overlay) cierra
  overlay.addEventListener('click', function () {
    setSidebar(false);
  });

  // Al hacer clic en un enlace del sidebar en móvil, cerrar
  if (sidebar) {
    sidebar.addEventListener('click', function (e) {
    // solo cerrar automáticamente en dispositivos móviles para evitar
    // que el sidebar se oculte en pantallas de escritorio al interactuar
    const isMobile = window.innerWidth < 768;
    if (isMobile && e.target && e.target.tagName === 'A') setSidebar(false);
    });
  }

  // Bind custom collapse toggles (we removed the automatic data-bs-toggle
  // attribute from the template to avoid Bootstrap double-handling).
  try {
    document.querySelectorAll('.btn-collapse-toggle').forEach(btnToggle => {
      btnToggle.addEventListener('click', function (ev) {
        ev.stopPropagation();
        ev.preventDefault();
        const targetSel = btnToggle.getAttribute('data-collapse-target');
        if (!targetSel) return;
        const tgt = document.querySelector(targetSel);
        if (!tgt) return;
        const inst = bootstrap.Collapse.getOrCreateInstance(tgt, { toggle: false });
        if (tgt.classList.contains('show')) inst.hide(); else inst.show();
      });
    });
    const gestionar = document.getElementById('gestionarCollapse');
    if (gestionar) {
      gestionar.addEventListener('click', function (ev) {
        ev.stopPropagation();
      });
    }
  } catch (e) {
    // ignore
  }

  // Show a scrollbar on the sidebar when the "Inventario / Gestión" collapse is opened
  try {
    const gestionarEl = document.getElementById('gestionarCollapse');
    if (gestionarEl) {
      gestionarEl.addEventListener('shown.bs.collapse', function () {
        try {
          sidebar.classList.add('sidebar-scroll');
          // ensure we don't exceed viewport height
          sidebar.style.maxHeight = 'calc(100vh - 56px)';
        } catch (e) {}
      });
      gestionarEl.addEventListener('hidden.bs.collapse', function () {
        try {
          sidebar.classList.remove('sidebar-scroll');
          sidebar.style.maxHeight = '';
        } catch (e) {}
      });
    }
  } catch (e) {}

  // Cerrar sidebar al hacer clic en cualquier parte fuera de él (solo en móvil)
  document.addEventListener('click', function (e) {
    const isMobile = window.innerWidth < 768;
    if (!isMobile) return;
    if (!wrapper.classList.contains('show-sidebar')) return;
    // si el click es dentro del sidebar o en el botón toggle, no cerrar
    if (sidebar.contains(e.target) || btn.contains(e.target) || overlay.contains(e.target)) return;
    setSidebar(false);
  });

  // Floating FAB (contact) behavior
  const contactFab = document.getElementById('contactFab');
  const fabWrapper = document.querySelector('.contact-fab-wrapper');
  const fabMenu = document.getElementById('fabMenu');
  if (contactFab && fabWrapper && fabMenu) {
    // If the page contains a prominent invoice/actions area, nudge the FAB to the left
    function adjustFabForInvoice() {
      try {
        const hasInvoice = Boolean(document.querySelector('.invoice-card') || document.querySelector('.invoice-actions'));
        if (hasInvoice) fabWrapper.classList.add('invoice-left'); else fabWrapper.classList.remove('invoice-left');
      } catch (e) {}
    }
    // initial adjust and on resize (in case layout changes)
    adjustFabForInvoice();
    window.addEventListener('resize', function () { adjustFabForInvoice(); });

    contactFab.addEventListener('click', function (ev) {
      ev.stopPropagation();
      fabWrapper.classList.toggle('open');
      const isOpen = fabWrapper.classList.contains('open');
      fabMenu.setAttribute('aria-hidden', String(!isOpen));
    });

    // cerrar fab al hacer click fuera
    document.addEventListener('click', function (e) {
      if (!fabWrapper.classList.contains('open')) return;
      if (fabWrapper.contains(e.target)) return;
      fabWrapper.classList.remove('open');
      fabMenu.setAttribute('aria-hidden', 'true');
    });
  }

  // Highlight active menu item based on current path
  try {
    const links = Array.from(document.querySelectorAll('#sidebar-wrapper a'));
    const current = location.pathname.replace(/\/$/, '') || '/';
    links.forEach(link => {
      try {
        const href = new URL(link.href, location.origin).pathname.replace(/\/$/, '') || '/';
        if (href === current || (href !== '/' && current.startsWith(href))) {
          link.classList.add('active');
          link.setAttribute('aria-current', 'page');
          // if inside a collapsed group, expand its collapse parent
          const collapse = link.closest('.collapse');
          if (collapse && collapse.classList.contains('collapse')) {
            const bsCollapse = bootstrap.Collapse.getOrCreateInstance(collapse, { toggle: false });
            bsCollapse.show();
          }
        }
      } catch (e) {
        // ignore malformed URLs
      }
      // ensure a tooltip/title exists for accessibility
      if (!link.getAttribute('title')) link.setAttribute('title', link.textContent.trim());
    });
  } catch (e) {
    // silent
  }
});
