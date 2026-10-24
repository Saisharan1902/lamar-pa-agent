"""Mock "Portal B": a second, deliberately different PA portal used only to test that the
agent generalises. It is NOT Lamar's Portal B (nobody has seen that); it is a stand-in
built to differ from Portal A on every axis the brief lists:

  layout      server-rendered wizard, one page per step (Portal A: one page of cards)
  labels      "Legal first name", "BIN / IIN", "Processor control number", "Plan state",
              "Drug to authorize", date of birth split into Month / Day / Year boxes
  controls    radio buttons for sex, a native <select> of full state names, an ARIA
              autocomplete for the drug
  flow        Patient -> Coverage -> Medication -> Review -> Submit -> "Request received"
              with a reference number (no form list, no Key)
  popups      cookie banner, feedback modal on the review page, "still there?" timeout modal
  ids         every element id is random on every page load

Run:  python portal_b/app.py --port 5066      then http://localhost:5066/?scenarios=...
"""
import argparse
import hashlib
import json
import os
import re
import secrets
import sys
from datetime import date, datetime
from pathlib import Path

from flask import Flask, abort, g, jsonify, redirect, render_template, request, session

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "portal"))
from reference_data import STATES  # noqa: E402  (code -> name)

SCENARIOS = {
    "cookie_banner": "Cookie banner fixed over the bottom of every page (default on).",
    "feedback_modal": "Modal 'Quick feedback' dialog on the review page.",
    "idle_modal": "'Are you still there?' modal on the coverage step.",
    "slow_lookup": "Drug lookup takes 2 seconds.",
    "unknown_plan": "Coverage step rejects the BIN: 'No pharmacy plan matches this BIN / IIN.'",
    "attestation": "Review page requires an 'I attest...' checkbox (not in the data contract).",
    "plan_rejects": "Submit ends on 'Submission not accepted' with a reason.",
    "duplicate_request": "Review page shows 'An open request already exists for this patient' dialog.",
}
DEFAULTS = ["cookie_banner"]
DRUGS = ["Simponi Aria 50MG/4ML solution", "Simponi 50MG/0.5ML auto-injector", "Humira 40MG/0.4ML pen",
         "Humira 40MG/0.8ML pen", "Humira 80MG/0.8ML pen", "Enbrel 50MG/ML syringe"]
USERNAME = os.environ.get("PORTAL_USER", "demo")
PASSWORD = os.environ.get("PORTAL_PASS", "demo123")
NAME_OK = re.compile(r"^(?=.*[^\W\d_])(?:[^\W\d_]|[ '\-\u2019])+$")

app = Flask(__name__, template_folder="templates")
app.secret_key = "portal-b-dev-secret"
SUBMITTED = {}   # ref -> request
FAILED = {}
CREATION_EVENTS = []


def today():
    t = os.environ.get("PORTAL_TODAY")
    return date.fromisoformat(t) if t else date.today()


@app.before_request
def scenarios():
    if "scenarios" in request.args:
        raw = request.args["scenarios"].strip()
        chosen = [] if raw in ("", "none") else [s.strip() for s in raw.split(",")]
        if any(s not in SCENARIOS for s in chosen):
            abort(400, "unknown scenario")
        session.clear()
        session["scn"] = chosen
    elif "scn" not in session:
        session["scn"] = list(DEFAULTS)
    if "test_case" in request.args:
        session["test_case"] = request.args["test_case"]
    g.scn = set(session["scn"])
    g.rid = lambda name: f"{name}-{secrets.token_hex(3)}"     # ids change on every load


@app.context_processor
def helpers():
    return {"on": lambda n: n in g.scn, "rid": g.rid, "states": STATES}


def signed_in():
    return session.get("user") == USERNAME


@app.get("/healthz")
def healthz():
    return "ok"


@app.get("/")
def home():
    return redirect("/request/patient" if signed_in() else "/signin")


@app.route("/signin", methods=["GET", "POST"])
def signin():
    err = None
    if request.method == "POST":
        if request.form.get("uid") == USERNAME and request.form.get("pc") == PASSWORD:
            session["user"] = USERNAME
            session["req"] = {}
            return redirect("/request/patient")
        err = "That user ID and passcode don't match our records."
    return render_template("signin.html", err=err)


def need_login():
    return None if signed_in() else redirect("/signin")


def parse_dob(m, d, y):
    if not (re.fullmatch(r"\d{2}", m or "") and re.fullmatch(r"\d{2}", d or "") and re.fullmatch(r"\d{4}", y or "")):
        return None
    try:
        return datetime(int(y), int(m), int(d)).date()
    except ValueError:
        return None


