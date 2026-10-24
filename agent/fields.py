"""Portal-agnostic knowledge about the contract fields.

Maps whatever label a portal puts on a control to a contract field, and a
contract value to the option text a portal is likely to show. Nothing here refers
to Portal A's ids, classes or layout.
"""
import re
import unicodedata
from datetime import datetime

from .validate import parse_any_date

PROVIDER_CTX = r"provider|physician|prescriber|doctor|referring|rendering|ordering|pharmacy name|facility"

# (field, label regex, condition). First match wins.
FIELD_RULES = [
    # brief Section 4 (medical-benefit) fields: only filled when the record carries them
    ("provider_npi", r"\bnpi\b", None),
    ("subscriber_relationship", r"relationship", None),
    ("subscriber_first_name", r"(subscriber|insured|policy ?holder|cardholder)('s)? (first|given)", None),
    ("subscriber_last_name", r"(subscriber|insured|policy ?holder|cardholder)('s)? (last|sur|family)", None),
    ("subscriber_dob", r"(subscriber|insured|policy ?holder|cardholder)('s)? .*(birth|dob)", None),
    ("subscriber_name", r"(subscriber|insured|policy ?holder|cardholder)('s)? (full )?name$", None),
    ("member_id", r"member ?(id|number|#)|subscriber id|insurance id|policy (number|id|#)", None),
    ("payer_name", r"\bpayer\b|insurance (company|carrier|plan name)|health plan name|\bcarrier\b", None),
    ("service_date", r"date of service|service date|\bdos\b", None),
    ("cpt_code", r"\bcpt\b|procedure code|\bhcpcs\b", None),
    ("icd10_code", r"\bicd|diagnosis code", None),
    ("place_of_service", r"place of service|\bpos\b", None),
    ("urgency", r"urgency|priority|review type", None),
    # pharmacy contract (sample_patients.json)
    ("rx_bin", r"\brx ?bin\b|\bbin\b|\bbin number|\biin\b", None),
    ("rx_pcn", r"\b(rx ?)?pcn\b|processor control", None),
    ("rx_group", r"\brx ?group\b|\bgroup( (id|number|#))?\b", None),
    ("insurance_state", r"(insurance|plan|coverage).*\bstate\b|\bstate\b.*(insurance|plan|coverage)", None),
    ("medication_search", r"medication|\bdrug\b|\bndc\b|prescription name", None),
    ("date_of_birth", r"birth|\bdob\b", "patient"),
    ("patient_zip", r"\bzip\b|postal code", "patient"),
    ("first_name", r"(first|given)( name)?\b", "patient"),
    ("last_name", r"(last|sur|family)( ?name)?\b", "patient"),
    ("sex", r"\bsex\b|\bgender\b", None),
]


def norm(s):
    s = (s or "").lower().replace("*", " ").replace(":", " ").replace("\u2019", "'")
    return re.sub(r"\s+", " ", s).strip()


def classify(label, section=""):
    """Return the contract field a control represents, or None."""
    lab, sec = norm(unicodedata.normalize("NFKC", label or "")), norm(section)
    # Reviewed label spelling only. Never normalize patient names or identifiers.
    lab = re.sub(r"\b(member|subscriber|insurance)\s+[ιіı]d\b", r"\1 id", lab)
    if not lab:
        return None
    other_person = bool(re.search(PROVIDER_CTX + r"|subscriber|insured|policy ?holder|cardholder", lab)) or (
        bool(re.search(PROVIDER_CTX, sec)) and "patient" not in lab)
    for field, pattern, cond in FIELD_RULES:
        if not re.search(pattern, lab):
            continue
        if cond == "patient" and other_person:
            continue
        return field
    # one box of a date split into Month / Day / Year, inside a "Date of birth" group
    if date_part(lab) and re.search(r"birth|\bdob\b", sec):
        return "subscriber_dob" if re.search(r"subscriber|insured|policy ?holder|cardholder", sec) else "date_of_birth"
    if date_part(lab) and re.search(r"date of service|service date", sec):
        return "service_date"
    # a bare "State" counts only inside an insurance section (a patient-address state is not in the contract)
    if lab == "state" and re.search(r"insurance|\bplan\b|coverage|payer|benefit", sec):
        return "insurance_state"
    return None


STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}

OPTION_SYNONYMS = {
    "sex": {"M": ["m", "male"], "F": ["f", "female"],
            "X": ["x", "unspecified", "unknown", "other", "non-binary", "nonbinary", "undifferentiated"]},
    "subscriber_relationship": {"self": ["self", "patient", "self (patient)", "patient is the subscriber"],
                                "spouse": ["spouse", "spouse/partner", "husband/wife"],
                                "child": ["child", "dependent child", "son/daughter"],
                                "other": ["other", "other relationship"]},
    "urgency": {"standard": ["standard", "routine", "standard review", "non-urgent"],
                "expedited": ["expedited", "urgent", "expedited review", "urgent/expedited", "expedited (urgent)"]},
}
ALIASES = {"rx_group": "group_number"}   # a "Group" box takes group_number from a medical record


