"""Verify committed autocomplete values and select with a guarded Enter key."""
import re

from . import fields as F
from .errors import Escalate


def selection_matches(control, field, value, selected_text=None):
    state = control.get("committed") or {}
    backing = state.get("values", [])
    expected = selected_text or value

    def matches(text):
        if field in {"cpt_code", "icd10_code", "place_of_service"}:
            return bool(re.match(re.escape(value) + r"(?:$|\s|[-–:])", text.strip()))
        return F.option_matches(field, expected, text) > 0

    if state.get("hasBacking"):
        if not backing or not all(matches(v) or v == value for v in backing):
            return False
        # More than one committed code is not the single procedure in the input.
        if len(set(backing)) != 1:
            return False
    if matches(control.get("value", "")):
        return True
    # An empty search box is valid only with both a matching backing value and
    # the selected item visibly attached to this particular control.
    return bool(backing and any(matches(t) for t in state.get("labels", [])))


def commit_with_enter(page, locator):
    """Allow the widget's key handler, while blocking form submission and writes.

    A bare Enter can submit the entire page. A keyboard selection must finish
    before the agent's separately guarded final submission.
    """
    blocked = []

    def guard(route):
        if route.request.method not in {"GET", "HEAD", "OPTIONS"}:
            blocked.append(route.request.method)
            route.abort()
        else:
            route.continue_()

    page.route("**/*", guard)
    page.evaluate("""() => {
      window.__agentSubmitGuard = e => {e.preventDefault();e.stopImmediatePropagation();};
      document.addEventListener('submit', window.__agentSubmitGuard, true);
    }""")
    try:
        locator.press("Enter", timeout=4000)
        page.wait_for_timeout(250)
    finally:
        page.evaluate("""() => {
          document.removeEventListener('submit', window.__agentSubmitGuard, true);
          delete window.__agentSubmitGuard;
        }""")
        page.unroute("**/*", guard)
    if blocked:
        raise Escalate("portal", "The keyboard selection attempted a write; it was blocked.",
                       "Select the value manually before creating the request.")
