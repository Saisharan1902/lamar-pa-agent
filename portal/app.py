"""Synthetic Portal A, rebuilt from the Playwright trace (CoverMyMeds-style pharmacy PA intake).

Flow, as recorded in the trace:
  Start a New Request (single page, cards revealed one after another)
    Medication (autocomplete) -> Primary Diagnosis (skippable) -> Patient Information
    -> Patient Insurance (state, RxBIN, RxPCN, RxGroup; forms load live)
    -> Select a Form -> Start Request -> request page "First Last (Key: XXXXXXXX)"
The trace stops on the request page without clicking "Send to Plan", so creating
the request is the end of this flow: the request Key is the confirmation number.

Run:  python portal/app.py --port 5055
Scenarios: http://localhost:5055/?scenarios=flaky_start,survey_overlay   ('none' = all off)
"""
import argparse
import hashlib
import json
import os
import secrets
import sys
import time
from datetime import date
from pathlib import Path

from flask import (Flask, abort, g, jsonify, redirect, render_template, request,
                   session, url_for)

sys.path.insert(0, str(Path(__file__).parent))
from reference_data import DRUGS, FORMS, STATES, state_for_zip  # noqa: E402
from validation import validate_insurance, validate_patient  # noqa: E402

HERE = Path(__file__).parent
CONFIG = json.loads((HERE / "scenarios.json").read_text())
ALL_SCENARIOS = set(CONFIG["popups"]) | set(CONFIG["edge_cases"])
USERNAME = os.environ.get("PORTAL_USER", "demo")
PASSWORD = os.environ.get("PORTAL_PASS", "demo123")
DIAGNOSES = [("M05.79", "Rheumatoid arthritis with rheumatoid factor of multiple sites"),
             ("M06.9", "Rheumatoid arthritis, unspecified"), ("L40.50", "Arthropathic psoriasis, unspecified"),
             ("M45.9", "Ankylosing spondylitis of unspecified sites in spine"), ("K50.90", "Crohn's disease, unspecified")]

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.environ.get("PORTAL_SECRET", "synthetic-portal-dev-secret")

REQUESTS = {}        # key -> request record
FAILURES = {}        # ref -> failure record
BY_TOKEN = {}        # page token -> key/ref (server-side de-duplication of double clicks)
PENDING = {}         # page token -> request waiting on the review page (scenario review_step)
SUBMISSION_LOG = []  # every outcome, for tests


def today():
    t = os.environ.get("PORTAL_TODAY")
    return date.fromisoformat(t) if t else date.today()


@app.before_request
def load_scenarios():
    if "scenarios" in request.args:
        raw = request.args["scenarios"].strip()
        chosen = [] if raw in ("", "none") else [s.strip() for s in raw.split(",")]
        bad = [s for s in chosen if s not in ALL_SCENARIOS]
        if bad:
            abort(400, f"Unknown scenario(s): {', '.join(bad)}")
        session.clear()
        session["scn"] = chosen
    elif "scn" not in session:
        session["scn"] = list(CONFIG["defaults"])
    if "test_case" in request.args:
        session["test_case"] = request.args["test_case"]
    g.scn = set(session["scn"])
    g.idtok = secrets.token_hex(3) if "random_ids" in g.scn else None


def on(name):
    return name in g.scn


def fired(name):
    return name in session.get("fired", [])


def mark_fired(name):
    session["fired"] = session.get("fired", []) + [name]


@app.context_processor
def helpers():
    def fid(name):
        return f"{name}-{g.idtok}" if g.idtok else name
    return {"fid": fid, "on": on}


def logged_in():
    return bool(session.get("user"))


def api_auth():
    if not logged_in():
        return jsonify({"expired": True, "redirect": url_for("login", expired=1)}), 401
    return None


