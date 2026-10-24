"""Run the agent over every case in tests/cases.json against a fresh Portal A.

    python tests/run_eval.py            # everything, writes results/
    python tests/run_eval.py --only kitchen_sink --repeat 0

Starts the portal itself (fixed PORTAL_TODAY so date rules never drift), runs
./run_agent as a subprocess exactly as reviewers will, checks status + escalated
field, runs the ledger (double-submit) checks, then the repeatability check:
the same case N times must give byte-identical result JSON and action logs.
"""
import argparse
import json
import os
import shutil
import socket
import subprocess
import tempfile
import sys
import time
import re
import urllib.request
from urllib.parse import urlencode
from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from agent.ledger import Ledger, record_key  # noqa: E402
from agent import fields as F
from agent.validate import validate_record  # noqa: E402

SPEC = json.loads((ROOT / "tests" / "cases.json").read_text())
TODAY = SPEC["today"]
SAMPLES = {r["case_id"]: r for r in json.loads((ROOT / SPEC["samples_file"]).read_text())}


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Portal:
    def __init__(self, app="portal/app.py"):
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        env = dict(os.environ, PORTAL_TODAY=TODAY)
        # portal output goes to a file (a pipe would fill up with request logs and stall the portal)
        self.log = tempfile.TemporaryFile(mode="w+")
        self.proc = subprocess.Popen([sys.executable, str(ROOT / app), "--port", str(self.port)],
                                     env=env, stdout=self.log, stderr=subprocess.STDOUT)
        for _ in range(100):
            if self.proc.poll() is not None:
                break
            try:
                urllib.request.urlopen(self.base + "/healthz", timeout=1)
                return
            except OSError:
                time.sleep(0.1)
        self.proc.kill()
        self.proc.wait(5)
        self.log.seek(0)
        err = self.log.read()
        raise RuntimeError(f"{app} did not start. Portal output:\n" + err[-2000:])

    def submissions(self):
        return json.load(urllib.request.urlopen(self.base + "/api/debug/submissions"))["count"]

    def creations(self, case):
        url = self.base + "/api/debug/submissions?" + urlencode({"test_filter": case})
        return json.load(urllib.request.urlopen(url))["created_for_case"]

    def stop(self):
        self.proc.terminate()
        self.proc.wait(5)


def build_record(case):
    if "record_inline" in case:                    # a record outside the sample file (e.g. Section 4 shape)
        return dict(case["record_inline"])
    rec = dict(SAMPLES[case.get("record") or SPEC["default_record"]])
    for k, v in case.get("overrides", {}).items():
        if v is None:
            rec.pop(k, None)
        else:
            rec[k] = v
    return rec


def url_for(portal, case):
    params = {"test_case": case["name"]}
    if case.get("scenarios"):
        params["scenarios"] = case["scenarios"]
    return portal.base + "/?" + urlencode(params)


def run_agent(portal_url, record, workdir, state_dir=None, args=()):
    workdir.mkdir(parents=True, exist_ok=True)
    pfile = workdir / "patient.json"
    pfile.write_text(json.dumps(record, indent=2, ensure_ascii=False))
    env = dict(os.environ, AGENT_STATE_DIR=str(state_dir or workdir / "state"), PYTHON=sys.executable)
    t0 = time.monotonic()
    proc = subprocess.run([str(ROOT / "run_agent"), "--portal-url", portal_url, "--patient", str(pfile),
                           "--out", str(workdir / "result.json"), "--as-of", TODAY, *args],
                          env=env, capture_output=True, text=True, timeout=400)
    elapsed = time.monotonic() - t0
    if proc.returncode != 0 or not (workdir / "result.json").exists():
        return {"status": "CRASH", "reason": proc.stderr[-800:]}, "", elapsed
    log = (workdir / "result.log.jsonl").read_text() if (workdir / "result.log.jsonl").exists() else ""
    return json.loads((workdir / "result.json").read_text()), log, elapsed


def check(case, result):
    ok = result["status"] == case["expect"]
    if ok and case.get("field"):
        ok = (result.get("escalation") or {}).get("field") == case["field"]
    return ok