def canonical_field(field, record):
    alias = ALIASES.get(field)
    return alias if alias in record and field not in record else field


def value_for(field, record):
    """The record's value for a portal field (the field itself, else its medical-contract alias)."""
    v = record.get(field)
    if v in (None, "") and field in ALIASES:
        v = record.get(ALIASES[field])
    return v


def search_text(field, value):
    """What to type into a searchable dropdown to find this value."""
    if field == "insurance_state":
        return STATE_NAMES.get(value, value)
    return value


def option_matches(field, value, option_text, option_value=""):
    """Match strength: 3 exact value, 2 exact text/synonym, 1 prefix (code or drug name), 0 no."""
    t, v, want = norm(option_text), norm(option_value), norm(value)
    if not t and not v:
        return 0
    if field == "insurance_state":
        name = norm(STATE_NAMES.get(value, ""))
        if v and v == want:
            return 3
        return 2 if t in (want, name) or (name and t == f"{name} ({want})") else 0
    if field == "sex" and value == "X" and re.match(r"(unknown|other|unspecified|undisclosed|non-?binary)\b", t):
        return 2
    syn = OPTION_SYNONYMS.get(field, {}).get(value)
    if syn is not None:
        if v and v == want:
            return 3
        return 2 if (t in syn or v in syn) else 0
    if v and v == want:
        return 3
    if t == want:
        return 2
    if field == "medication_search":
        # "Simponi Aria" matches "Simponi Aria 50MG/4ML solution" but not "Simponi 50MG..."
        return 1 if re.match(re.escape(want) + r"(\s|$)", t) else 0
    if re.match(re.escape(want) + r"(\s*[-–:]\s|\s+\()", t + " "):
        return 1
    return 0


def date_part(label):
    """'month' / 'day' / 'year' when a control holds one part of a split date, else None."""
    lab = norm(label)
    if re.fullmatch(r"(birth |dob )?(month|mm)( \(mm\))?|.*\b(month|mm)\b.*", lab) and not re.search(r"\bdd\b|\byyyy\b", lab):
        return "month"
    if re.search(r"\b(day|dd)\b", lab) and not re.search(r"\bmm\b|\byyyy\b|birthday", lab):
        return "day"
    if re.search(r"\b(year|yyyy)\b", lab) and not re.search(r"\bmm\b|\bdd\b", lab):
        return "year"
    return None


def format_date(us_value, placeholder="", input_type="text", label=""):
    """Show an MM/DD/YYYY date the way the control expects (presentation only)."""
    d = parse_any_date(us_value)
    if d is None:
        return us_value
    part = date_part(label)
    if part:                                   # one box of a split date: the same digits, in pieces
        return {"month": d.strftime("%m"), "day": d.strftime("%d"), "year": d.strftime("%Y")}[part]
    order = date_order(placeholder + " " + label)
    if (input_type or "").strip().lower() == "date" or order == "ymd":
        return d.isoformat()
    if order == "dmy":
        return d.strftime("%d/%m/%Y")
    return d.strftime("%m/%d/%Y")


def date_order(hint):
    """Use an explicit format marker, never guess from an ambiguous date value."""
    hint = re.sub(r"\s+", "", (hint or "").lower())
    for marker, order in (("dd/mm/yyyy", "dmy"), ("mm/dd/yyyy", "mdy"), ("yyyy-mm-dd", "ymd")):
        if marker in hint:
            return order
    return None


def display_date(value, order=None):
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value or ""):
        return parse_any_date(value)
    if order == "dmy":
        try:
            return datetime.strptime(value, "%d/%m/%Y").date()
        except (ValueError, TypeError):
            return None
    return parse_any_date(value)


DATE_FIELDS = {"date_of_birth", "service_date", "subscriber_dob"}


def states_named(title):
    """US states a form title is restricted to, by full name ("Texas Medicaid ..." -> {"TX"})."""
    t = title or ""
    names = {name.lower(): code for code, name in STATE_NAMES.items()}
    pattern = r"\b(?:" + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)) + r")\b"
    return {names[m.group().lower()] for m in re.finditer(pattern, t, re.I)}


def api_form_titles(body):
    """Form titles, in order, from a JSON response shaped like a forms list ({"forms": [...]}, or under "data")."""
    if isinstance(body, dict) and isinstance(body.get("data"), dict):
        body = body["data"]
    forms = body.get("forms") if isinstance(body, dict) else None
    if not isinstance(forms, list) or not all(isinstance(f, dict) for f in forms):
        return None
    titles = [f.get("title") or f.get("description") or f.get("name") for f in forms]
    return titles if all(isinstance(t, str) for t in titles) else None
