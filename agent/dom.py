"""In-page JavaScript used to read a portal the way a person would.

Everything is found by accessible label, fieldset/heading context and ARIA role.
No ids, classes or coordinates, so the same code can read an unseen portal.
Elements are tagged with data-agent-* attributes so Python can act on exactly
the element that was inspected.
"""
import time as _time

from playwright.sync_api import Error as _PWError


def evaluate(page, script, arg=None, tries=4):
    """page.evaluate that survives the page navigating underneath it (e.g. a redirect to
    the login page): wait for the new document and read again."""
    for i in range(tries):
        try:
            return page.evaluate(script) if arg is None else page.evaluate(script, arg)
        except _PWError as e:
            msg = str(e)
            if i == tries - 1 or not any(s in msg for s in ("Execution context was destroyed",
                                                             "navigation", "Target page, context or browser")):
                raise
            try:
                page.wait_for_load_state("domcontentloaded", timeout=8000)
            except _PWError:
                pass
            _time.sleep(0.2)

COMMON = r"""
const vis = (el) => {
  if (!el || !el.isConnected) return false;
  if (el.closest('[hidden]')) return false;
  const s = getComputedStyle(el);
  if (s.display === 'none' || s.visibility === 'hidden' || +s.opacity === 0) return false;
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0;
};
const txt = (el) => (el ? (el.innerText || el.textContent || '') : '').replace(/\s+/g, ' ').trim();
const byIds = (ids) => (ids || '').split(/\s+/).filter(Boolean)
  .map((id) => txt(document.getElementById(id))).join(' ').trim();
const labelOf = (el) => {
  let t = byIds(el.getAttribute('aria-labelledby'));
  if (!t && el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) t = txt(l); }
  if (!t) { const l = el.closest('label'); if (l) t = txt(l); }
  if (!t) t = el.getAttribute('aria-label') || '';
  if (!t) t = el.getAttribute('placeholder') || el.getAttribute('title') || '';
  return t;
};
const HEADINGS = 'h1,h2,h3,h4,h5,legend,[role="heading"]';
const precedingHeading = (el) => {
  let best = '';
  for (const h of document.querySelectorAll(HEADINGS)) {
    if (!vis(h)) continue;
    if (h.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) best = txt(h); else break;
  }
  return best;
};
const sectionOf = (el, skipFieldset) => {
  let fs = el.closest('fieldset');
  if (fs && fs === skipFieldset) fs = fs.parentElement && fs.parentElement.closest('fieldset');
  if (fs) { const lg = fs.querySelector(':scope > legend'); if (lg) return txt(lg); }
  return precedingHeading(el);
};
// A "section" is the nearest ancestor that contains a heading: a card, a form card, a page.
const sectionRoot = (el) => {
  let a = el.parentElement;
  while (a && a !== document.body) {
    if (a.querySelector('h1,h2,h3,h4,[role="heading"]')) return a;
    a = a.parentElement;
  }
  return document.body;
};
const sectionId = (el) => {
  const root = sectionRoot(el);
  if (!root.hasAttribute('data-agent-s')) {
    window.__agentSec = (window.__agentSec || 0) + 1;
    root.setAttribute('data-agent-s', String(window.__agentSec));
  }
  return root.getAttribute('data-agent-s');
};
const inOverlay = (el) => !!el.closest('[role="dialog"],[role="alertdialog"],[aria-modal="true"],[data-agent-i]');
const primaryRoot = () => document.querySelector('main,[role="main"]') || document.body;
const inPrimary = (el) => primaryRoot().contains(el) &&
  !el.closest('aside,[role="complementary"],nav,header,footer,[role="navigation"]');
const committedSelection = (el) => {
  const root = el.closest('label') || el.closest('fieldset,[role="group"]') || el.parentElement;
  if (!root) return {hasBacking:false, values:[], labels:[]};
  const hidden = [...root.querySelectorAll('input[type="hidden"]')];
  const labels = [...root.querySelectorAll('span,div,output,[aria-selected="true"],[role="listitem"]')]
    .filter(e => vis(e) && !e.contains(el) && !e.closest('[role="listbox"]') &&
      !e.querySelector('input,select,textarea,[role="option"]') && txt(e))
    .map(txt);
  return {hasBacking:hidden.length > 0, values:hidden.map(e=>e.value).filter(Boolean),
          labels:[...new Set(labels)]};
};
"""