@app.route("/request/patient", methods=["GET", "POST"])
def patient():
    if (r := need_login()):
        return r
    errs, f = {}, request.form
    if request.method == "POST":
        for k, lab in (("fn", "Legal first name"), ("ln", "Legal last name")):
            v = (f.get(k) or "").strip()
            if not v:
                errs[k] = f"{lab} is required."
            elif not NAME_OK.match(v):
                errs[k] = f"{lab} can only use letters, spaces, hyphens and apostrophes."
        dob = parse_dob(f.get("dm"), f.get("dd"), f.get("dy"))
        if not dob:
            errs["dob"] = "Enter a real date of birth (MM, DD, YYYY)."
        elif dob > today():
            errs["dob"] = "Date of birth can't be in the future."
        if f.get("sx") not in ("female", "male", "other"):
            errs["sx"] = "Choose the patient's sex."
        if not re.fullmatch(r"\d{5}", f.get("zp") or ""):
            errs["zp"] = "Home ZIP must be 5 digits."
        if not errs:
            session["req"] = {**session.get("req", {}), "fn": f["fn"], "ln": f["ln"],
                              "dob": dob.strftime("%m/%d/%Y"), "sx": f["sx"], "zp": f["zp"]}
            return redirect("/request/coverage")
    return render_template("patient.html", errs=errs, f=f, step=1)


@app.route("/request/coverage", methods=["GET", "POST"])
def coverage():
    if (r := need_login()):
        return r
    errs, f = {}, request.form
    if request.method == "POST":
        if f.get("st") not in STATES.values():
            errs["st"] = "Choose the state of the pharmacy plan."
        if not (re.fullmatch(r"\d{6}", f.get("bin") or "") or f.get("bin") == "22022"):
            errs["bin"] = "BIN / IIN is the 6-digit number on the pharmacy card."
        elif "unknown_plan" in g.scn:
            errs["bin"] = "No pharmacy plan matches this BIN / IIN."
        if (f.get("pcn") or "") and not re.fullmatch(r"[A-Za-z0-9]{1,10}", f["pcn"]):
            errs["pcn"] = "Processor control number: letters and numbers only."
        if (f.get("grp") or "") and not re.fullmatch(r"[A-Za-z0-9-]{1,15}", f["grp"]):
            errs["grp"] = "Rx group: letters, numbers and hyphens only."
        if not errs:
            session["req"] = {**session.get("req", {}), "st": f["st"], "bin": f["bin"],
                              "pcn": f.get("pcn", ""), "grp": f.get("grp", "")}
            return redirect("/request/medication")
    return render_template("coverage.html", errs=errs, f=f, step=2)


@app.get("/api/drugs")
def drugs():
    import time
    if "slow_lookup" in g.scn:
        time.sleep(2)
    q = (request.args.get("q") or "").strip().lower()
    return jsonify([d for d in DRUGS if q and d.lower().startswith(q)] if len(q) >= 2 else [])


@app.route("/request/medication", methods=["GET", "POST"])
def medication():
    if (r := need_login()):
        return r
    errs, f = {}, request.form
    if request.method == "POST":
        if f.get("drug_pick") not in DRUGS or f.get("drug") != f.get("drug_pick"):
            errs["drug"] = "Pick the drug from the list of matches."
        if not errs:
            session["req"] = {**session.get("req", {}), "drug": f["drug_pick"]}
            return redirect("/request/review")
    return render_template("medication.html", errs=errs, f=f, step=3)


@app.route("/request/review", methods=["GET", "POST"])
def review():
    if (r := need_login()):
        return r
    req = session.get("req", {})
    if not all(k in req for k in ("fn", "bin", "drug")):
        return redirect("/request/patient")
    errs = {}
    if request.method == "POST":
        if "attestation" in g.scn and request.form.get("attest") != "yes":
            errs["attest"] = "You must confirm the attestation to submit."
        if not errs:
            body = json.dumps(req, sort_keys=True)
            ref = "MR-" + hashlib.sha256(body.encode()).hexdigest()[:6].upper()
            if "plan_rejects" in g.scn:
                FAILED[ref] = req
                return redirect(f"/request/not-accepted/{ref}")
            SUBMITTED.setdefault(ref, req)
            if session.get("submitted_ref") != ref:
                CREATION_EVENTS.append({"ref": ref, "case": session.get("test_case")})
                session["submitted_ref"] = ref
            return redirect(f"/request/received/{ref}")
    sex = {"female": "Female", "male": "Male", "other": "Unknown / other"}.get(req.get("sx"), "")
    return render_template("review.html", r=req, sex=sex, errs=errs, step=4)


@app.get("/request/received/<ref>")
def received(ref):
    if ref not in SUBMITTED:
        abort(404)
    return render_template("received.html", ref=ref, r=SUBMITTED[ref])


@app.get("/request/not-accepted/<ref>")
def not_accepted(ref):
    if ref not in FAILED:
        abort(404)
    return render_template("not_accepted.html", ref=ref)


@app.get("/api/debug/submissions")
def debug_submissions():
    return jsonify({"count": len(SUBMITTED), "records": SUBMITTED,
                    "created_for_case": sum(e["case"] == request.args.get("test_filter") for e in CREATION_EVENTS)})


from challenges import bp as challenge_blueprint
app.register_blueprint(challenge_blueprint)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5066)
    a = ap.parse_args()
    app.run(host="127.0.0.1", port=a.port, debug=False, threaded=True)