# ------------------------------------------------------------------ pages
@app.route("/")
def index():
    return redirect(url_for("formpick" if logged_in() else "login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("username") == USERNAME and request.form.get("password") == PASSWORD:
            session["user"] = USERNAME
            return redirect(url_for("formpick"))
        error = "Incorrect username or password."
    return render_template("login.html", error=error,
                           expired=request.args.get("expired") == "1"), (401 if error else 200)


@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login", expired=1 if request.args.get("reason") else None))


@app.route("/formpick")
def formpick():
    if not logged_in():
        return redirect(url_for("login", expired=1))
    cfg = {"scn": sorted(g.scn), "token": secrets.token_hex(8)}
    return render_template("formpick.html", states=STATES, cfg=json.dumps(cfg))


@app.route("/v2/requests/<key>")
def request_page(key):
    if not logged_in():
        return redirect(url_for("login", expired=1))
    r = REQUESTS.get(key) or abort(404)
    if on("request_page_error") and not fired("request_page_error"):
        mark_fired("request_page_error")           # transient: the next load works
        return render_template("request_error.html", key=key), 500
    return render_template("request.html", key=key, r=r, states=STATES)


@app.route("/formpick/failed/<ref>")
def failed_page(ref):
    if not logged_in():
        return redirect(url_for("login", expired=1))
    f = FAILURES.get(ref) or abort(404)
    return render_template("failed.html", ref=ref, f=f)


# ------------------------------------------------------------------ APIs used by the page
@app.route("/api/drugs")
def api_drugs():
    time.sleep(2.5 if on("slow_drug_search") else 0.3)
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])
    if q.isdigit():
        hits = [d for d in DRUGS if d[2] == q]
    else:
        hits = [d for d in DRUGS if q.lower() in d[1].lower()]
    return jsonify([{"id": i, "name": n} for i, n, _ in hits])


@app.route("/api/diagnoses")
def api_diagnoses():
    q = request.args.get("q", "").strip().lower()
    time.sleep(0.2)
    return jsonify([{"code": c, "name": f"{c} - {t}"} for c, t in DIAGNOSES
                    if len(q) >= 2 and (c.lower().startswith(q) or q in t.lower())])


@app.route("/api/zip-state")
def api_zip_state():
    time.sleep(0.2)
    return jsonify({"state": state_for_zip(request.args.get("zip", "").strip())})


@app.route("/api/patient", methods=["POST"])
def api_patient():
    if (r := api_auth()):
        return r
    body = request.get_json(force=True)
    if on("session_expiry") and not fired("session_expiry"):
        mark_fired("session_expiry")
        session.pop("user", None)
        return jsonify({"expired": True, "redirect": url_for("login", expired=1)}), 401
    errors = validate_patient(body, today())
    if errors:
        return jsonify({"errors": errors}), 400
    if on("duplicate_patient") and not body.get("confirm_new"):
        return jsonify({"duplicate": True})
    return jsonify({"ok": True})


def bin_key(b):
    return (b or "").lstrip("0") or "0"


@app.route("/api/forms")
def api_forms():
    if (r := api_auth()):
        return r
    a = request.args
    errors = validate_insurance(a)
    if errors:
        return jsonify({"errors": errors}), 400
    time.sleep(3.0 if on("slow_forms") else 0.4)
    if on("no_forms"):
        return jsonify({"forms": [], "message": "No forms were found for this insurance. Try searching by plan name."})
    pcn = (a.get("pcn") or "").strip().upper()
    found = []
    for f in FORMS:
        bins = [bin_key(b) for b in f["bin"]]
        if bins and bin_key(a.get("bin")) not in bins:
            continue
        if not bins and a.get("drug_id") != "180335":      # drug-specific form in the trace
            continue
        # Prefix match: the trace's search for PCN "NVT" also returned form 68117 (PCNs EGWP, NVTD),
        # 9 forms in all ("Show 8 More").
        if pcn and f["pcn"] and not any(p.upper().startswith(pcn) for p in f["pcn"]):
            continue
        found.append({k: f[k] for k in ("id", "title", "directions", "benefit", "is_epa")})
    if on("other_state_forms_first"):                      # state-specific forms ranked above the rest
        found.sort(key=lambda f: not any(n in f["title"] for n in ("Colorado", "Texas")))
    return jsonify({"forms": found, "message": None if found else "No forms were found for this insurance."})


