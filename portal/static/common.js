// Popups shared by every page. Nothing depends on element ids (they may be randomized).
(function () {
  "use strict";
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));

  // modals: close buttons. Modals without a delay attribute show immediately.
  $$("[data-modal]").forEach((m) => {
    $$("[data-close]", m).forEach((b) => b.addEventListener("click", () => {
      m.hidden = true;
      if (m.dataset.modal === "session") clearTimeout(window.__sessionTimer);
    }));
  });

  // session warning: shown by the page via window.portalStartSessionTimer()
  window.portalStartSessionTimer = function () {
    const m = $('[data-modal="session"]');
    if (!m || m.dataset.started) return;
    m.dataset.started = "1";
    const delay = parseInt(m.dataset.delay || "1000", 10);
    setTimeout(() => {
      m.hidden = false;
      window.__sessionTimer = setTimeout(() => { location.href = "/logout?reason=timeout"; }, 15000);
    }, delay);
  };

  // dismissible widgets
  $$("[data-dismiss]").forEach((b) => b.addEventListener("click", () => {
    const w = $(`[data-widget="${b.dataset.dismiss}"]`);
    if (w) w.remove();
    const p = $('[data-panel="faqs"]');
    if (b.dataset.dismiss === "chat" && p) p.hidden = true;
  }));
  const faqs = $('[data-action="faqs"]');
  if (faqs) faqs.addEventListener("click", () => { $('[data-panel="faqs"]').hidden = false; });
  $$("[data-close-panel]").forEach((b) => b.addEventListener("click", () => { b.closest("[data-panel]").hidden = true; }));
})();
