(function () {
  // Desktop services dropdown
  const navItem = document.getElementById('servicesNavItem');
  const trigger = document.getElementById('servicesTrigger');

  if (navItem && trigger) {
    trigger.addEventListener('click', (e) => {
      e.stopPropagation();
      const isOpen = navItem.classList.toggle('open');
      trigger.setAttribute('aria-expanded', isOpen);
    });

    document.addEventListener('click', (e) => {
      if (!navItem.contains(e.target)) {
        navItem.classList.remove('open');
        trigger.setAttribute('aria-expanded', 'false');
      }
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        navItem.classList.remove('open');
        trigger.setAttribute('aria-expanded', 'false');
      }
    });
  }

  // Mobile menu toggle
  const menuToggle = document.getElementById('menuToggle');
  const mobileNav = document.getElementById('mobileNav');

  if (menuToggle && mobileNav) {
    menuToggle.addEventListener('click', () => {
      const isOpen = mobileNav.classList.toggle('open');
      menuToggle.setAttribute('aria-expanded', isOpen);
    });
  }

  const mobileServicesTrigger = document.getElementById('mobileServicesTrigger');
  const mobileServicesSubmenu = document.getElementById('mobileServicesSubmenu');
  if (mobileServicesTrigger && mobileServicesSubmenu) {
    mobileServicesTrigger.addEventListener('click', () => {
      mobileServicesSubmenu.classList.toggle('open');
      mobileServicesTrigger.parentElement.classList.toggle('open');
    });
  }
})();