def verify_saved(portal, record, result):
    if result["status"] != "SUCCESS":
        return True, ""
    conf = result.get("confirmation_id")
    if not conf:
        return False, "SUCCESS has no reference"
    snapshot = json.load(urllib.request.urlopen(portal.base + "/api/debug/submissions"))
    saved = snapshot.get("records", {}).get(conf)
    if not saved:
        return False, "Reference does not identify a saved request"
    if "patient" in saved:
        actual = {**saved["patient"], **saved["insurance"]}
        drug = saved["drug"]
        form = saved["form"]["title"]
        if form != (result.get("form_selection") or {}).get("chosen"):
            return False, "Saved form differs from selected form"
    else:
        actual = {"first_name": saved["fn"], "last_name": saved["ln"], "date_of_birth": saved["dob"],
                  "sex": {"female":"F","male":"M","other":"X"}[saved["sx"]],
                  "patient_zip": saved["zp"], "insurance_state": next(k for k,v in F.STATE_NAMES.items() if v == saved["st"]),
                  "rx_bin":saved["bin"], "rx_pcn":saved["pcn"], "rx_group":saved["grp"]}
        drug = saved["drug"]
    for field in ("first_name","last_name","sex","date_of_birth","patient_zip","insurance_state","rx_bin","rx_pcn","rx_group"):
        if field == "date_of_birth":
            def calendar_date(value):
                for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
                    try:
                        return datetime.strptime(value, fmt).date()
                    except (ValueError, TypeError):
                        pass
                return None
            got, want = calendar_date(actual.get(field)), calendar_date(record.get(field))
            if got is None or got != want:
                return False, "Saved field mismatch: " + field
        elif actual.get(field, "") != (record.get(field) or ""):
            return False, "Saved field mismatch: " + field
    if F.option_matches("medication_search",record["medication_search"],drug) == 0:
        # For NDC searches, verify against independent drug metadata on Portal A.
        import importlib.util
        spec = importlib.util.spec_from_file_location("oracle_reference", ROOT/"portal/reference_data.py")
        data = importlib.util.module_from_spec(spec); spec.loader.exec_module(data)
        if not any(d[1]==drug and d[2]==record["medication_search"].replace("-","") for d in data.DRUGS):
            return False, "Saved medication mismatch"
    return True, "saved values verified"


def run_case(portals, case, out_dir):
    portal = portals[case.get("portal", "a")]
    wd = out_dir / "runs" / case["name"]
    shutil.rmtree(wd, ignore_errors=True)
    before = portal.creations(case["name"])
    result, _, secs = run_agent(url_for(portal, case), build_record(case), wd, args=case.get("args", ()))
    creations = portal.creations(case["name"]) - before
    count_ok = creations == (1 if case["expect"] == "SUCCESS" else 0)
    saved_ok, evidence = verify_saved(portal, build_record(case), result)
    return {"name": case["name"], "creations": creations, "saved_values_checked": result["status"] == "SUCCESS", "portal": case.get("portal", "a").upper(), "group": case.get("group", ""), "scenarios": case.get("scenarios") or "(defaults)",
            "expect": case["expect"] + (f" / {case['field']}" if case.get("field") else ""),
            "got": result["status"] + (f" / {(result.get('escalation') or {}).get('field')}"
                                       if result.get("escalation") else ""),
            "reason": result.get("reason", ""), "pass": check(case, result) and saved_ok and count_ok, "seconds": round(secs, 1),
            "note": case.get("note", "") + ("; " + evidence if evidence else "")}


def ledger_cases(portal, out_dir):
    rows = []
    base = {"name": "x", "scenarios": None, "record": SPEC["default_record"]}
    rec = build_record(base)

    # 1. same record twice with the same ledger: second run must not submit again
    wd = out_dir / "runs" / "rerun_after_success_no_double_submit"
    shutil.rmtree(wd, ignore_errors=True)
    state = wd / "state"
    first, _, _ = run_agent(url_for(portal, base), rec, wd / "first", state)
    before = portal.submissions()
    second, log2, secs = run_agent(url_for(portal, base), rec, wd / "second", state)
    after = portal.submissions()
    ok = (first["status"] == "SUCCESS" and second == first and after == before and '"ledger_hit"' in log2)
    rows.append({"name": "rerun_after_success_no_double_submit", "group": "ledger", "scenarios": "(defaults)",
                 "expect": "SUCCESS, same request key, 0 new requests",
                 "got": f"{second['status']} {second.get('confirmation_id')}, {after - before} new requests",
                 "reason": second.get("reason", ""), "pass": ok, "seconds": round(secs, 1)})

    # 2. a previous run died right after clicking submit: must escalate, not resubmit
    wd = out_dir / "runs" / "interrupted_after_submit_escalates"
    shutil.rmtree(wd, ignore_errors=True)
    state = wd / "state"
    norm, _ = validate_record(rec, date.fromisoformat(TODAY))
    Ledger(state).mark_submitting(record_key(portal.base, norm))
    before = portal.submissions()
    res, _, secs = run_agent(url_for(portal, base), rec, wd, state)
    after = portal.submissions()
    ok = res["status"] == "ESCALATED" and (res.get("escalation") or {}).get("field") == "submission" and after == before
    rows.append({"name": "interrupted_after_submit_escalates", "group": "ledger", "scenarios": "(defaults)",
                 "expect": "ESCALATED / submission, 0 new requests",
                 "got": f"{res['status']} / {(res.get('escalation') or {}).get('field')}, {after - before} new requests",
                 "reason": res.get("reason", ""), "pass": ok, "seconds": round(secs, 1)})
    return rows