@app.route("/api/requests", methods=["POST"])
def api_requests():
    if (r := api_auth()):
        return r
    b = request.get_json(force=True)
    token = b.get("token", "")
    if token in BY_TOKEN:                          # double click / resend: same outcome
        return jsonify(BY_TOKEN[token])
    p, ins = b.get("patient") or {}, b.get("insurance") or {}
    errors = validate_patient(p, today())
    errors.update(validate_insurance({"bin": ins.get("rx_bin"), "pcn": ins.get("rx_pcn"),
                                      "group_id": ins.get("rx_group"), "state": ins.get("insurance_state")}))
    form = next((f for f in FORMS if f["id"] == b.get("form_id")), None)
    drug = next((d for d in DRUGS if d[0] == b.get("drug_id")), None)
    if not form or not drug:
        errors["form"] = "Select a medication and a form."
    if errors:
        return jsonify({"errors": errors, "message": "Fix the highlighted fields and try again."}), 400
    acks = set(b.get("acks") or [])
    if on("therapeutic_alternatives") and "alternatives" not in acks:
        return jsonify({"alternatives": [{"name": "Inflectra 100MG vial", "coverage": "Preferred, no PA required"},
                                         {"name": "Renflexis 100MG vial", "coverage": "Preferred, no PA required"}]})
    if (on("existing_pa") or on("existing_pa_expired")) and "existing" not in acks:
        return jsonify({"existing": {"key": "B7QK2M4X", "created": "08/14/2026",
                                     "status": "Expired" if on("existing_pa_expired") else "Sent to Plan"}})
    if on("review_step"):                          # nothing is created until the review page is submitted
        PENDING[token] = {"body": b, "form": form, "drug": drug}
        return jsonify({"url": url_for("review_page", token=token)})
    out, status = create_request(b, form, drug)
    return jsonify(out), status


def create_request(b, form, drug):
    """Create the request (or the failure record). Returns (response dict, HTTP status)."""
    token = b.get("token", "")
    p, ins = b.get("patient") or {}, b.get("insurance") or {}
    if on("flaky_start") and not fired("flaky_start"):
        mark_fired("flaky_start")
        return {"retryable": True,
                "message": "Something went wrong. Your request was not created. Please try again."}, 503
    time.sleep(0.4)
    canonical = json.dumps({"p": p, "i": ins, "f": form["id"], "d": drug[0]}, sort_keys=True)
    digest = hashlib.sha1(canonical.encode()).hexdigest()
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    key = "".join(alphabet[int(digest[i:i + 2], 16) % len(alphabet)] for i in range(0, 16, 2))
    if on("start_fails"):
        FAILURES[key] = {"reason": f"{form['title']} does not accept electronic prior authorization for this "
                                   "member. Fax the completed form to the plan instead.", "form": form["title"]}
        out = {"failed": True, "url": url_for("failed_page", ref=key)}
    else:
        REQUESTS[key] = {"patient": p, "insurance": ins, "form": form, "drug": drug[1]}
        out = {"url": url_for("request_page", key=key)}
    BY_TOKEN[token] = out
    SUBMISSION_LOG.append({"key": key, "ok": not on("start_fails"), "case": session.get("test_case")})
    return out, 200


@app.route("/formpick/review/<token>", methods=["GET", "POST"])
def review_page(token):
    """Scenario review_step: a 'Review your request' page between Start and the created request."""
    if not logged_in():
        return redirect(url_for("login", expired=1))
    pend = PENDING.get(token) or abort(404)
    if token in BY_TOKEN:                          # already submitted: same outcome again
        return redirect(BY_TOKEN[token]["url"])
    errors, message = {}, None
    if request.method == "POST":
        if on("review_validation"):
            zip5 = (pend["body"].get("patient") or {}).get("patient_zip", "")
            errors["patient_zip"] = f"ZIP code {zip5} is outside the service area of the selected plan."
        else:
            out, status = create_request(pend["body"], pend["form"], pend["drug"])
            if status == 200:
                return redirect(out["url"])
            message = out.get("message")
    return render_template("review.html", token=token, p=pend["body"].get("patient") or {},
                           ins=pend["body"].get("insurance") or {}, form=pend["form"], drug=pend["drug"][1],
                           states=STATES, errors=errors, message=message), (422 if errors or message else 200)


@app.route("/api/debug/submissions")
def api_submissions():
    selected = [e for e in SUBMISSION_LOG if e.get("case") == request.args.get("test_filter")]
    return jsonify({"count": len(SUBMISSION_LOG), "submissions": SUBMISSION_LOG, "records": REQUESTS,
                    "created_for_case": sum(e["ok"] for e in selected)})


@app.route("/healthz")
def healthz():
    return "ok"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5055)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    app.run(host=a.host, port=a.port, debug=False, threaded=True)
