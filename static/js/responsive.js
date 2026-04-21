(function () {
  function closeNav(nav) {
    if (!nav) {
      return;
    }
    nav.classList.remove("nav-open");
    var toggle = nav.querySelector("[data-menu-toggle]");
    if (toggle) {
      toggle.setAttribute("aria-expanded", "false");
    }
    document.body.classList.remove("mobile-menu-open");
  }

  function closeAllNavs() {
    document.querySelectorAll("nav[data-mobile-nav]").forEach(closeNav);
  }

  function closeSidebar() {
    document.body.classList.remove("sidebar-open");
    document.querySelectorAll("[data-sidebar-toggle]").forEach(function (toggle) {
      toggle.setAttribute("aria-expanded", "false");
    });
  }

  function toggleSidebar() {
    var isOpen = document.body.classList.toggle("sidebar-open");
    document.querySelectorAll("[data-sidebar-toggle]").forEach(function (toggle) {
      toggle.setAttribute("aria-expanded", String(isOpen));
    });
  }

  function initMobileNav() {
    document.querySelectorAll("nav[data-mobile-nav]").forEach(function (nav) {
      var toggle = nav.querySelector("[data-menu-toggle]");
      if (!toggle) {
        return;
      }

      toggle.addEventListener("click", function (event) {
        event.stopPropagation();
        var willOpen = !nav.classList.contains("nav-open");
        closeAllNavs();
        nav.classList.toggle("nav-open", willOpen);
        toggle.setAttribute("aria-expanded", String(willOpen));
        document.body.classList.toggle("mobile-menu-open", willOpen);
      });

      nav.querySelectorAll(".nav-links a, .nav-cta a, .nav-cta button").forEach(function (link) {
        link.addEventListener("click", function () {
          if (window.innerWidth < 1024) {
            closeNav(nav);
          }
        });
      });
    });
  }

  function initSidebars() {
    var sidebar = document.querySelector(".sidebar");
    if (!sidebar) {
      return;
    }

    var overlay = document.querySelector("[data-sidebar-overlay]");
    if (!overlay) {
      overlay = document.createElement("div");
      overlay.className = "sidebar-overlay";
      overlay.setAttribute("data-sidebar-overlay", "");
      sidebar.insertAdjacentElement("afterend", overlay);
    }

    overlay.addEventListener("click", closeSidebar);

    document.querySelectorAll("[data-sidebar-toggle]").forEach(function (toggle) {
      toggle.addEventListener("click", function () {
        toggleSidebar();
      });
    });

    sidebar.querySelectorAll("a, button").forEach(function (item) {
      item.addEventListener("click", function () {
        if (window.innerWidth < 1024) {
          closeSidebar();
        }
      });
    });
  }

  document.addEventListener("click", function (event) {
    if (!event.target.closest("nav[data-mobile-nav]")) {
      closeAllNavs();
    }

    if (!event.target.closest(".sidebar") && !event.target.closest("[data-sidebar-toggle]")) {
      closeSidebar();
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      closeAllNavs();
      closeSidebar();
    }
  });

  window.addEventListener("resize", function () {
    if (window.innerWidth >= 1024) {
      closeAllNavs();
      closeSidebar();
    }
  });

  document.addEventListener("DOMContentLoaded", function () {
    initMobileNav();
    initSidebars();
  });
})();