def trace_replay(portal):
    """Replay the selectors and values recorded in the Portal A trace (14316.zip) against the
    synthetic portal. If the reproduction is faithful, the recording runs unchanged."""
    from playwright.sync_api import sync_playwright
    t0 = time.monotonic()
    steps = []
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1280, "height": 800})
            pg.goto(portal.base + "/?scenarios=none")
            pg.fill("input[name=username]", "demo"); pg.fill("input[name=password]", "demo123")
            pg.get_by_role("button", name="Sign In").click()
            cb = pg.get_by_role("combobox", name="Search for medication name or")          # call@55
            cb.fill(""); cb.fill("12341111111"); pg.wait_for_timeout(900)                   # call@57
            steps.append("NDC 12341111111 -> " + pg.locator(".no-results").inner_text())
            cb.fill(""); cb.fill("Simponi Aria"); pg.wait_for_selector('[role="option"]')    # call@71/75
            steps.append(f"options for 'Simponi Aria': {pg.locator('[role=option]').count()}")
            pg.locator('[role="option"] >> nth=0').click()                                  # call@87
            pg.click("#skip-diagnosis")                                                      # call@99
            pg.get_by_role("textbox", name="First Name").fill("Test")                        # call@105
            pg.get_by_role("textbox", name="Last Name").fill("Test")
            pg.click('internal:text="Female"s')                                              # call@111
            pg.get_by_role("textbox", name="Date of Birth").fill("11/13/1986")
            pg.get_by_role("textbox", name="Patient Zip Code").fill("74055")
            pg.locator("#patient-demographics-state-row").wait_for()                         # call@121
            steps.append("state row after ZIP: " + pg.locator("#patient-demographics-state-row [data-value-text]").inner_text())
            pg.click("#submit-patient-demographics")                                         # call@123
            # call@125 (expect "I don't know") and call@189/191 (eligibility button, "Start PA") failed
            # in the recording: those states did not appear, so they are not waited for here.
            pg.click("#insurance-search-state-row")                                          # call@145
            pg.fill("#insurance-search-state-row-search", "Oklahoma")                        # call@149
            pg.get_by_role("option", name=re.compile(r"^(OK|Oklahoma)$", re.I)).click()      # call@155
            pg.get_by_role("textbox", name="RxBIN").fill("610602")                           # call@161
            pg.get_by_role("textbox", name="RxPCN Number").fill("NVT")                       # call@173
            pg.get_by_role("textbox", name="RxGroup").fill("")                               # call@185
            pg.get_by_role("button", name="Start Request").first.wait_for()
            pg.click("#showMoreForms")                                                       # call@197
            pg.locator('#submit-pa-67652 >> [type="submit"]').click()                        # call@213
            pg.wait_for_url("**/v2/requests/*")
            steps.append("landed on: " + pg.locator("h1").inner_text())
            b.close()
        ok = True
    except Exception as e:  # noqa: BLE001
        steps.append(f"FAILED: {type(e).__name__}: {str(e).splitlines()[0][:200]}")
        ok = False
    return {"name": "trace_replay_fidelity", "group": "fidelity", "scenarios": "none",
            "expect": "trace's own selectors reach the request page", "got": " | ".join(steps),
            "reason": "", "pass": ok, "seconds": round(time.monotonic() - t0, 1), "note": ""}


def repeatability(portals, cases, runs, out_dir, jobs):
    by_name = {c["name"]: c for c in SPEC["cases"]}
    rows = []

    def one(name):
        case = by_name[name]
        portal = portals[case.get("portal", "a")]
        outs = []
        for k in range(runs):
            wd = out_dir / "repeat" / name / f"run{k + 1}"
            shutil.rmtree(wd, ignore_errors=True)
            before = portal.creations(name)
            res, log, _ = run_agent(url_for(portal, case), build_record(case), wd, args=case.get("args", ()))
            count_ok = portal.creations(name) - before == (1 if case["expect"] == "SUCCESS" else 0)
            saved_ok, _ = verify_saved(portal, build_record(case), res)
            outs.append((json.dumps(res, sort_keys=True), log, count_ok and saved_ok))
        same_result = len({o[0] for o in outs}) == 1
        same_log = len({o[1] for o in outs}) == 1
        status = json.loads(outs[0][0])["status"]
        return {"name": name, "runs": runs, "status": status, "identical_results": same_result,
                "identical_action_logs": same_log, "log_lines": outs[0][1].count("\n"),
                "note": "",
                "pass": same_result and same_log and all(o[2] for o in outs) and check(case, json.loads(outs[0][0]))}

    with ThreadPoolExecutor(jobs) as ex:
        rows = list(ex.map(one, cases))
    return rows


