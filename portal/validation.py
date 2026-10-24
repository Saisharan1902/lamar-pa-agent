"""Server-side checks for the synthetic Portal A (pharmacy PA flow from the trace).

Written independently of the agent's validator on purpose: the agent has to cope
with whatever the portal says back. Messages are modelled on real portal copy.
"""
import re
from datetime import date, datetime

from reference_data import STATES

NAME_OK = re.compile(r"^(?=.*[^\W\d_])(?:[^\W\d_]|[ '\-\u2019])+$")
SHORT_BINS = {"15921", "16127", "20974", "22022"}  # exact values in supplied form metadata


def parse_dob(s):
    """MM/DD/YYYY from the text field, or YYYY-MM-DD from a native date picker."""
    s = (s or "").strip()
    for fmt, rx in (("%m/%d/%Y", r"\d{2}/\d{2}/\d{4}"), ("%Y-%m-%d", r"\d{4}-\d{2}-\d{2}")):
        if re.fullmatch(rx, s):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                return None
    return None


def validate_patient(form, today: date):
    e = {}
    for key, label in (("first_name", "First Name"), ("last_name", "Last Name")):
        v = (form.get(key) or "").strip()
        if not v:
            e[key] = f"{label} is required."
        elif not NAME_OK.match(v):
            e[key] = f"{label} may only contain letters, spaces, hyphens and apostrophes."
    if form.get("sex") not in ("M", "F", "X"):
        e["sex"] = "Gender is required."
    raw = (form.get("date_of_birth") or "").strip()
    dob = parse_dob(raw)
    if not raw:
        e["date_of_birth"] = "Date of Birth is required."
    elif not dob:
        e["date_of_birth"] = "Enter a valid date (MM/DD/YYYY)."
    elif dob > today:
        e["date_of_birth"] = "Date of Birth cannot be in the future."
    if not re.fullmatch(r"\d{5}", (form.get("patient_zip") or "").strip()):
        e["patient_zip"] = "Enter a 5-digit ZIP code."
    if form.get("insurance_state") not in STATES:
        e["insurance_state"] = "Select the patient's insurance state."
    return e


def validate_insurance(args):
    e = {}
    if not (re.fullmatch(r"\d{6}", args.get("bin") or "") or args.get("bin") in SHORT_BINS):
        e["rx_bin"] = "RxBIN must be six digits or a supported captured identifier."
    p = (args.get("pcn") or "").strip()
    if p and not re.fullmatch(r"[A-Za-z0-9]{1,10}", p):
        e["rx_pcn"] = "RxPCN may only contain letters and numbers."
    g = (args.get("group_id") or "").strip()
    if g and not re.fullmatch(r"[A-Za-z0-9-]{1,15}", g):
        e["rx_group"] = "RxGroup may only contain letters, numbers and hyphens."
    if args.get("state") not in STATES:
        e["insurance_state"] = "Select the patient's insurance state."
    return e