DISCOVER_CONTROLS = COMMON + r"""
() => {
  document.querySelectorAll('[data-agent-f]').forEach((e) => e.removeAttribute('data-agent-f'));
  const out = []; const seenRadio = new Set();
  const all = document.querySelectorAll('input, select, textarea, [role="combobox"]:not(input)');
  for (const el of all) {
    const type = (el.getAttribute('type') || el.tagName).toLowerCase();
    if (['hidden', 'submit', 'button', 'image', 'reset', 'file'].includes(type) && el.getAttribute('role') !== 'combobox') continue;
    if (inOverlay(el) || !inPrimary(el)) continue;
    if (type === 'radio') {
      if (seenRadio.has(el.name)) continue;
      const group = Array.from(document.querySelectorAll(`input[type="radio"][name="${CSS.escape(el.name)}"]`)).filter(vis);
      if (!group.length) continue;
      seenRadio.add(el.name);
      const fs = el.closest('fieldset'); const rg = el.closest('[role="radiogroup"]');
      let label = '';
      if (rg) label = byIds(rg.getAttribute('aria-labelledby')) || rg.getAttribute('aria-label') || '';
      if (!label && fs) { const lg = fs.querySelector(':scope > legend'); if (lg) label = txt(lg); }
      const idx = out.length;
      const options = group.map((r, j) => { r.setAttribute('data-agent-f', idx + ':' + j);
        return { text: labelOf(r), value: r.value, checked: r.checked }; });
      out.push({ idx, kind: 'radio', label, section: sectionOf(el, fs), options, sid: sectionId(el), disabled: false,
                 required: /\*/.test(label) || group.some((r) => r.required),
                 value: (options.find((o) => o.checked) || {}).value || '' });
      continue;
    }
    if (!vis(el)) continue;
    const idx = out.length; el.setAttribute('data-agent-f', String(idx));
    const label = labelOf(el);
    let kind = el.tagName === 'SELECT' ? 'select' : el.tagName === 'TEXTAREA' ? 'text' : 'text';
    if (type === 'checkbox') kind = 'checkbox';
    if (type === 'password') kind = 'password';
    if (el.getAttribute('role') === 'combobox' && el.tagName !== 'SELECT') kind = 'combobox';
    if (el.getAttribute('role') === 'combobox' && el.tagName !== 'INPUT' && el.tagName !== 'SELECT') kind = 'listbutton';
    if (['list', 'both'].includes(el.getAttribute('aria-autocomplete'))) kind = 'combobox';
    const rec = { idx, kind, label, section: sectionOf(el), type,
      placeholder: el.getAttribute('placeholder') || '',
      required: el.required || el.getAttribute('aria-required') === 'true' || /\*/.test(label),
      disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true', readonly: !!el.readOnly,
      formatHint: (el.getAttribute('placeholder') || '') + ' ' + byIds(el.getAttribute('aria-describedby')),
      sid: sectionId(el),
      value: kind === 'listbutton' ? txt(el) : (el.value || '') };
    if (kind === 'combobox') rec.committed = committedSelection(el);
    if (kind === 'select') {
      rec.options = Array.from(el.options).map((o) => ({ text: txt(o), value: o.value, disabled: o.disabled }));
      rec.value = el.value; rec.valueText = el.selectedIndex >= 0 ? txt(el.options[el.selectedIndex]) : '';
    }
    if (kind === 'checkbox') rec.value = el.checked ? 'on' : '';
    out.push(rec);
  }
  return out;
}
"""

