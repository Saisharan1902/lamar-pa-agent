// "Start a New Request" page: cards revealed in order, as in the trace.
// Elements are found via data-* attributes only, so randomized ids don't matter.
(function () {
  "use strict";
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const CFG = JSON.parse($("#portal-config").textContent);
  const on = (n) => CFG.scn.includes(n);
  const card = (n) => $(`[data-card="${n}"]`);
  const ctl = (field) => { const b = $(`[data-field="${field}"]`); return b && $("input, select, button[role=combobox]", b); };

  const state = { drug: null, patient: null, insuranceState: "", searchSeq: 0, starting: false };

  function reveal(name) {
    const c = card(name);
    if (c.hidden) { c.hidden = false; c.scrollIntoView({ block: "nearest" }); }
    if (name === "patient" && window.portalStartSessionTimer) window.portalStartSessionTimer();
  }
  function expired(res) {
    if (res.status === 401) { location.href = "/login?expired=1"; return true; }
    return false;
  }

  // ---------- field errors (aria-invalid + aria-describedby, like real portals)
  let errSeq = 0;
  function setError(field, msg) {
    const box = $(`[data-field="${field}"]`);
    if (!box) return;
    const old = $(":scope > .field-error", box);
    if (old) old.remove();
    box.classList.remove("has-error");
    const input = box.matches("fieldset") ? box : ctl(field);
    if (input) { input.removeAttribute("aria-invalid"); input.removeAttribute("aria-describedby"); }
    if (!msg) return;
    const div = document.createElement("div");
    div.className = "field-error"; div.id = "err-" + (++errSeq); div.textContent = msg;
    box.appendChild(div); box.classList.add("has-error");
    if (input) { input.setAttribute("aria-invalid", "true"); input.setAttribute("aria-describedby", div.id); }
  }
  function clearErrors(fields) { fields.forEach((f) => setError(f, null)); }
  function toast(msg) {
    let t = $(".toast");
    if (!t) { t = document.createElement("div"); t.className = "toast"; t.setAttribute("role", "alert"); $("main").prepend(t); }
    t.textContent = msg;
  }

  // ---------- generic autocomplete (medication, diagnosis)
  function combo(field, url, render, pick) {
    const box = $(`[data-field="${field}"]`);
    const input = $("[data-combo-input]", box), list = $("[data-combo-list]", box);
    let seq = 0;
    input.addEventListener("input", () => {
      const q = input.value.trim(), mine = ++seq;
      pick(null);
      if (q.length < 2) { list.hidden = true; return; }
      fetch(url + encodeURIComponent(q)).then((r) => r.json()).then((items) => {
        if (mine !== seq) return;
        list.innerHTML = "";
        if (!items.length) {
          const li = document.createElement("li"); li.className = "no-results"; li.setAttribute("role", "status");
          li.textContent = "No Results"; list.appendChild(li);
        }
        items.forEach((it) => {
          const li = document.createElement("li"); li.setAttribute("role", "option"); li.textContent = render(it);
          li.addEventListener("mousedown", (e) => {
            e.preventDefault(); input.value = render(it); list.hidden = true;
            input.setAttribute("aria-expanded", "false"); pick(it);
          });
          list.appendChild(li);
        });
        list.hidden = false; input.setAttribute("aria-expanded", "true");
      });
    });
    input.addEventListener("blur", () => setTimeout(() => { list.hidden = true; }, 150));
  }

  combo("medication_search", "/api/drugs?q=", (d) => d.name, (d) => {
    state.drug = d;
    if (d) { reveal("diagnosis"); searchForms(); }
  });
  const dxContinue = $('[data-action="continue-dx"]');
  combo("diagnosis", "/api/diagnoses?q=", (d) => d.name, (d) => { dxContinue.disabled = !d; });
  $('[data-action="skip-dx"]').addEventListener("click", () => reveal("patient"));
  dxContinue.addEventListener("click", () => reveal("patient"));
  $('[data-action="clear-dx"]').addEventListener("click", () => {
    $('[data-field="diagnosis"] input').value = ""; dxContinue.disabled = true;
  });

  // ---------- patient card
  const zip = ctl("patient_zip");
  // The state row appears once a 5-digit ZIP is entered, already filled from the ZIP (as in the trace).
  let zipSeq = 0;
  zip.addEventListener("input", () => {
    const z = zip.value.trim(), mine = ++zipSeq;
    if (!/^\d{5}$/.test(z)) return;
    fetch("/api/zip-state?zip=" + z).then((r) => r.json()).then((b) => {
      if (mine !== zipSeq) return;
      ptState.set(b.state);
      $('[data-field="insurance_state"]').hidden = false;
    });
  });
  const PATIENT_FIELDS = ["first_name", "last_name", "sex", "date_of_birth", "patient_zip", "insurance_state"];
  function readPatient() {
    const sex = $('input[name="sex"]:checked');
    return { first_name: ctl("first_name").value, last_name: ctl("last_name").value, sex: sex ? sex.value : "",
             date_of_birth: ctl("date_of_birth").value, patient_zip: zip.value, insurance_state: ptState.get() };
  }
  function submitPatient(confirmNew) {
    const p = readPatient();
    fetch("/api/patient", { method: "POST", headers: { "Content-Type": "application/json" },
                            body: JSON.stringify(Object.assign({ confirm_new: !!confirmNew }, p)) })
      .then((res) => {
        if (expired(res)) return null;
        return res.json().then((body) => ({ res, body }));
      })
      .then((x) => {
        if (!x) return;
        clearErrors(PATIENT_FIELDS);
        if (x.body.errors) { Object.entries(x.body.errors).forEach(([f, m]) => setError(f, m)); return; }
        if (x.body.duplicate) { $('[data-modal="duplicate"]').hidden = false; return; }
        state.patient = p;
        reveal("insurance");
        if (!on("state_not_prefilled") && p.insurance_state) setInsState(p.insurance_state);
        searchForms();
      });
  }
  $('[data-action="continue-patient"]').addEventListener("click", () => submitPatient(false));
  $('[data-action="skip-patient"]').addEventListener("click", () => reveal("insurance"));
  $('[data-action="clear-patient"]').addEventListener("click", () => {
    $$('[data-card="patient"] input[type=text], [data-card="patient"] input[type=date]').forEach((i) => { i.value = ""; });
    $$('[data-card="patient"] input[type=radio]').forEach((i) => { i.checked = false; });
  });
  $('[data-action="dup-new"]').addEventListener("click", () => { $('[data-modal="duplicate"]').hidden = true; submitPatient(true); });
  $('[data-action="dup-existing"]').addEventListener("click", () => { $('[data-modal="duplicate"]').hidden = true; });

  // ---------- custom searchable state dropdowns (patient card + insurance card)
  // Options exist in the DOM only while a dropdown is open (like the real portal).
  const STATES = JSON.parse($("#portal-states").textContent);
  function makeDropdown(name, onPick) {
    const btn = $(`[data-dropdown="${name}"]`), box = btn.closest(".field");
    const popup = $("[data-popup]", box), search = $("[data-dd-search]", box), list = $('[role="listbox"]', box);
    let value = "";
    const close = () => { popup.hidden = true; list.innerHTML = ""; btn.setAttribute("aria-expanded", "false"); };
    const set = (code) => { value = code || ""; $("[data-value-text]", btn).textContent = STATES[code] || "Select"; };
    const fill = (q) => {
      list.innerHTML = "";
      Object.entries(STATES).forEach(([code, nm]) => {
        if (q && !nm.toLowerCase().startsWith(q) && code.toLowerCase() !== q) return;
        const li = document.createElement("li"); li.setAttribute("role", "option"); li.textContent = nm;
        li.addEventListener("click", () => { set(code); close(); onPick(code); });
        list.appendChild(li);
      });
    };
    btn.addEventListener("click", () => {
      if (!popup.hidden) { close(); return; }
      popup.hidden = false; btn.setAttribute("aria-expanded", "true"); search.value = ""; fill(""); search.focus();
    });
    search.addEventListener("input", () => fill(search.value.trim().toLowerCase()));
    return { set, get: () => value };
  }
  const ptState = makeDropdown("patient", () => {});
  const insState = makeDropdown("insurance", (code) => { state.insuranceState = code; searchForms(); });
  function setInsState(code) { state.insuranceState = code; insState.set(code); }

  // ---------- live form search
  let timer = null;
  ["rx_bin", "rx_pcn", "rx_group"].forEach((f) => ctl(f).addEventListener("input", () => {
    clearTimeout(timer); timer = setTimeout(searchForms, 700);
  }));
  const results = $("[data-results]");
  function searchForms() {
    const bin = ctl("rx_bin").value.trim();
    if (!state.drug || !state.patient || !state.insuranceState || !bin) return;
    const mine = ++state.searchSeq;
    results.setAttribute("aria-busy", "true");
    results.innerHTML = '<div class="spinner" role="progressbar" aria-label="Finding forms"></div><p class="muted center">Finding forms…</p>';
    const qs = new URLSearchParams({ bin, pcn: ctl("rx_pcn").value.trim(), group_id: ctl("rx_group").value.trim(),
                                     state: state.insuranceState, drug_id: state.drug.id });
    fetch("/api/forms?" + qs).then((res) => {
      if (expired(res)) return null;
      return res.json().then((body) => ({ res, body }));
    }).then((x) => {
      if (!x || mine !== state.searchSeq) return;
      results.removeAttribute("aria-busy");
      clearErrors(["rx_bin", "rx_pcn", "rx_group"]);
      if (x.body.errors) {
        Object.entries(x.body.errors).forEach(([f, m]) => setError(f === "insurance_state" ? "insurance_state_ins" : f, m));
        results.innerHTML = '<p class="muted">Form results will display here</p>';
        return;
      }
      renderForms(x.body.forms, x.body.message);
    });
  }
  let surveyShown = false;
  function formCard(f, primary) {
    return `<article class="form-card${primary ? " recommended" : ""}" data-form-id="${f.id}">
      <div class="thumb" aria-hidden="true"></div>
      <div class="form-body">
        <p class="benefit">${f.benefit}</p>
        <h3>${f.title}</h3>
        <p>${f.directions}</p>
        <form class="form-actions" id="submit-pa-${f.id}" data-start="${f.id}">
          <button type="button" class="btn-text">More Info</button>
          <button type="submit" class="btn-primary" title="Start request for ${f.title}">Start Request</button>
        </form>
      </div></article>`;
  }
  function renderForms(forms, message) {
    if (forms.length && on("payer_eligibility") && !state.eligibilityDone) {
      // Optional eligibility offer shown before the forms (#payer-eligibility-*-button in Lamar's own automation).
      results.innerHTML = `<section class="eligibility" aria-labelledby="pe-title">
        <h3 id="pe-title">Check pharmacy benefits eligibility?</h3>
        <p>We can check this patient's pharmacy benefits with the plan before you choose a PA form.</p>
        <div class="form-actions">
          <button type="button" class="btn-primary" id="payer-eligibility-primary-button">Yes, Check Eligibility</button>
          <button type="button" class="btn-text" id="payer-eligibility-secondary-button">No, Proceed to PA Forms</button>
        </div></section>`;
      $("#payer-eligibility-primary-button", results).addEventListener("click", () => toast("Eligibility checks are not available right now."));
      $("#payer-eligibility-secondary-button", results).addEventListener("click", () => {
        state.eligibilityDone = true; renderForms(forms, message);
      });
      return;
    }
    if (!forms.length) {
      results.innerHTML = `<p class="notice warn" role="status">${message || "No forms were found."}</p>`;
      return;
    }
    const [top, ...rest] = forms;
    results.innerHTML = `<p class="small muted">Suggested form</p>${formCard(top, true)}` +
      (rest.length ? `<button type="button" class="btn-outline" id="showMoreForms" data-action="more-forms">Show ${rest.length} More</button>
         <div class="more-forms" hidden>${rest.map((f) => formCard(f, false)).join("")}</div>` : "");
    const more = $('[data-action="more-forms"]', results);
    if (more) more.addEventListener("click", () => { $(".more-forms", results).hidden = false; more.remove(); });
    $$("form[data-start]", results).forEach((fm) => fm.addEventListener("submit", (e) => {
      e.preventDefault();
      if (on("native_confirm") && !window.confirm(`Start a new prior authorization request for ${state.patient.first_name} ${state.patient.last_name}?`)) return;
      startRequest(parseInt(fm.dataset.start, 10), $('[type="submit"]', fm));
    }));
    if (on("survey_overlay") && !surveyShown) { surveyShown = true; $('[data-modal="survey"]').hidden = false; }
  }

  // ---------- Start Request
  function startRequest(formId, btn, acks) {
    if (state.starting) return;
    state.starting = true; if (btn) btn.disabled = true;
    const body = { token: CFG.token, form_id: formId, drug_id: state.drug.id, patient: state.patient, acks: acks || [],
                   insurance: { insurance_state: state.insuranceState, rx_bin: ctl("rx_bin").value.trim(),
                                rx_pcn: ctl("rx_pcn").value.trim(), rx_group: ctl("rx_group").value.trim() } };
    fetch("/api/requests", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then((res) => {
        if (expired(res)) return null;
        return res.json().then((b) => ({ res, b }));
      })
      .then((x) => {
        state.starting = false; if (btn) btn.disabled = false;
        if (!x) return;
        if (x.b.url) { location.href = x.b.url; return; }
        if (x.b.alternatives) { showAlternatives(formId, x.b.alternatives, acks || []); return; }
        if (x.b.existing) { showExisting(formId, x.b.existing, acks || []); return; }
        if (x.b.errors) Object.entries(x.b.errors).forEach(([f, m]) => setError(f, m));
        toast(x.b.message || "Something went wrong.");
      })
      .catch(() => { state.starting = false; if (btn) btn.disabled = false; toast("Network error. Your request status is unknown."); });
  }

  // Scenario therapeutic_alternatives: the plan suggests other drugs; "Continue Prior Auth" keeps the prescribed one.
  function showAlternatives(formId, alts, acks) {
    results.innerHTML = `<section class="alternatives" aria-labelledby="alt-title">
      <h3 id="alt-title">Therapeutic Alternatives</h3>
      <p>The plan covers these alternatives to ${state.drug.name} without a prior authorization.</p>
      <table id="form-alts-table"><thead><tr><th>Medication</th><th>Coverage</th><th></th></tr></thead><tbody>
      ${alts.map((a) => `<tr><td>${a.name}</td><td>${a.coverage}</td>
        <td><button type="button" class="btn-outline" data-action="choose-alt">Choose ${a.name.split(" ")[0]}</button></td></tr>`).join("")}
      </tbody></table>
      <div class="form-actions"><button type="button" class="btn-primary" data-action="continue-pa">Continue Prior Auth</button></div>
    </section>`;
    $$('[data-action="choose-alt"]', results).forEach((b) => b.addEventListener("click", () =>
      toast("Ask the prescriber for a new prescription to switch medications.")));
    $('[data-action="continue-pa"]', results).addEventListener("click", (e) =>
      startRequest(formId, e.currentTarget, acks.concat(["alternatives"])));
  }
  // Scenarios existing_pa / existing_pa_expired: CMM's existing-PA modal.
  function showExisting(formId, ex, acks) {
    const m = $('[data-modal="existing-pa"]');
    $("[data-existing-body]", m).textContent =
      `A prior authorization for this patient and medication already exists. Key: ${ex.key}  Status: ${ex.status}  Created: ${ex.created}`;
    m.hidden = false;
    $('[data-action="existing-new"]', m).onclick = () => { m.hidden = true; startRequest(formId, null, acks.concat(["existing"])); };
    $('[data-action="existing-cancel"]', m).onclick = () => { m.hidden = true; };
  }
})();
