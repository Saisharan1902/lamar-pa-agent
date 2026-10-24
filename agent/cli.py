"""./run_agent --portal-url <URL> --patient <patient.json> --out <result.json>"""
import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

from .runner import Agent
from .actionlog import ActionLog


def main(argv=None):
    ap = argparse.ArgumentParser(description="Prior-authorization portal agent")
    ap.add_argument("--portal-url", required=True)
    ap.add_argument("--patient", required=True, help="path to one patient record (JSON object)")
    ap.add_argument("--out", required=True, help="where to write the result JSON")
    ap.add_argument("--log", help="action log path (default: <out>.log.jsonl)")
    ap.add_argument("--as-of", help="treat this YYYY-MM-DD as today (default: $AGENT_TODAY or system date)")
    ap.add_argument("--state-dir", default=os.environ.get("AGENT_STATE_DIR", ".agent_state"),
                    help="where the submission ledger lives")
    ap.add_argument("--headed", action="store_true", help="show the browser")
    ap.add_argument("--form-policy", choices=["first", "clarify"],
                    default=os.environ.get("AGENT_FORM_POLICY", "first"),
                    help="first: start the first (recommended) form and report the alternatives (default); "
                         "clarify: escalate when the portal offers more than one form")
    a = ap.parse_args(argv)

    today_s = a.as_of or os.environ.get("AGENT_TODAY")
    out = Path(a.out)
    log_path = Path(a.log) if a.log else out.with_suffix(".log.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    early_log = ActionLog()

    def stop(field, reason, problem, action):
        result = {"status": "ESCALATED", "reason": reason, "confirmation_id": None,
                  "fields_filled": {}, "escalation": {"field": field, "problem": problem,
                                                      "suggested_action": action}}
        early_log.add("validation_issue", field=field)
        early_log.add("end", status="ESCALATED")
        out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        early_log.write(log_path)
        print(json.dumps({"status": "ESCALATED", "reason": reason}))
        return 0

    try:
        today = date.fromisoformat(today_s) if today_s else date.today()
    except ValueError:
        return stop("as_of", "The validation date is invalid.", "Expected --as-of YYYY-MM-DD.",
                    "Provide a valid calendar date.")

    try:
        record = json.loads(Path(a.patient).read_text(encoding="utf-8"))
        if isinstance(record, list) and len(record) == 1:
            record = record[0]
        if not isinstance(record, dict):
            raise ValueError("patient file must contain one JSON object (a list is only accepted if it has one record)")
    except (OSError, ValueError) as e:
        return stop("patient_file", "Patient file could not be read.",
                    f"{type(e).__name__}: expected one readable JSON patient object.",
                    "Provide one valid JSON patient record.")

    agent = Agent(a.portal_url, record, today, a.state_dir, headless=not a.headed, form_policy=a.form_policy)
    try:
        result = agent.run()
    except Exception as e:  # never leave the caller without a result file
        agent.log.add("internal_error", error=type(e).__name__)
        result = {"status": "ESCALATED", "reason": "Agent internal error; request state unknown.",
                  "confirmation_id": None, "fields_filled": agent.filled,
                  "escalation": {"field": "agent", "problem": f"{type(e).__name__}: {e}"[:300],
                                 "suggested_action": "Check the portal for this request, then report the error."}}
    agent.log.add("end", status=result["status"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    agent.log.write(log_path)
    print(json.dumps({"status": result["status"], "reason": result["reason"],
                      "confirmation_id": result.get("confirmation_id")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