SCAN_INTERRUPTIONS = COMMON + r"""
() => {
  document.querySelectorAll('[data-agent-i]').forEach((e) => e.removeAttribute('data-agent-i'));
  document.querySelectorAll('[data-agent-b]').forEach((e) => e.removeAttribute('data-agent-b'));
  const found = [];
  const dialogs = Array.from(document.querySelectorAll('[role="dialog"],[role="alertdialog"],[aria-modal="true"],dialog[open]'))
    .filter(vis).filter((d, _, arr) => !arr.some((o) => o !== d && o.contains(d)));
  dialogs.forEach((d) => found.push({ el: d, kind: 'dialog' }));
  for (const el of document.body.querySelectorAll('*')) {
    const s = getComputedStyle(el);
    if (s.position !== 'fixed' || !vis(el)) continue;
    if (['HEADER', 'NAV'].includes(el.tagName)) continue;
    if (dialogs.some((d) => el.contains(d) || d.contains(el))) continue;
    if (found.some((f) => f.el.contains(el))) continue;
    found.push({ el, kind: 'overlay' });
  }
  return found.map((f, i) => {
    f.el.setAttribute('data-agent-i', String(i));
    const title = txt(f.el.querySelector('h1,h2,h3,[role="heading"]')) ||
                  byIds(f.el.getAttribute('aria-labelledby')) || f.el.getAttribute('aria-label') || '';
    const buttons = Array.from(f.el.querySelectorAll('button, a, [role="button"], input[type="button"], input[type="submit"]'))
      .filter(vis).map((b, j) => { b.setAttribute('data-agent-b', i + ':' + j);
        return { j, text: (txt(b) || b.getAttribute('aria-label') || b.value || '').trim(),
                 aria: b.getAttribute('aria-label') || '' }; });
    return { i, kind: f.kind, title, label: f.el.getAttribute('aria-label') || '',
             text: txt(f.el).slice(0, 400), buttons };
  });
}
"""

SCAN_ERRORS = COMMON + r"""
() => {
  const out = []; const seen = new Set();
  const sel = '[role="alert"], [aria-live="assertive"], [class*="error" i], [class*="invalid" i]';
  for (const e of document.querySelectorAll(sel)) {
    if (!vis(e) || !inPrimary(e) || seen.has(e)) continue;
    if (e.querySelector('input, select, textarea')) continue;       // a wrapper, not a message
    const t = txt(e); if (!t || t.length > 400) continue;
    if (out.some((o) => o.text === t)) continue;
    seen.add(e);
    let label = '';
    const described = document.querySelector(`[aria-describedby~="${CSS.escape(e.id || '__none__')}"]`);
    if (described) label = described.tagName === 'FIELDSET' ? txt(described.querySelector('legend')) : labelOf(described);
    if (!label) {
      let n = e.parentElement;
      for (let k = 0; k < 4 && n && !label; k++, n = n.parentElement) {
        const ctl = n.querySelectorAll('input:not([type=hidden]), select, textarea');
        if (ctl.length === 1) label = labelOf(ctl[0]);
        else if (n.tagName === 'TR') label = txt(n.querySelector('th'));
        else if (n.tagName === 'FIELDSET') label = txt(n.querySelector('legend'));
      }
    }
    out.push({ text: t, label });
  }
  return out;
}
"""

SCAN_BUTTONS = COMMON + r"""
() => {
  document.querySelectorAll('[data-agent-a]').forEach((e) => e.removeAttribute('data-agent-a'));
  const els = document.querySelectorAll('button, input[type="submit"], input[type="button"], [role="button"], a');
  const out = [];
  for (const b of els) {
    if (!vis(b) || inOverlay(b) || !inPrimary(b)) continue;
    const type = (b.getAttribute('type') || '').toLowerCase();
    const text = (txt(b) || b.value || b.getAttribute('aria-label') || '').trim();
    if (!text) continue;
    const i = out.length; b.setAttribute('data-agent-a', String(i));
    out.push({ i, text, tag: b.tagName.toLowerCase(), type, disabled: !!b.disabled || b.getAttribute('aria-disabled') === 'true' });
  }
  return out;
}
"""

