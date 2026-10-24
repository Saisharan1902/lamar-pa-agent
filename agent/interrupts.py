"""Popups and overlays.

Policy:
  * Known-benign interruptions (cookies, maintenance notices, session keep-alive,
    surveys, chat widgets) are dismissed with an allow-listed button.
  * Known-blocking business dialogs (duplicate patient, etc.) escalate.
  * Any other modal dialog escalates: we do not click buttons we don't understand.
  * Unknown non-modal fixed elements (headers, sidebars) are ignored.
"""
import re

from .dom import SCAN_INTERRUPTIONS, evaluate
from .errors import Escalate

# (category, text pattern, buttons to press in order of preference)
BENIGN = [
    ("session_keepalive", r"session (is about to|will) expire|about to be (signed|logged) out|are you still there|inactiv",
     ["stay signed in", "stay logged in", "keep me signed in", "continue session", "extend session",
      "i'm still here", "continue working", "yes"]),
    ("cookie_consent", r"cookie|terms of use|privacy preferences",
     ["accept", "accept all", "i agree", "agree", "got it", "ok", "close"]),
    ("maintenance_notice", r"maintenance|scheduled downtime|service notice",
     ["acknowledge", "got it", "ok", "close", "dismiss", "continue"]),
    ("survey", r"survey|feedback|how are we doing|rate your|how likely",
     ["no thanks", "no, thanks", "not now", "maybe later", "skip", "close", "dismiss"]),
    ("announcement", r"what's new|announcement|new feature|important message",
     ["got it", "close message", "close", "dismiss", "ok", "\u00d7"]),
    ("chat_widget", r"chat with (support|us)|live chat|faqs|need help\?",
     ["close chat", "minimize chat", "minimize", "close", "\u00d7", "x"]),
]
BLOCKING = [
    ("duplicate_patient", r"duplicate|already (has|exists?)|may already exist|existing (open )?request|existing patient",
     "patient", "The portal reports a possible duplicate patient or an existing open request.",
     "Check the existing request in the portal. Only create a new one if a person confirms it is not a duplicate."),
]
NEVER_CLICK = re.compile(r"sign ?out|log ?out|delete|discard|cancel request|submit|take survey|create .* anyway|manage", re.I)


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def classify(c):
    """Return (category, button_index) / raises Escalate / returns None to ignore."""
    blob = _norm(" ".join([c["title"], c["label"], c["text"]]))
    if c["kind"] == "dialog" and EXISTING_PA_RE.search(blob):
        return _existing_pa(c, blob)
    for cat, pat, field, problem, action in BLOCKING:
        if re.search(pat, blob) and c["kind"] == "dialog":
            raise Escalate(field, f"{problem} Dialog: '{c['title'] or c['text'][:80]}'", action)
    for cat, pat, prefs in BENIGN:
        if re.search(pat, blob):
            for want in prefs:
                for b in c["buttons"]:
                    name = _norm(b["text"]) or _norm(b["aria"])
                    if NEVER_CLICK.search(name):
                        continue
                    if name == want or _norm(b["aria"]) == want:
                        return cat, b["j"]
            return cat, None
    if c["kind"] == "dialog":
        raise Escalate("portal", f"Unexpected dialog: '{c['title'] or c['text'][:80]}'",
                       "A person should read this dialog in the portal and decide how to proceed.")
    return None


EXISTING_PA_RE = re.compile(r"existing (pa|prior auth(orization)?)\b", re.I)


def _existing_pa(c, blob):
    """CMM's existing-PA modal. An expired PA cannot be used, so a new one is fine; any other status escalates."""
    status = re.search(r"status:\s*([a-z][a-z ]*?)(?=\s+(?:created|key|cancel)\b|[.;,]|$)", blob)
    status = status.group(1).strip() if status else "unknown"
    key = re.search(r"key:\s*([a-z0-9]{6,})", blob)
    if status == "expired":
        for b in c["buttons"]:
            if re.fullmatch(r"continue with new (pa|prior auth(orization)?)", _norm(b["text"])):
                return "existing_pa_expired", b["j"]
    e = Escalate("patient", f"The portal shows an existing PA for this patient and medication "
                            f"(key {key.group(1).upper() if key else 'unknown'}, status: {status}).",
                 "Check the existing request. Create a new one only if a person confirms it is needed.")
    e.nothing_created = True
    raise e


def handle(page, log, max_rounds=6):
    """Dismiss benign interruptions until none remain. Returns number dismissed."""
    dismissed = 0
    for _ in range(max_rounds):
        cands = evaluate(page, SCAN_INTERRUPTIONS)
        acted = False
        for c in cands:
            res = classify(c)
            if res is None:
                continue
            cat, j = res
            if j is None:
                page.keyboard.press("Escape")
                log.add("interruption", category=cat, how="escape")
            else:
                btn = next(b for b in c["buttons"] if b["j"] == j)
                page.locator(f'[data-agent-b="{c["i"]}:{j}"]').click(timeout=3000)
                log.add("interruption", category=cat, how="click", button=btn["text"] or btn["aria"])
            page.wait_for_timeout(300)
            dismissed += 1
            acted = True
            break
        if not acted:
            return dismissed
    remaining = [c for c in evaluate(page, SCAN_INTERRUPTIONS) if classify(c) is not None]
    if remaining:
        raise Escalate("portal", f"Could not dismiss '{remaining[0]['title'] or remaining[0]['text'][:60]}'",
                       "A person should clear the popup in the portal.")
    return dismissed
