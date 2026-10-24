"""The agent: one patient record in, one outcome out.

  1. Validate the record (pure Python). Any issue -> ESCALATED, portal untouched.
  2. Check the ledger. Already started -> stored result. Unknown -> ESCALATED.
  3. Drive the portal with a generic, section-aware loop:
       settle -> dismiss benign popups -> sign in if asked -> result page? ->
       fill every visible control it recognises ->
       act on the first section (card) that needs it, in page order:
         Continue (enabled)            -> click, check for field errors
         'Enter This Later' / 'Skip'   -> only for a section holding no contract data
         form list / final Submit      -> choose the form, start the request
  4. Write result JSON + action log.

Nothing here names a Portal A page. The loop knows "pages have sections with
fields and buttons", which is what lets it attempt an unseen portal.
"""
import os
import re
import time
import hashlib
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Error as PWError
from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

from . import fields as F
from . import interrupts
from .actionlog import ActionLog, mask
from .dom import evaluate as _evaluate
from .dom import (DISCOVER_CONTROLS, LISTBOX_OPTIONS, LISTBUTTON_SEARCH, PAGE_STATE, READ_COMBO_STATE,
                  SCAN_ERRORS, SCAN_PAGE)
from .errors import Escalate
from .ledger import Ledger, record_key
from .validate import validate_record, parse_any_date
from .receipts import SCAN_RECEIPT, parse_document
from .widgets import selection_matches, commit_with_enter

MAX_STEPS = 40
RUN_BUDGET_S = 240
START_RETRIES = 2
SETTLE_MS = 700
IDLE_WAIT_S = 15            # how long to wait for async content (e.g. form search) before giving up

CONTINUE_RE = re.compile(r"^(continue|next|save (and|&) continue|proceed|next step|review( request| and submit)?$|"
                         r"continue to review|siguiente|continuar|revisar solicitud)\b", re.I)
SKIP_RE = re.compile(r"^(enter this later|skip( this step| for now)?|not now|do this later|i'll do this later|"
                     r"no,? (proceed|continue) to (the )?(pa|prior auth(orization)?) forms?)\b", re.I)
START_RE = re.compile(r"^(start (request|pa|prior auth(orization)?)|use this form|select (this )?form|choose (this )?form)\b", re.I)
SUBMIT_RE = re.compile(r"^(submit( request)?|send request|finish|complete request|enviar solicitud)\b", re.I)
MORE_RE = re.compile(r"^(show|view|see|load) (\d+ )?(more|all)\b", re.I)   # "Show 8 More" in the trace
LOGIN_RE = re.compile(r"^(sign ?in|log ?in)\b", re.I)

KEY_RE = re.compile(r"\(key:\s*[A-Z0-9]{6,}\)", re.I)
SUCCESS_RE = re.compile(r"submitted successfully|request (has been|was) (submitted|created|started|received)|"
                        r"request received|"
                        r"successfully (submitted|created)", re.I)
FAILURE_RE = re.compile(r"couldn't start|could not (start|be (processed|completed|submitted))|unable to start|"
                        r"not accepted|rejected|denied|submission failed|request failed", re.I)
CONF_RE = re.compile(r"(?:\(key:\s*|(?:reference|confirmation|request|case|tracking)\s*(?:number|no\.?|id|#|key)\s*[:#]?\s*)"
                     r"([A-Z0-9][A-Z0-9-]{5,})", re.I)
NO_FORMS_RE = re.compile(r"no forms (were )?found|no matching forms|no results found", re.I)
RETRYABLE_RE = re.compile(r"(?:request|submission) (?:was not|has not been) (?:submitted|created)", re.I)
LOAD_ERROR_RE = re.compile(r"error loading|unable to load|failed to load|something went wrong loading", re.I)
UNSAFE_RETRY_RE = re.compile(r"may have been|status is unknown|unknown status|check (the )?status", re.I)


def _result(status, reason, confirmation_id=None, filled=None, escalation=None, extra=None):
    r = {"status": status, "reason": reason, "confirmation_id": confirmation_id,
         "fields_filled": filled or {}, "escalation": escalation}
    if extra:
        r.update(extra)
    return r


