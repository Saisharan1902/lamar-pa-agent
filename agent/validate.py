"""Pre-flight validation of a patient record (pharmacy PA contract from sample_patients.json).

Pure functions, no browser; runs before any portal is touched. The rule is that a
value is used exactly as given or the record is escalated: the agent never pads,
trims, re-cases or reformats data to make it pass.

Contract (from the sample file):
  medication_search, first_name, last_name, sex, date_of_birth (MM/DD/YYYY),
  patient_zip, insurance_state, rx_bin               required
  rx_pcn, rx_group                                   optional ("" = not provided)
  case_id, notes                                     metadata, never sent to a portal
"""
import re
from dataclasses import asdict, dataclass
from datetime import date

PHARMACY = ["medication_search", "first_name", "last_name", "sex", "date_of_birth",
            "patient_zip", "insurance_state", "rx_bin", "rx_pcn", "rx_group"]
PHARMACY_REQUIRED = ["medication_search", "first_name", "last_name", "sex", "date_of_birth",
                     "patient_zip", "insurance_state", "rx_bin"]
# The brief also supplies a medical-benefit contract. Detect its fields separately
# from the pharmacy sample and validate either shape without changing values.
MEDICAL = ["first_name", "last_name", "date_of_birth", "sex", "payer_name", "member_id", "group_number",
           "subscriber_relationship", "subscriber_first_name", "subscriber_last_name", "subscriber_name",
           "subscriber_dob", "provider_npi", "service_date", "cpt_code", "icd10_code", "place_of_service", "urgency"]
MEDICAL_REQUIRED = ["first_name", "last_name", "date_of_birth", "sex", "payer_name", "member_id",
                    "subscriber_relationship", "provider_npi", "service_date", "cpt_code", "icd10_code",
                    "place_of_service", "urgency"]
MEDICAL_MARKERS = {"payer_name", "member_id", "group_number", "subscriber_relationship", "provider_npi",
                   "service_date", "cpt_code", "icd10_code", "place_of_service", "urgency"}
PHARMACY_MARKERS = {"medication_search", "patient_zip", "insurance_state", "rx_bin", "rx_pcn", "rx_group"}
CONTRACT = PHARMACY + [k for k in MEDICAL if k not in PHARMACY]
REQUIRED = PHARMACY_REQUIRED          # recomputed per record in validate_record
METADATA = {"case_id", "notes"}

US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA",
    "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM",
    "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA",
    "WV", "WI", "WY",
}
# Preserve valid internal spacing and punctuation; require at least one letter.
NAME_RE = re.compile(r"^(?=.*[^\W\d_])(?:[^\W\d_]|[ '\-\u2019])+$")
# These exact identifiers occur in the supplied trace metadata. They are used as
# supplied, not padded; all other BIN inputs must contain six digits.
CAPTURED_SHORT_BINS = frozenset({"15921", "16127", "20974", "22022"})
DOB_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
ZIP_RE = re.compile(r"^\d{5}$")
BIN_RE = re.compile(r"^\d{6}$")
PCN_RE = re.compile(r"^[A-Za-z0-9]{1,10}$")
GROUP_RE = re.compile(r"^[A-Za-z0-9-]+$")
RX_GROUP_RE = re.compile(r"^[A-Za-z0-9-]{1,15}$")


@dataclass
class Issue:
    field: str
    problem: str
    suggested_action: str

    def to_dict(self):
        return asdict(self)


MEMBER_ID_RE = re.compile(r"^[A-Za-z]\d{9}$")
NPI_RE = re.compile(r"^\d{10}$")
CPT_RE = re.compile(r"^\d{5}$")
ICD10_RE = re.compile(r"^[A-Za-z]\d{2}(\.?[A-Za-z0-9]{1,4})?$")
POS_RE = re.compile(r"^\d{2}$")
ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
RELATIONSHIPS = ("self", "spouse", "child", "other")
URGENCIES = ("standard", "expedited")


def contract_for(record):
    """Which contract(s) a record follows: 'pharmacy' (sample_patients.json, the default), 'medical'
    (brief Section 4), or both when it carries fields of both."""
    keys = {k for k, v in record.items() if not _blank(v)} if isinstance(record, dict) else set()
    modes = []
    if keys & PHARMACY_MARKERS or not keys & MEDICAL_MARKERS:
        modes.append("pharmacy")
    if keys & MEDICAL_MARKERS:
        modes.append("medical")
    return modes


def npi_ok(npi):
    """NPI check digit: Luhn over '80840' + the first 9 digits (CMS NPI standard)."""
    digits = [int(c) for c in "80840" + npi[:9]]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - total % 10) % 10 == int(npi[9])