def write_report(out_dir, rows, rep_rows, elapsed):
    passed = sum(r["pass"] for r in rows)
    rp = sum(r["pass"] for r in rep_rows)
    lines = [f"# Evaluation report", "",
             f"Portal A (synthetic, from the trace) and mock Portal B (a deliberately different portal, "
             f"`portal_b/`), as-of date {TODAY}. Total wall time {elapsed:.0f}s.", "",
             f"**Cases: {passed}/{len(rows)} passed. Repeatability: {rp}/{len(rep_rows)} passed "
             f"({sum(r['identical_results'] for r in rep_rows)} with identical results, "
             f"{sum(r['identical_action_logs'] for r in rep_rows)} with identical action logs).**", "",
             "| # | Case | Portal | Group | Scenarios | Expected | Got | Pass | s |", "|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        lines.append(f"| {i} | {r['name']} | {r.get('portal', 'A')} | {r['group']} | {r['scenarios']} | {r['expect']} | {r['got']} | "
                     f"{'yes' if r['pass'] else '**NO**'} | {r['seconds']} |")
    lines += ["", "## Repeatability", "",
              "Each case run independently N times (fresh ledger each run). Result JSON and action log must be byte-identical.", "",
              "| Case | Runs | Status | Identical results | Identical action logs | Log lines | Pass | Note |",
              "|---|---|---|---|---|---|---|---|"]
    for r in rep_rows:
        lines.append(f"| {r['name']} | {r['runs']} | {r['status']} | {r['identical_results']} | "
                     f"{r['identical_action_logs']} | {r['log_lines']} | {'yes' if r['pass'] else '**NO**'} | {r['note']} |")
    notes = [r for r in rows if r.get("note")]
    if notes:
        lines += ["", "## Notes", ""] + [f"- **{r['name']}**: {r['note']}" for r in notes]
    lines += ["", "## Reasons returned", ""]
    for r in rows:
        lines.append(f"- **{r['name']}**: {r['reason']}")
    (out_dir / "eval_report.md").write_text("\n".join(lines) + "\n")
    (out_dir / "eval_results.json").write_text(json.dumps({"cases": rows, "repeatability": rep_rows}, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--repeat", type=int, default=SPEC["repeatability"]["runs"])
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--out", default=str(ROOT / "results"))
    a = ap.parse_args()
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    portals = {"a": Portal("portal/app.py"), "b": Portal("portal_b/app.py")}
    portal = portals["a"]
    try:
        cases = [c for c in SPEC["cases"] if not a.only or c["name"] in a.only]
        with ThreadPoolExecutor(a.jobs) as ex:
            rows = list(ex.map(lambda c: run_case(portals, c, out_dir), cases))
        for r in rows:
            print(f"{'PASS' if r['pass'] else 'FAIL'}  {r['name']:<38} expect {r['expect']:<32} got {r['got']}  ({r['seconds']}s)")
        if not a.only:
            r = trace_replay(portal)
            rows.insert(0, r)
            print(f"{'PASS' if r['pass'] else 'FAIL'}  {r['name']:<38} {r['got']}")
            for r in ledger_cases(portal, out_dir):
                rows.append(r)
                print(f"{'PASS' if r['pass'] else 'FAIL'}  {r['name']:<38} {r['got']}")
        rep_rows = []
        if a.repeat:
            rep_cases = [n for n in SPEC["repeatability"]["cases"] if not a.only or n in a.only]
            rep_rows = repeatability(portals, rep_cases, a.repeat, out_dir, a.jobs)
            for r in rep_rows:
                print(f"{'PASS' if r['pass'] else 'FAIL'}  repeat x{r['runs']} {r['name']:<30} results identical="
                      f"{r['identical_results']} logs identical={r['identical_action_logs']}")
        write_report(out_dir, rows, rep_rows, time.monotonic() - t0)
    finally:
        for p in portals.values():
            p.stop()
    failed = [r for r in rows if not r["pass"]] + [r for r in rep_rows if not r["pass"]]
    print(f"\n{len(rows) - sum(not r['pass'] for r in rows)}/{len(rows)} cases passed; "
          f"{sum(r['pass'] for r in rep_rows)}/{len(rep_rows)} repeatability checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