PAGE_STATE = COMMON + r"""
() => ({
  text: (primaryRoot().innerText || '').replace(/[ \t]+/g, ' ').slice(0, 20000),
  busy: Array.from(document.querySelectorAll('[aria-busy="true"], [role="progressbar"]')).some(e=>vis(e)&&inPrimary(e)),
  password: Array.from(document.querySelectorAll('input[type="password"]')).some(vis),
  title: document.title,
})
"""

LISTBOX_OPTIONS = COMMON + r"""
(idx) => {
  const el = document.querySelector(`[data-agent-f="${idx}"]`);
  let box = el && el.getAttribute('aria-controls') ? document.getElementById(el.getAttribute('aria-controls')) : null;
  const scope = box && vis(box) ? box : document;
  document.querySelectorAll('[data-agent-o]').forEach((e) => e.removeAttribute('data-agent-o'));
  const opts = Array.from(scope.querySelectorAll('[role="option"]')).filter(vis)
    .map((o, j) => { o.setAttribute('data-agent-o', String(j)); return { j, text: txt(o) }; });
  const none = /no (results|matches|options)/i.test(txt(box || document.body).slice(0, 2000)) && !opts.length;
  return { options: opts, noResults: none };
}
"""

SCAN_PAGE = COMMON + r"""
() => {
  document.querySelectorAll('[data-agent-a]').forEach((e) => e.removeAttribute('data-agent-a'));
  const els = document.querySelectorAll('button, input[type="submit"], input[type="button"], [role="button"], a');
  const buttons = []; const sections = {};
  for (const b of els) {
    if (!vis(b) || inOverlay(b) || !inPrimary(b)) continue;
    if (b.getAttribute('role') === 'combobox') continue;
    const type = (b.getAttribute('type') || '').toLowerCase();
    const text = (txt(b) || b.value || b.getAttribute('aria-label') || '').trim();
    if (!text) continue;
    const i = buttons.length; b.setAttribute('data-agent-a', String(i));
    const sid = sectionId(b);
    buttons.push({ i, text, tag: b.tagName.toLowerCase(), type, sid,
                   formAction: b.form ? b.form.action : null,
                   formMethod: b.form ? b.form.method.toUpperCase() : null,
                   versions: b.form ? [...b.form.querySelectorAll('input[type="hidden"]')]
                     .filter(e=>/(?:^|[_-])(revision|version|etag)(?:$|[_-])/i.test(e.name))
                     .map(e=>[e.name,e.value]) : [],
                   disabled: !!b.disabled || b.getAttribute('aria-disabled') === 'true' });
  }
  document.querySelectorAll('[data-agent-s]').forEach((root) => {
    if (!vis(root) && root !== document.body) return;
    const h = root.querySelector('h1,h2,h3,h4,[role="heading"]');
    sections[root.getAttribute('data-agent-s')] = {
      title: txt(h), busy: !!root.querySelector('[aria-busy="true"], [role="progressbar"]') || root.getAttribute('aria-busy') === 'true',
      text: txt(root).slice(0, 600) };
  });
  return { buttons, sections };
}
"""

LISTBUTTON_SEARCH = COMMON + r"""
(idx) => {
  // After opening a custom dropdown: find the search box it offers, if any.
  document.querySelectorAll('[data-agent-q]').forEach((e) => e.removeAttribute('data-agent-q'));
  const el = document.querySelector(`[data-agent-f="${idx}"]`);
  let cand = document.activeElement;
  if (!(cand && cand.tagName === 'INPUT' && cand !== el && vis(cand))) {
    cand = null;
    const box = el && el.getAttribute('aria-controls') ? document.getElementById(el.getAttribute('aria-controls')) : null;
    const scope = box ? box.parentElement : (el && el.parentElement);
    if (scope) cand = Array.from(scope.querySelectorAll('input')).find((i) => vis(i) && !['hidden', 'radio', 'checkbox'].includes(i.type));
  }
  if (!cand) return false;
  cand.setAttribute('data-agent-q', '1');
  return true;
}
"""

READ_COMBO_STATE = COMMON + r"""
(idx) => {
  const el = document.querySelector(`[data-agent-f="${idx}"]`);
  return el ? {value:el.value || '', committed:committedSelection(el)} : null;
}
"""