def parse_iso_date(s):
    m = ISO_RE.match(s or "")
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def parse_any_date(s):
    return parse_us_date(s) or parse_iso_date(s)


def parse_us_date(s):
    m = DOB_RE.match(s or "")
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


def age_on(dob, on):
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


def _blank(v):
    return v is None or (isinstance(v, str) and v == "")


def portal_fields(record):
    """The part of the record that goes to a portal (metadata removed, empty optionals removed)."""
    return {k: v for k, v in record.items() if k in CONTRACT and not _blank(v)}


def validate_record(record, today):
    """Return (portal_record, [Issue]). An empty issue list means safe to send."""
    issues = []
    if not isinstance(record, dict):
        return {}, [Issue("record", "patient record is not a JSON object", "Provide one JSON object per patient.")]

    for k, v in record.items():
        if k in CONTRACT and v is not None and not isinstance(v, str):
            issues.append(Issue(k, f"{k} should be text, got {type(v).__name__} ({v!r})",
                                f"Send {k} as a string, exactly as printed on the source document."))
    bad_type = {i.field for i in issues}
    rec = {k: v for k, v in record.items() if k not in bad_type}

    modes = contract_for(rec)
    required = list(dict.fromkeys((PHARMACY_REQUIRED if "pharmacy" in modes else [])
                                  + (MEDICAL_REQUIRED if "medical" in modes else [])))
    for k in required:
        if k not in bad_type and _blank(rec.get(k)):
            issues.append(Issue(k, f"{k} is missing", f"Add {k} to the record."))

    def present(k):
        v = rec.get(k)
        return None if _blank(v) else v

    for k in CONTRACT:
        v = present(k)
        if v is not None and v != v.strip():
            issues.append(Issue(k, f"{k} has leading or trailing spaces",
                                f"Confirm the exact {k} and remove the extra spaces in the source record."))
    spaced = {i.field for i in issues if "spaces" in i.problem}

    if (v := present("medication_search")) and "medication_search" not in spaced:
        if len(v) < 2:
            issues.append(Issue("medication_search", f"medication search '{v}' is too short to search",
                                "Provide the drug name (and strength if known) or the 11-digit NDC."))
        elif re.fullmatch(r"[\d-]+", v) and len(v.replace("-", "")) not in (10, 11):
            issues.append(Issue("medication_search", f"'{v}' looks like an NDC but is not 10 or 11 digits",
                                "Copy the NDC exactly from the prescription or package."))

    for k, label in (("first_name", "first name"), ("last_name", "last name")):
        if (v := present(k)) and k not in spaced and not NAME_RE.match(v):
            issues.append(Issue(k, f"patient {label} '{v}' contains characters other than letters, "
                                   f"spaces, hyphens or apostrophes",
                                f"Check the patient's {label} against their insurance card."))

    if (v := present("sex")) and v not in ("M", "F", "X"):
        issues.append(Issue("sex", f"sex '{v}' is not one of M, F, X", "Record the patient's sex as M, F or X."))

    if (v := present("date_of_birth")) and "date_of_birth" not in spaced:
        # pharmacy records use MM/DD/YYYY (sample file); the brief's medical example uses YYYY-MM-DD
        d = parse_any_date(v) if modes == ["medical"] else parse_us_date(v)
        fmt = "YYYY-MM-DD or MM/DD/YYYY" if modes == ["medical"] else "MM/DD/YYYY"
        if not d:
            issues.append(Issue("date_of_birth", f"date of birth '{v}' is not a valid {fmt} date",
                                f"Correct the date of birth in the source record (format {fmt})."))
        elif d > today:
            issues.append(Issue("date_of_birth", f"date of birth {v} is in the future",
                                "Verify the date of birth against the patient's chart."))
        elif age_on(d, today) > 120:
            issues.append(Issue("date_of_birth", f"date of birth {v} gives an age over 120",
                                "Verify the year of birth."))

    if (v := present("patient_zip")) and "patient_zip" not in spaced and not ZIP_RE.match(v):
        issues.append(Issue("patient_zip", f"ZIP code '{v}' is not 5 digits",
                            "Confirm the patient's 5-digit ZIP code."))

    if (v := present("insurance_state")) and "insurance_state" not in spaced and v not in US_STATES:
        issues.append(Issue("insurance_state", f"insurance state '{v}' is not a 2-letter US state code (e.g. OK)",
                            "Record the state of the patient's insurance as a 2-letter code."))

    if (v := present("rx_bin")) and "rx_bin" not in spaced and not (BIN_RE.fullmatch(v) or v in CAPTURED_SHORT_BINS):
        issues.append(Issue("rx_bin", f"RxBIN '{v}' is neither six digits nor a captured supported identifier.",
                            "Copy the RxBIN from the source card or confirm its supported portal representation; "
                            "the agent will not pad it."))

    if (v := present("rx_pcn")) and "rx_pcn" not in spaced and not PCN_RE.match(v):
        issues.append(Issue("rx_pcn", f"RxPCN '{v}' may only contain letters and digits (max 10)",
                            "Copy the PCN exactly from the insurance card, or leave it empty."))

    if (v := present("rx_group")) and "rx_group" not in spaced and not RX_GROUP_RE.fullmatch(v):
        issues.append(Issue("rx_group", f"RxGroup '{v}' may only contain letters, digits and hyphens (max 15)",
                            "Copy the RxGroup exactly from the insurance card, or leave it empty."))

    if "medical" in modes:
        issues += _medical_issues(present, spaced, today)

    order = {k: i for i, k in enumerate(CONTRACT)}
    seen, uniq = set(), []
    for it in sorted(issues, key=lambda x: order.get(x.field, 99)):
        if it.field not in seen:
            seen.add(it.field)
            uniq.append(it)
    return portal_fields(rec), uniq