class Agent:
    def __init__(self, portal_url, record, today, state_dir, headless=True, form_policy="first"):
        self.url = portal_url
        u = urlparse(portal_url)
        self.origin = f"{u.scheme}://{u.netloc}"
        self.raw = record
        self.today = today
        self.ledger = Ledger(state_dir)
        self.headless = headless
        self.form_policy = form_policy
        self.username = os.environ.get("PORTAL_USERNAME", "demo")
        self.password = os.environ.get("PORTAL_PASSWORD", "demo123")
        self.log = ActionLog()
        self.filled = {}
        self.observed = {}
        self.date_parts = {}
        self.date_orders = {}
        self.claimed = False
        self.attempted = False
        self.document_method = None
        self.reloaded = False
        self.security_refreshes = 0
        self.revision_refreshes = 0
        self.write_responses = []
        self.receipt_evidence = None
        self.form_selection = None
        self.logins = 0
        self.dialogs = []                # native alert/confirm/prompt dialogs, in order
        self.form_responses = []         # JSON responses that may carry the portal's form list

    # ------------------------------------------------------------------ entry
    def run(self):
        self.log.add("start", portal=self.origin, today=str(self.today))
        rec, issues = validate_record(self.raw, self.today)
        if issues:
            for i in issues:
                self.log.add("validation_issue", field=i.field)
            first = issues[0]
            more = f" (+{len(issues) - 1} more)" if len(issues) > 1 else ""
            return _result("ESCALATED", f"Record failed validation: {first.problem}{more}",
                           escalation=first.to_dict(),
                           extra={"all_issues": [i.to_dict() for i in issues]} if len(issues) > 1 else None)
        self.rec = rec
        self.key = record_key(self.origin, rec)
        prior = self.ledger.get(self.key)
        if prior and prior["state"] == "done":
            self.log.add("ledger_hit", state="done")
            return prior["result"]
        if prior and prior["state"] == "submitting":
            self.log.add("ledger_hit", state="submitting")
            return _result("ESCALATED", "A previous run was interrupted after starting the request; it may exist.",
                           escalation={"field": "submission",
                                       "problem": "Earlier run stopped after clicking Start with no confirmed outcome.",
                                       "suggested_action": "Search the portal dashboard for this patient's request "
                                                           "before retrying, then clear the agent ledger entry."})
        self.log.add("validated", fields=sorted(rec))
        return self._drive()

    def _drive(self):
        self.started = time.monotonic()
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            ctx = browser.new_context(viewport={"width": 1280, "height": 800}, locale="en-US",
                                      timezone_id="America/New_York", reduced_motion="reduce")
            self.page = ctx.new_page()
            self.page.set_default_timeout(10000)
            # Count in-flight requests ourselves: Playwright's "networkidle" is a one-time
            # page-load milestone and does not wait for requests made after the page loaded.
            self.inflight = set()
            self.page.on("request", lambda r: self.inflight.add(r))
            self.page.on("requestfinished", lambda r: self.inflight.discard(r))
            self.page.on("requestfailed", lambda r: self.inflight.discard(r))
            self.page.on("framenavigated", lambda f: f == self.page.main_frame and self.inflight.clear())
            self.page.on("dialog", self._on_dialog)
            self.page.on("response", self._on_response)
            try:
                return self._loop()
            except Escalate as e:
                state = self.ledger.get(self.key) if self.key else None
                if getattr(e, "nothing_created", False) and state and state["state"] == "submitting":
                    self.ledger.clear(self.key)          # the portal stopped before creating anything
                self.log.add("escalate", field=e.field)
                return _result("ESCALATED", e.problem, getattr(e, "confirmation_id", None), filled=self.filled,
                               escalation=e.to_dict(), extra=self._extra())
            except (PWTimeout, PWError) as e:
                state = self.ledger.get(self.key)
                after = bool(state and state["state"] == "submitting")
                self.log.add("browser_error", after_submit=after, error=type(e).__name__)
                msg = str(e).splitlines()[0][:200]
                if after:
                    return _result("ESCALATED", "Browser error after starting the request; status unknown.",
                                   filled=self.filled, escalation={"field": "submission", "problem": msg,
                                   "suggested_action": "Check the portal dashboard for this request before retrying."})
                return _result("ESCALATED", "The agent could not complete the portal flow.", filled=self.filled,
                               escalation={"field": "portal", "problem": msg,
                                           "suggested_action": "Open the portal and complete or inspect the request manually."})
            finally:
                browser.close()

    def _on_dialog(self, d):
        """Native browser dialogs. Never accept one: an alert has nothing to choose, a confirm is dismissed
        and then escalated, because we cannot tell what accepting it would do."""
        self.dialogs.append({"type": d.type, "message": d.message})
        msg = d.message[:120]
        for f in ("first_name", "last_name", "date_of_birth"):     # the log never holds patient identifiers
            v = (getattr(self, "rec", None) or {}).get(f)
            if v:
                msg = re.sub(re.escape(str(v)), mask(f, v), msg, flags=re.I)
        self.log.add("native_dialog", kind=d.type, message=msg)
        try:
            d.dismiss()
        except PWError:
            pass

    def _check_dialogs(self):
        for dl in self.dialogs:
            if dl["type"] != "alert" and not dl.get("seen"):
                dl["seen"] = True
                raise Escalate("portal", f"The portal asked for a confirmation the agent will not give: "
                                         f"'{dl['message'][:120]}'. It was dismissed.",
                               "A person should repeat this step in the portal and decide.")

    def _on_response(self, r):
        if self.attempted and r.request.method not in {"GET", "HEAD", "OPTIONS"}:
            self.write_responses.append({"url": r.url, "method": r.request.method, "status": r.status})
        if r.request.is_navigation_request() and r.frame == self.page.main_frame:
            self.document_method = r.request.method
        # Only remember candidates here; reading a body inside an event handler can stall the sync API.
        if "json" in (r.headers.get("content-type") or "") and r.request.resource_type in ("xhr", "fetch"):
            self.form_responses = (self.form_responses + [r])[-10:]

    def _api_form_titles(self):
        """The newest JSON response that is a forms list, as titles in order, or None."""
        for r in reversed(self.form_responses):
            try:
                titles = F.api_form_titles(r.json())
            except (PWError, ValueError):
                continue
            if titles is not None:
                return titles
        return None

    def _extra(self):
        extra = {}
        if self.form_selection:
            extra["form_selection"] = self.form_selection
        if self.receipt_evidence:
            extra["receipt_evidence"] = self.receipt_evidence
        return extra or None

    # ------------------------------------------------------------------ main loop
    def _loop(self):
        page = self.page
        self.log.add("goto", url=self.url.replace(self.origin, "") or "/")
        page.goto(self.url)
        advanced, idle_since = set(), None
        for _ in range(MAX_STEPS):
            if time.monotonic() - self.started > RUN_BUDGET_S:
                raise Escalate("portal", "Run exceeded its time budget.", "Complete the request manually.")
            self._settle()
            if self._eval("() => { const f = !window.__agentSeen; window.__agentSeen = true; return f; }"):
                advanced = set()                         # new document: nothing on it is done yet
            interrupts.handle(page, self.log)
            self._check_dialogs()
            state = self._eval(PAGE_STATE)
            if state["password"]:
                self._login(state)
                continue
            res = self._result_from_page(state)
            if res:
                return res

            self._fill_visible()
            scan = self._eval(SCAN_PAGE)
            action = self._next_action(scan, advanced)
            if action is None:
                # waiting for something asynchronous (typically the form search)
                if self._no_forms(scan, self._eval(PAGE_STATE)):
                    raise Escalate("form", "The portal found no forms for this medication and insurance.",
                                   "Check RxBIN/RxPCN/RxGroup and state, or search by plan name manually.")
                idle_since = idle_since or time.monotonic()
                if time.monotonic() - idle_since > IDLE_WAIT_S:
                    raise Escalate("portal", "Nothing left to fill or click, and no form list or result appeared.",
                                   "Open the portal and check where the request stopped.")
                page.wait_for_timeout(500)
                continue
            idle_since = None
            kind, sid, btn = action
            title = scan["sections"].get(sid, {}).get("title", "")
            if kind in ("start", "submit"):
                res = self._start(kind)
                if res:
                    return res
                continue                             # a review page or interstitial: keep going on it
            # Let late UI updates settle before checking values and leaving the section.
            # This also avoids racing a popup against the navigation click.
            self._settle()
            interrupts.handle(page, self.log)
            self._check_dialogs()
            self._verify_still_set()
            self._click(btn, kind, title)
            advanced.add(title or sid)
            if kind == "continue":
                self._check_errors_after()
        raise Escalate("portal", f"Did not finish within {MAX_STEPS} steps.", "Complete the request manually.")

    def _next_action(self, scan, advanced):
        """First section in page order that needs an action from us."""
        controls = self._controls_by_section()
        by_sid = {}
        for b in scan["buttons"]:
            by_sid.setdefault(b["sid"], []).append(b)
        order = sorted(by_sid, key=lambda s: min(b["i"] for b in by_sid[s]))
        for sid in order:
            info = scan["sections"].get(sid, {})
            title = info.get("title", "")
            btns = by_sid[sid]
            if any(START_RE.search(b["text"]) for b in btns):
                return ("start", sid, None)
            if (title or sid) in advanced:
                continue
            cont = next((b for b in btns if CONTINUE_RE.search(b["text"]) and not b["disabled"]), None)
            if cont:
                return ("continue", sid, cont)
            skip = next((b for b in btns if SKIP_RE.search(b["text"]) and not b["disabled"]), None)
            mine = controls.get(sid, [])
            if skip and not any(c["field"] for c in mine) and not any(c["required"] and not c["value"] for c in mine):
                return ("skip", sid, skip)
            if any(SUBMIT_RE.search(b["text"]) and not b["disabled"] for b in btns):
                return ("submit", sid, None)
        return None

    def _controls_by_section(self):
        out = {}
        for c in self._eval(DISCOVER_CONTROLS):
            c["field"] = F.classify(c["label"], c["section"])
            out.setdefault(c["sid"], []).append(c)
        return out

    def _no_forms(self, scan, state):
        return bool(NO_FORMS_RE.search(state["text"])) and not state["busy"]

    # ------------------------------------------------------------------ helpers
    def _settle(self):
        page = self.page
        try:
            page.wait_for_load_state("domcontentloaded")
        except PWTimeout:
            pass
        self._quiet()
        deadline = time.monotonic() + 20
        while self._eval(PAGE_STATE)["busy"] and time.monotonic() < deadline:
            page.wait_for_timeout(250)
        page.wait_for_timeout(SETTLE_MS)

    def _login(self, state):
        u = urlparse(self.page.url)
        if f"{u.scheme}://{u.netloc}" != self.origin:
            raise Escalate("login", "Sign-in moved to a different origin.",
                           "Verify the sign-in destination before entering credentials.")
        self.logins += 1
        if self.logins > 3:
            raise Escalate("login", "The portal keeps asking to sign in.", "Check the portal account and session settings.")
        # Only real error messages count: page copy can contain words like "incorrect"
        # (the trace's own footer says "If a form is unavailable, incorrect, ...").
        alerts = " ".join(e["text"] for e in self._eval(SCAN_ERRORS))
        if self.logins > 1 and re.search(r"(incorrect|invalid|wrong) (username|password|credentials|user ?name or password)"
                                         r"|login failed|sign[- ]in failed", alerts, re.I):
            raise Escalate("login", "The portal rejected the login credentials.",
                           "Check PORTAL_USERNAME / PORTAL_PASSWORD for this portal.")
        expired = bool(re.search(r"session (has )?expired|signed out|timed out", state["text"], re.I))
        self.log.add("login", attempt=self.logins, session_expired_notice=expired)
        controls = self._eval(DISCOVER_CONTROLS)
        pw = next((c for c in controls if c["kind"] == "password"), None)
        user = next((c for c in controls if c["kind"] == "text" and pw and c["idx"] < pw["idx"]), None)
        if not pw or not user:
            raise Escalate("login", "Could not find the username and password fields.", "Sign in manually.")
        self.page.locator(f'[data-agent-f="{user["idx"]}"]').fill(self.username)
        self.page.locator(f'[data-agent-f="{pw["idx"]}"]').fill(self.password)
        btn = next((b for b in self._eval(SCAN_PAGE)["buttons"] if LOGIN_RE.search(b["text"])), None)
        if not btn:
            raise Escalate("login", "No sign-in button found.", "Sign in manually.")
        self._click(btn, "login", "")

    def _click(self, btn, purpose, section, before_click=None):
        """Click a scanned button; if something covers it, clear popups and retry once."""
        page = self.page
        target_text, target_sid = btn["text"], btn["sid"]
        for attempt in range(2):
            interrupts.handle(page, self.log)
            if attempt:   # rescan: indices may have changed after the popup went away
                btn = next((b for b in self._eval(SCAN_PAGE)["buttons"]
                            if b["text"] == target_text and b["sid"] == target_sid), None)
                if not btn:
                    raise Escalate("portal", f"The '{target_text}' button disappeared.", "Check the page in the portal.")
            try:
                loc = page.locator(f'[data-agent-a="{btn["i"]}"]')
                if before_click:
                    # Trial only checks actionability. A timeout after the real click may
                    # happen after the server commits, so never clear its ledger or click twice.
                    loc.click(trial=True, timeout=4000)
                    before_click()
                    self.attempted = True
                loc.click(timeout=4000)
                self.log.add("click", purpose=purpose, button=target_text, section=section)
                return
            except PWTimeout:
                if before_click and self.attempted:
                    raise Escalate("submission", "The submit click timed out; the request may already exist.",
                                   "Check the portal dashboard before retrying.")
                self.log.add("click_blocked", purpose=purpose, attempt=attempt + 1)
        raise Escalate("portal", f"The '{target_text}' button stayed blocked.", "Check the page for an overlay.")

    def _quiet(self, quiet_ms=400, max_ms=8000):
        """Wait until no request has been in flight for `quiet_ms` (bounded by `max_ms`)."""
        waited, quiet = 0, 0
        while waited < max_ms:
            busy = any(r.resource_type in ("xhr", "fetch", "document") for r in list(self.inflight))
            quiet = 0 if busy else quiet + 100
            if quiet >= quiet_ms:
                return
            self.page.wait_for_timeout(100)
            waited += 100

    def _after_input(self):
        """Values often trigger lookups (ZIP -> state, BIN -> forms). Let them finish so fields
        those lookups add or pre-fill exist before the next scan."""
        self.page.wait_for_timeout(150)
        self._quiet()

    def _eval(self, script, arg=None):
        return _evaluate(self.page, script, arg)

    def _act(self, what, fn):
        try:
            return fn(4000)
        except PWTimeout:
            self.log.add("action_blocked", what=what)
            interrupts.handle(self.page, self.log)
            return fn(8000)

    # ------------------------------------------------------------------ filling
    def _fill_visible(self):
        """Fill every visible, enabled control we recognise; repeat while new ones appear."""
        done = set()
        for _ in range(60):   # one rescan per change: fields can appear after another is set
            controls = self._eval(DISCOVER_CONTROLS)
            progress = False
            unmapped_required = []
            for c in controls:
                if c["kind"] == "password":
                    continue
                field = F.classify(c["label"], c["section"])
                if field is None:
                    if c["required"] and not c["value"] and not c["disabled"]:
                        unmapped_required.append((c["label"] or c["placeholder"] or "(unlabelled)").replace("*", "").strip())
                    continue
                key = (field, c["label"], c["sid"])
                if key in done:
                    continue
                value = F.value_for(field, self.rec)
                if field in F.DATE_FIELDS:
                    order = F.date_order(c.get("formatHint", c["placeholder"]) + " " + c["label"])
                    if order:
                        self.date_orders[field] = order
                if value in (None, ""):
                    self._check_unsupplied(field, c["value"])
                    if c["required"] and not c["value"]:
                        raise Escalate(field, f"The portal requires '{c['label'].replace('*', '').strip()}' "
                                              f"but the record has no {field}.", f"Add {field} to the record.")
                    done.add(key)
                    continue
                if c["disabled"] or c.get("readonly"):
                    if not self._control_matches(c, field, value):
                        raise Escalate(field, f"The read-only '{c['label']}' does not match the supplied value.",
                                       "Verify the inherited coverage or patient details before continuing.")
                    self._observe(c, field, value)
                    done.add(key)
                    continue
                changed = self._fill_control(c, field, value)
                self._observe(c, field, value)
                done.add(key)
                if changed:
                    progress = True
                    self._after_input()   # let lookups triggered by this value finish
                    break                 # the page may have changed; rescan before the next control
            if not progress:
                if unmapped_required:
                    raise Escalate("portal", "The portal requires fields that are not in the data contract: "
                                             + ", ".join(sorted(set(unmapped_required))),
                                   "A person should supply these values or extend the field mapping.")
                return
        raise Escalate("portal", "The page kept changing while the agent filled it.",
                       "Open the portal and complete this page manually.")

    def _fill_control(self, c, field, value):
        """Make one control hold `value`. Returns True if anything was changed."""
        page = self.page
        loc = page.locator(f'[data-agent-f="{c["idx"]}"]')
        label = c["label"].replace("*", "").strip()
        shown = mask(field, value)
        if c["kind"] == "text":
            text = F.format_date(value, c.get("formatHint", c["placeholder"]), c["type"], c["label"]) if field in F.DATE_FIELDS else value
            if c["value"] == text:
                return False
            self._act(field, lambda t: loc.fill(text, timeout=t))
            if loc.input_value() != text:
                raise Escalate(field, f"The portal changed '{label}' after entry.", "Check the field format in the portal.")
            logged = shown
        elif c["kind"] == "select":
            c = self._wait_options(c)
            opt = self._choose(field, value, c["options"], label)
            if c["value"] == opt["value"]:
                return False
            self._act(field, lambda t: loc.select_option(value=opt["value"], timeout=t))
            logged = opt["text"]
        elif c["kind"] == "radio":
            opt = self._choose(field, value, c["options"], label)
            if opt.get("checked"):
                return False
            j = c["options"].index(opt)
            radio = page.locator(f'[data-agent-f="{c["idx"]}:{j}"]')
            self._act(field, lambda t: radio.check(timeout=t))
            logged = opt["text"]
        elif c["kind"] == "combobox":
            if self._control_matches(c, field, value):
                return False
            logged = self._combobox(c, field, value, typed=True)
        elif c["kind"] == "listbutton":
            if F.option_matches(field, value, c["value"]) > 0:
                return False
            logged = self._combobox(c, field, value, typed=False)
        else:
            raise Escalate(field, f"Don't know how to fill a {c['kind']} control labelled '{label}'.",
                           "Fill this field manually.")
        self.log.add("fill", field=field, label=label, kind=c["kind"],
                     value=shown if c["kind"] == "text" else logged)
        self.filled.setdefault(field, {"label": label, "value": shown if c["kind"] == "text" else logged})
        return True

    def _check_unsupplied(self, field, got):
        # A blank optional identifier does not authorize an inherited value.
        # Do not silently clear it either: ask a person to resolve the source.
        if field in {"rx_pcn", "rx_group", "group_number"} and not F.value_for(field, self.rec):
            if str(got or "").strip() not in ("", "-", "—", "Not provided"):
                raise Escalate(field, f"The portal contains {field}, but none was supplied in the record.",
                               "Confirm this identifier against the source before continuing.")

    def _observe(self, c, field, value):
        part = F.date_part(c["label"]) if field in F.DATE_FIELDS else None
        if part:
            self.date_parts.setdefault(field, set()).add(part)
            if self.date_parts[field] != {"month", "day", "year"}:
                return
        self.observed[field] = self.filled.get(field, {}).get("value", value)
        self.observed[F.canonical_field(field, self.rec)] = self.observed[field]

    def _verify_summary(self, receipt=None):
        """Verify every labelled value the portal exposes, including read-only review data."""
        checks = set()
        for label, got in (receipt if receipt is not None else self._eval(SCAN_RECEIPT))["pairs"]:
            lab = F.norm(label)
            if lab == "form" and self.form_selection:
                if F.norm(got) != F.norm(self.form_selection["chosen"]):
                    raise Escalate("form", "The portal summary shows a different form than the one selected.",
                                   "Inspect the saved request before sending it to the plan.")
                checks.add("form")
                continue
            if lab in ("patient", "name", "patient name"):
                expected = self.rec["first_name"] + " " + self.rec["last_name"]
                if F.norm(got) != F.norm(expected):
                    raise Escalate("first_name", "The portal summary shows a different patient name.",
                                   "Inspect the saved request before continuing.")
                checks.update(("first_name", "last_name"))
                continue
            if re.fullmatch(r"rxbin / rxpcn / rxgroup", lab):
                if len(got.split("/")) != 3:
                    raise Escalate("rx_bin", "The insurance summary is incomplete.", "Inspect the insurance values.")
                for field, val in zip(("rx_bin", "rx_pcn", "rx_group"), got.split("/")):
                    if val.strip() != (self.rec.get(field) or "-"):
                        raise Escalate(field, "The portal summary shows different insurance details.",
                                       "Inspect the saved request before continuing.")
                    checks.add(field)
                continue
            field = F.classify(label, "Patient")
            want = F.value_for(field, self.rec) if field else None
            self._check_unsupplied(field, got)
            if not want:
                continue
            if field in {"rx_bin", "rx_pcn", "rx_group", "group_number", "member_id", "provider_npi", "cpt_code", "icd10_code"}:
                ok = got.strip() == want
            elif field in F.DATE_FIELDS:
                order = F.date_order(label) or self.date_orders.get(field)
                parsed = F.display_date(got, order)
                ok = parsed is not None and parse_any_date(want) == parsed
            elif field == "medication_search":
                selected = self.observed.get(field, want)
                # An NDC's selected drug name is the value read from its unique lookup result.
                ok = F.norm(got) == F.norm(selected) or F.option_matches(field, selected, got) > 0
            else:
                ok = F.option_matches(field, want, got) > 0
            if not ok:
                raise Escalate(field, f"The portal summary shows a different {field}.",
                               "Inspect the saved request before continuing.")
            checks.add(field)
            checks.add(F.canonical_field(field, self.rec))
        return checks

    def _verify_complete(self):
        checks = self._verify_summary()
        missing = [f for f, v in self.rec.items() if v and f not in self.observed and f not in checks
                   and not (f == "group_number" and "rx_group" in self.observed)]
        if missing:
            raise Escalate(missing[0], "The portal has not exposed all supplied fields: " + ", ".join(missing),
                           "Verify these values in the portal before creating the request.")

    def _wait_options(self, c):
        for i in range(40):
            real = [o for o in c.get("options", []) if o["value"] and not o["disabled"]]
            if real and not c["disabled"]:
                if i:
                    self.log.add("waited_for_options", label=c["label"].replace("*", "").strip())
                return c
            self.page.wait_for_timeout(250)
            c = next(x for x in self._eval(DISCOVER_CONTROLS) if x["idx"] == c["idx"])
        raise Escalate("portal", f"The '{c['label']}' list never loaded.", "Retry later or complete manually.")

    def _choose(self, field, value, options, label):
        scored = [(F.option_matches(field, value, o["text"], o.get("value", "")), o) for o in options
                  if not o.get("disabled")]
        best = max((s for s, _ in scored), default=0)
        if best == 0:
            raise Escalate(field, f"'{value}' is not an option in the portal's '{label}' list.",
                           f"Confirm the {field}; the portal does not offer this value.")
        top = [o for s, o in scored if s == best]
        if len(top) > 1:
            raise Escalate(field, f"'{value}' matches several options in '{label}': "
                                  + ", ".join(o["text"] for o in top[:5]), "A person should pick the correct option.")
        return top[0]

    def _combobox(self, c, field, value, typed):
        """Autocomplete input (typed) or custom dropdown button (not typed). If a popup
        interrupts, the whole step is redone once; retrying only the click would hit a stale list."""
        for attempt in range(2):
            try:
                return self._combobox_once(c, field, value, typed)
            except PWTimeout:
                if attempt:
                    raise
                self.log.add("action_blocked", what=field)
                interrupts.handle(self.page, self.log)

    def _combobox_once(self, c, field, value, typed):
        page = self.page
        loc = page.locator(f'[data-agent-f="{c["idx"]}"]')
        label = c["label"].replace("*", "").strip()
        if typed:
            loc.fill("", timeout=4000)
            loc.fill(value, timeout=4000)
        else:
            loc.click(timeout=4000)
            page.wait_for_timeout(250)
            if self._eval(LISTBUTTON_SEARCH, str(c["idx"])):
                page.locator('[data-agent-q="1"]').fill(F.search_text(field, value), timeout=4000)
        listing = None
        for _ in range(40):                                 # up to 10s (slow searches)
            page.wait_for_timeout(250)
            listing = self._eval(LISTBOX_OPTIONS, str(c["idx"]))
            if listing["options"] or listing["noResults"]:
                break
        opts = listing["options"] if listing else []
        by_id = field == "medication_search" and re.fullmatch(r"\d{10,11}", value.replace("-", ""))
        if by_id:
            # An NDC is a unique id and the portal shows the drug name, not the NDC: take the
            # results as they are (0 -> not found, 1 -> use it, several -> ambiguous, escalate).
            matches = opts
        else:
            scored = [(F.option_matches(field, value, o["text"]), o) for o in opts]
            best = max((s for s, _ in scored), default=0)
            matches = [o for s, o in scored if s == best and s > 0]
        if not matches:
            raise Escalate(field, f"The portal has no '{label}' entry for '{value}'."
                           + (f" It offered: {', '.join(o['text'] for o in opts[:5])}" if opts else ""),
                           f"Confirm the {field}; the portal's list does not contain it.")
        if len(matches) > 1:
            raise Escalate(field, f"'{value}' matches several entries in '{label}': "
                                  + "; ".join(m["text"] for m in matches[:6]),
                           "A person should say which one is meant (e.g. add the strength to the medication).")
        page.locator(f'[data-agent-o="{matches[0]["j"]}"]').click(timeout=4000)
        page.wait_for_timeout(250)
        if typed:
            current = self._eval(READ_COMBO_STATE, str(c["idx"]))
            state = current.get("committed", {}) if current else {}
            if state.get("hasBacking") and not state.get("values"):
                commit_with_enter(page, loc)
                self.log.add("keyboard_commit", field=field)
                current = self._eval(READ_COMBO_STATE, str(c["idx"]))
            ok = current and selection_matches(current, field, value, matches[0]["text"] if by_id else None)
        else:
            ok = F.option_matches(field, value, loc.inner_text()) > 0
        if not ok:
            raise Escalate(field, f"The selected '{label}' entry did not stick.", "Fill this field manually.")
        return matches[0]["text"]

    def _control_matches(self, c, field, value):
        if c["kind"] == "text":
            return c["value"] == (F.format_date(value, c.get("formatHint", c["placeholder"]), c["type"], c["label"])
                                  if field in F.DATE_FIELDS else value)
        if c["kind"] == "select":
            return any(o["value"] == c["value"] and F.option_matches(field, value, o["text"], o["value"]) > 0
                       for o in c["options"])
        if c["kind"] == "radio":
            return any(o.get("checked") and F.option_matches(field, value, o["text"], o["value"]) > 0
                       for o in c["options"])
        if c["kind"] == "combobox":
            by_id = field == "medication_search" and re.fullmatch(r"\d{10,11}", value.replace("-", ""))
            selected = self.observed.get(field) if by_id else None
            return selection_matches(c, field, value, selected)
        return F.option_matches(field, value, c["value"]) > 0

    def _verify_still_set(self):
        """Before moving on: every control we filled must still hold our value."""
        for c in self._eval(DISCOVER_CONTROLS):
            field = F.classify(c["label"], c["section"])
            self._check_unsupplied(field, c["value"])
            if not field or field not in self.observed:
                continue
            value = F.value_for(field, self.rec)
            if not self._control_matches(c, field, value):
                raise Escalate(field, f"'{c['label'].replace('*', '').strip()}' no longer holds the value the agent "
                                      "entered (the portal changed or cleared it).",
                               "Check this field in the portal before continuing.")

    # ------------------------------------------------------------------ outcomes
    def _field_errors(self):
        out = []
        for e in self._eval(SCAN_ERRORS):
            out.append((F.classify(e["label"], "") if e["label"] else None, e["label"], e["text"]))
        return out

    def _check_errors_after(self):
        self._settle()
        interrupts.handle(self.page, self.log)
        self._check_dialogs()
        if self._eval(PAGE_STATE)["password"]:
            return  # The main loop handles a bounded same-origin sign-in.
        all_errors = self._field_errors()
        errs = [e for e in all_errors if e[0] or e[1]]
        if errs:
            field, label, text = errs[0]
            self.log.add("portal_rejected_field", field=field or label)
            raise Escalate(field or label, f"Portal rejected '{label.replace('*', '').strip()}': {text}",
                           "Check this value against the source documents; the agent will not change it.")
        general = " ".join(e[2] for e in all_errors)
        if not general:
            return
        expired_token = re.search(r"security token expired|csrf.*expired|nonce.*expired", general, re.I)
        if expired_token and not self.attempted and self.security_refreshes == 0:
            u = urlparse(self.page.url)
            if f"{u.scheme}://{u.netloc}" == self.origin:
                self.security_refreshes += 1
                self.log.add("refresh_form", reason="expired security token", attempt=1)
                # Navigate with GET; do not replay the rejected POST document.
                self.page.goto(self.page.url)
                self._settle()
                return
        raise Escalate("portal", "The portal blocked this step: " + general[:200],
                       "Resolve the portal message before continuing; no values were changed to bypass it.")

    def _wait_for_stable_forms(self):
        """The form list reloads as insurance fields are typed: wait until it stops changing."""
        last, same = None, 0
        for _ in range(40):
            scan = self._eval(SCAN_PAGE)
            busy = any(s.get("busy") for s in scan["sections"].values())
            sig = tuple(b["text"] + "|" + b["sid"] for b in scan["buttons"])
            same = same + 1 if (sig == last and not busy) else 0
            if same >= 2:
                return scan
            last = sig
            self.page.wait_for_timeout(400)
        raise Escalate("form", "The form list kept changing.", "Choose the form manually.")

    def _form_choices(self, scan):
        starts = [b for b in scan["buttons"] if START_RE.search(b["text"]) and not b["disabled"]]
        return [{"title": scan["sections"].get(b["sid"], {}).get("title", "") or b["text"], "button": b}
                for b in starts]

    def _start(self, kind):
        page = self.page
        self._verify_still_set()
        self._verify_complete()
        scan = self._wait_for_stable_forms()
        if kind == "start":
            more = next((b for b in scan["buttons"] if MORE_RE.search(b["text"]) and not b["disabled"]), None)
            if more:                                   # list every option so the choice can be reported
                self._click(more, "show_all_forms", scan["sections"].get(more["sid"], {}).get("title", ""))
                self._settle()
                scan = self._wait_for_stable_forms()
            choices = self._form_choices(scan)
            if not choices:
                raise Escalate("form", "The form list disappeared.", "Choose the form manually.")
            api = self._api_form_titles()
            dom = [c["title"] for c in choices]
            if api is not None and [t.lower() for t in api] != [t.lower() for t in dom]:
                # two sources for the same list: what the page shows and what the portal sent it
                raise Escalate("form", f"The page lists {len(dom)} forms but the portal's data has {len(api)} "
                                       "in a different order or with different titles.",
                               "Choose the form manually; the agent will not guess which list is right.")
            # Skip forms restricted to another state ("Texas Medicaid ..." for an Oklahoma plan).
            st = self.rec.get("insurance_state")
            other = [c for c in choices if st and F.states_named(c["title"]) and st not in F.states_named(c["title"])]
            fitting = [c for c in choices if c not in other]
            if not fitting:
                raise Escalate("form", f"Every form offered is for a state other than {st}.",
                               "Check the insurance state, or choose the form manually.")
            chosen = fitting[0]
            self.form_selection = {"policy": self.form_policy, "chosen": chosen["title"],
                                   "position": choices.index(chosen) + 1, "candidates": len(choices),
                                   "alternatives": [c["title"] for c in fitting[1:11]],
                                   "skipped_other_state": [c["title"] for c in other][:10],
                                   "checked_against": "page and portal data" if api is not None else "page"}
            self.log.add("forms_found", count=len(choices), chosen=chosen["title"], skipped_other_state=len(other),
                         api_checked=api is not None)
            choices = fitting
            if self.form_policy == "clarify" and len(choices) > 1:
                raise Escalate("form", f"The portal offered {len(choices)} forms: "
                                       + "; ".join(c["title"] for c in choices[:5]),
                               "A person should pick the form (run with --form-policy first to take the top one).")
            target_title = choices[0]["title"]
        else:
            target_title = None

        def mark():
            if not self.claimed:
                if not self.ledger.claim(self.key):
                    raise Escalate("submission", "Another run has claimed this request.",
                                   "Check the other run's outcome before retrying.")
                self.claimed = True
                self.log.add("ledger", state="submitting")
            self.write_responses = []

        for attempt in range(START_RETRIES + 1):
            scan = self._eval(SCAN_PAGE)
            if kind == "start":
                ch = next((c for c in self._form_choices(scan) if c["title"] == target_title), None)
                if not ch:
                    raise Escalate("form", f"Form '{target_title}' is no longer offered.", "Choose the form manually.")
                btn = ch["button"]
            else:
                btn = next(b for b in scan["buttons"] if SUBMIT_RE.search(b["text"]) and not b["disabled"])
            self._click(btn, "start_request" if kind == "start" else "submit", target_title or "",
                        before_click=mark)
            self._settle()
            if interrupts.handle(page, self.log):
                self._settle()                       # a dismissed dialog (e.g. expired existing PA) may navigate
            self._check_dialogs()
            state = self._eval(PAGE_STATE)
            if not self._result_from_page_peek(state) and LOAD_ERROR_RE.search(state["text"]):
                # Reload only a known GET document, never a POST that could be replayed.
                if self.reloaded or self.document_method != "GET":
                    raise Escalate("submission", "Request page cannot be safely reloaded again.",
                                   "Check the portal dashboard before retrying.")
                self.reloaded = True
                self.log.add("reload", reason="page load error after start")
                page.reload()
                self._settle()
                state = self._eval(PAGE_STATE)
            res = self._result_from_page(state)
            if res:
                return res
            res = self._download_receipt()
            if res:
                return res
            errs = self._field_errors()
            field_errs = [e for e in errs if e[0] or e[1]]
            general = " ".join(e[2] for e in errs if not (e[0] or e[1]))
            if self._reconcile_revision(btn, general):
                continue
            if field_errs:
                field, label, text = field_errs[0]
                raise Escalate(field or label, f"Portal rejected '{label}' when starting the request: {text}",
                               "Resolve this value with the patient or plan; the agent will not change it.")
            if general and RETRYABLE_RE.search(general) and not UNSAFE_RETRY_RE.search(general):
                if attempt < START_RETRIES:
                    self.log.add("retry_start", attempt=attempt + 1, reason="portal says request was not created")
                    page.wait_for_timeout(1000 * (attempt + 1))
                    continue
                self.ledger.clear(self.key)
                self.claimed = False
                raise Escalate("portal", f"Portal kept refusing to create the request: {general[:160]}",
                               "Nothing was created. Try again later or start it manually.")
            if kind == "start" and self._review_page():
                # Start opened a review / confirmation step, so nothing exists yet. Keep the ledger
                # marked (a crash from here on must not lead to a second request) and carry on.
                self.log.add("review_page")
                return None
            raise Escalate("submission", "Clicked Start but could not confirm whether a request was created.",
                           "Check the portal dashboard for this request before retrying.")
        raise Escalate("submission", "Start retries exhausted.", "Check the portal dashboard.")

    def _reconcile_revision(self, submitted_button, message):
        """One rejected version may be retried after a fresh, complete comparison.

        HTTP 409/412 must belong to the exact final form POST. The response must
        describe a draft/version conflict, expose a changed version token and
        offer a review of every supplied field. Unknown outcomes keep the claim.
        """
        if self.revision_refreshes or len(self.write_responses) != 1:
            return False
        response = self.write_responses[0]
        target = submitted_button.get("formAction")
        if (response["status"] not in {409, 412} or response["method"] != "POST" or
                submitted_button.get("formMethod") != "POST" or response["url"] != target or
                not submitted_button.get("versions") or not self._review_page()):
            return False
        if (not re.search(r"draft.*changed|revision.*(?:conflict|changed)|version.*(?:conflict|changed)", message, re.I)
                or not re.search(r"reload|refresh", message, re.I) or UNSAFE_RETRY_RE.search(message)):
            return False
        u = urlparse(target)
        if f"{u.scheme}://{u.netloc}" != self.origin or self.page.url != target:
            return False
        self.revision_refreshes += 1
        self.log.add("refresh_review", reason="rejected draft version", attempt=1)
        self.page.goto(target)  # A fresh GET, never browser POST resubmission.
        self._settle()
        interrupts.handle(self.page, self.log)
        self._check_dialogs()
        receipt = self._eval(SCAN_RECEIPT)
        if self._eval(PAGE_STATE)["password"] or self._references(receipt):
            raise Escalate("submission", "The refreshed review did not establish a new safe submission.",
                           "Check the request status manually.")
        checks = self._verify_summary(receipt)
        missing = sorted(f for f, v in self.rec.items() if v and f not in checks)
        if missing:
            raise Escalate(missing[0], "The refreshed review does not show every supplied field.",
                           "Compare the entire new draft before confirming it.")
        buttons = [b for b in self._eval(SCAN_PAGE)["buttons"] if SUBMIT_RE.search(b["text"]) and not b["disabled"]]
        if (len(buttons) != 1 or buttons[0].get("formAction") != target or
                not buttons[0].get("versions") or buttons[0]["versions"] == submitted_button["versions"]):
            raise Escalate("submission", "The refreshed draft has no unambiguous new version to confirm.",
                           "Resolve the version conflict manually.")
        self.log.add("review_compared", fields=sorted(checks))
        return True

    def _download_receipt(self):
        receipt = self._eval(SCAN_RECEIPT)
        links = receipt["downloads"]
        if not links or not self.attempted:
            return None
        if not re.search(r"(?:receipt|confirmation) (?:available|ready)", receipt["headings"], re.I):
            return None
        if len(links) != 1:
            raise Escalate("submission", "More than one receipt document is available.",
                           "Identify the document belonging to this request.")
        target = urlparse(links[0]["url"])
        if f"{target.scheme}://{target.netloc}" != self.origin:
            raise Escalate("submission", "The receipt download points to another origin.",
                           "Verify the document source manually.")
        def guard(route):
            u = urlparse(route.request.url)
            if f"{u.scheme}://{u.netloc}" != self.origin or route.request.method not in {"GET", "HEAD"}:
                route.abort()
            else:
                route.continue_()
        self.page.route("**/*", guard)
        try:
            with self.page.expect_download(timeout=8000) as event:
                self.page.locator(f'[data-agent-receipt="{links[0]["i"]}"]').click(timeout=4000)
        finally:
            self.page.unroute("**/*", guard)
        download = event.value
        if download.failure():
            raise Escalate("submission", "The receipt download failed.", "Check the request in the portal.")
        if Path(download.suggested_filename).suffix.lower() not in {".txt", ".json"}:
            raise Escalate("submission", "The receipt document format is not supported.",
                           "Verify the downloaded receipt manually.")
        path = Path(download.path())
        if path.stat().st_size > 1024 * 1024:
            raise Escalate("submission", "The receipt exceeds the document parsing limit.",
                           "Verify the document manually.")
        payload = path.read_bytes()
        try:
            document = parse_document(payload)
        except (ValueError, UnicodeError):
            raise Escalate("submission", "The downloaded receipt could not be read as labelled data.",
                           "Verify the document manually.")
        statuses = [F.norm(value) for label, value in document["pairs"]
                    if F.norm(label) in {"status", "request status", "submission status"}]
        if any(s not in {"success", "received", "submitted", "created", "submitted successfully"} for s in statuses):
            raise Escalate("submission", "The document does not confirm a completed request.",
                           "Check the request status manually.")
        ids = self._references(document)
        if len(ids) != 1:
            raise Escalate("submission", "The downloaded receipt has no single request reference.",
                           "Verify the document manually.")
        conf = next(iter(ids))
        checks = self._verify_summary(document)
        missing = sorted(f for f, value in self.rec.items() if value and f not in checks)
        if missing:
            raise Escalate(missing[0], "The downloaded receipt does not verify every supplied field.",
                           "Check the saved request before marking it successful.")
        self.receipt_evidence = {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload), "format": "text"}
        self.log.add("download_verified", fields=sorted(checks))
        result = _result("SUCCESS", "Request created; the downloaded receipt verifies its reference and supplied values.",
                         conf, self.filled, extra=self._extra())
        self._finish(result)
        return result

    def _review_page(self):
        """After Start: a page that asks for a final Submit / Continue rather than showing an outcome."""
        scan = self._eval(SCAN_PAGE)
        return any((SUBMIT_RE.search(b["text"]) or CONTINUE_RE.search(b["text"])) and not b["disabled"]
                   for b in scan["buttons"]) and not any(START_RE.search(b["text"]) for b in scan["buttons"])

    @staticmethod
    def _result_from_page_peek(state):
        return bool(KEY_RE.search(state["text"]) or SUCCESS_RE.search(state["text"]))

    @staticmethod
    def _references(receipt):
        ids = {m.group(1).upper() for m in CONF_RE.finditer(receipt["headings"])}
        for label, value in receipt["pairs"]:
            if re.fullmatch(r"(?:reference|confirmation|request|case|tracking) (?:number|id|key)", F.norm(label)):
                if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{5,}", value.strip()):
                    ids.add(value.strip().upper())
        return ids

    def _result_from_page(self, state):
        text = state["text"]
        receipt = self._eval(SCAN_RECEIPT)
        headings = receipt["headings"]
        ids = self._references(receipt)
        conf = next(iter(ids)) if len(ids) == 1 else None
        keyed = bool(KEY_RE.search(headings))
        failed = bool(FAILURE_RE.search(headings))
        success = keyed or bool(SUCCESS_RE.search(headings))
        if (failed or success) and not self.attempted:
            raise Escalate("submission", "An existing outcome page appeared before this run submitted anything.",
                           "Verify whose request this is before continuing.")
        if failed and success:
            raise Escalate("submission", "The portal shows conflicting success and failure messages.",
                           "Check the portal dashboard before retrying.")
        if failed and not keyed and self.attempted:
            # failure first: failure pages often say things like "no request was created"
            reason = re.search(r"reason\s*[:\-]\s*(.+)", text, re.I)
            why = (reason.group(1) if reason else text[:200]).strip().splitlines()[0]
            res = _result("FAILED", why, None, self.filled, extra=self._extra())
            self._finish(res)
            return res
        if success:
            if not conf:
                raise Escalate("submission", "Portal reported success but no single unambiguous request key was found.",
                               "Find the request in the portal dashboard and record its key.")
            self._verify_request_page(text, conf)
            res = _result("SUCCESS", "Prior authorization request created; the portal returned its reference number.",
                          conf, self.filled, extra=self._extra())
            self._finish(res)
            return res
        return None

    def _verify_request_page(self, text, conf):
        """The created request must show the patient and insurance we entered."""
        low = text.lower()
        try:
            checks = self._verify_summary()
            if not {"first_name", "last_name"}.issubset(checks):
                # The trace identifies the patient in its request heading.
                heading = self._eval(SCAN_RECEIPT)["headings"]
                name = self.rec["first_name"] + " " + self.rec["last_name"]
                if not re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", heading, re.I):
                    raise Escalate("first_name", "The receipt does not identify the expected patient.",
                                   "Inspect the saved request.")
                checks.update(("first_name", "last_name"))
            if "medication_search" in self.rec and "medication_search" not in checks:
                raise Escalate("medication_search", "The receipt does not show the saved medication.",
                               "Inspect the saved request.")
        except Escalate as e:
            e.confirmation_id = conf
            self._finish(_result("ESCALATED", e.problem, conf, self.filled,
                                 escalation=e.to_dict(), extra=self._extra()))
            raise
        sel = self.form_selection
        if sel and sel["chosen"].lower() not in low and any(a.lower() in low for a in sel["alternatives"]):
            # CMM has been seen submitting a different form than the one clicked (duplicate-PA modal)
            self._finish(_result("ESCALATED", "Request created, but for a different form than the one chosen.",
                                 conf, self.filled, extra=self._extra()))
            e = Escalate("form", f"Request {conf} was created on another form, not '{sel['chosen']}'.",
                         f"Open request {conf} and check which form it uses before sending it to the plan.")
            e.confirmation_id = conf
            raise e
        self.log.add("request_verified", fields=sorted(checks | ({"form"} if sel else set())))

    def _finish(self, res):
        self.ledger.mark_done(self.key, res)
        self.log.add("outcome", status=res["status"], confirmation_id=res["confirmation_id"])