def _medical_issues(present, spaced, today):
    """Brief Section 4 rules for the medical-benefit fields (only for records that carry them)."""
    out = []

    def bad(field, problem, action):
        if field not in spaced:
            out.append(Issue(field, problem, action))

    if (v := present("member_id")) and not MEMBER_ID_RE.match(v):
        bad("member_id", f"member ID '{v}' is not 1 letter followed by 9 digits",
            "Copy the member ID exactly from the patient's insurance card.")
    if (v := present("group_number")) and not GROUP_RE.match(v):
        bad("group_number", f"group number '{v}' may only contain letters, digits and hyphens",
            "Copy the group number exactly from the insurance card, or leave it empty.")
    if (v := present("subscriber_relationship")):
        if v not in RELATIONSHIPS:
            bad("subscriber_relationship", f"subscriber relationship '{v}' is not one of {', '.join(RELATIONSHIPS)}",
                "Record the patient's relationship to the subscriber as self, spouse, child or other.")
        elif v != "self":
            if not (present("subscriber_name") or (present("subscriber_first_name") and present("subscriber_last_name"))):
                bad("subscriber_name", f"subscriber relationship is '{v}' but the subscriber's name is missing",
                    "Add the subscriber's first and last name from the insurance card.")
            sd = present("subscriber_dob")
            if not sd:
                bad("subscriber_dob", f"subscriber relationship is '{v}' but the subscriber's date of birth is missing",
                    "Add the subscriber's date of birth.")
            elif not parse_any_date(sd) or parse_any_date(sd) > today:
                bad("subscriber_dob", f"subscriber date of birth '{sd}' is not a valid past date",
                    "Correct the subscriber's date of birth.")
    if (v := present("provider_npi")):
        if not NPI_RE.match(v):
            bad("provider_npi", f"provider NPI '{v}' is not 10 digits", "Look up the prescriber's 10-digit NPI.")
        elif not npi_ok(v):
            bad("provider_npi", f"provider NPI '{v}' fails the NPI check digit (Luhn)",
                "Look up the prescriber's NPI in the NPPES registry; one digit is probably wrong.")
    if (v := present("service_date")):
        d = parse_any_date(v)
        if not d:
            bad("service_date", f"service date '{v}' is not a valid date", "Correct the service date (YYYY-MM-DD).")
        elif d < today:
            bad("service_date", f"service date {v} is in the past", "Confirm the planned date of service.")
        elif (d - today).days > 180:
            bad("service_date", f"service date {v} is more than 180 days ahead", "Confirm the planned date of service.")
    if (v := present("cpt_code")) and not CPT_RE.match(v):
        bad("cpt_code", f"CPT code '{v}' is not 5 digits", "Copy the CPT code exactly from the order.")
    if (v := present("icd10_code")) and not ICD10_RE.match(v):
        bad("icd10_code", f"ICD-10 code '{v}' is not a valid ICD-10 format (e.g. M54.50)",
            "Copy the diagnosis code exactly from the chart.")
    if (v := present("place_of_service")) and not POS_RE.match(v):
        bad("place_of_service", f"place of service '{v}' is not a 2-digit code", "Use the 2-digit place-of-service code (e.g. 11).")
    if (v := present("urgency")) and v not in URGENCIES:
        bad("urgency", f"urgency '{v}' is not one of standard, expedited", "Set urgency to standard or expedited.")
    return out
