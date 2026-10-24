"""Fast unit tests (no browser): validator, label mapping, option matching, popup policy.

    python -m pytest tests/test_units.py -q
"""
import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from agent import fields as F  # noqa: E402
from agent import interrupts  # noqa: E402
from agent.actionlog import mask  # noqa: E402
from agent.errors import Escalate  # noqa: E402
from agent.validate import portal_fields, validate_record  # noqa: E402

TODAY = date(2026, 11, 2)
SAMPLES = {r["case_id"]: r for r in json.loads((ROOT / "sample_patients.json").read_text())}
GOOD = SAMPLES["P001_trace_exact"]


def issues(**over):
    rec = dict(GOOD)
    for k, v in over.items():
        if v is None:
            rec.pop(k, None)
        else:
            rec[k] = v
    return [i.field for i in validate_record(rec, TODAY)[1]]


# ---------------------------------------------------------------- her sample file
@pytest.mark.parametrize("case,expected", [
    ("P001_trace_exact", []),
    ("P002_clean_male_other_bin", []),
    ("P003_clean_hyphen_name", []),
    ("P004_bad_dob_and_zip", ["date_of_birth", "patient_zip"]),
    ("P005_missing_sex_bad_bin", ["sex", "rx_bin"]),
])
def test_sample_file(case, expected):
    assert [i.field for i in validate_record(SAMPLES[case], TODAY)[1]] == expected


def test_metadata_and_empty_optionals_never_reach_the_portal():
    sent = portal_fields(GOOD)
    assert "case_id" not in sent and "notes" not in sent and "rx_group" not in sent
    assert sent["rx_pcn"] == "NVT"


def test_values_are_never_changed():
    rec, _ = validate_record(dict(GOOD), TODAY)
    assert all(rec[k] == GOOD[k] for k in rec)


def test_captured_short_bin_is_used_exactly_without_padding():
    rec, iss = validate_record(SAMPLES["P002_clean_male_other_bin"], TODAY)
    assert iss == [] and rec["rx_bin"] == "22022"
    assert issues(rx_bin="61060") == ["rx_bin"]


# ---------------------------------------------------------------- each rule
@pytest.mark.parametrize("over,field", [
    ({"medication_search": None}, "medication_search"),
    ({"medication_search": "S"}, "medication_search"),
    ({"medication_search": "123456789"}, "medication_search"),
    ({"first_name": "T3st"}, "first_name"),
    ({"last_name": " Test"}, "last_name"),
    ({"sex": "Female"}, "sex"),
    ({"date_of_birth": "1986-11-13"}, "date_of_birth"),
    ({"date_of_birth": "13/11/1986"}, "date_of_birth"),
    ({"date_of_birth": "11/03/2026"}, "date_of_birth"),
    ({"date_of_birth": "11/01/1905"}, "date_of_birth"),
    ({"patient_zip": "7405"}, "patient_zip"),
    ({"insurance_state": "XX"}, "insurance_state"),
    ({"rx_bin": "6106020"}, "rx_bin"),
    ({"rx_bin": 610602}, "rx_bin"),
    ({"rx_pcn": "N V T"}, "rx_pcn"),
    ({"rx_group": "G" * 16}, "rx_group"),
])
def test_each_rule(over, field):
    assert issues(**over)[0] == field


@pytest.mark.parametrize("over", [
    {"date_of_birth": "11/02/1906"},           # exactly 120 today
    {"date_of_birth": "11/02/2026"},           # born today
    {"first_name": "Anne-Marie", "last_name": "O'Brien"}, {"first_name": "José"},
    {"rx_pcn": ""}, {"rx_pcn": None}, {"rx_group": "GRP-4421"}, {"insurance_state": "DC"},
    {"medication_search": "57894035001"}, {"medication_search": "57894-0350-01"},
])
def test_boundaries_accepted(over):
    assert issues(**over) == []


# ---------------------------------------------------------------- label mapping
@pytest.mark.parametrize("label,section,field", [
    ("Search for medication name or NDC number", "Medication", "medication_search"),
    ("Drug name", "", "medication_search"),
    ("First Name*", "Patient Information", "first_name"),
    ("Patient Last Name", "", "last_name"),
    ("Date of Birth*", "", "date_of_birth"), ("DOB", "", "date_of_birth"),
    ("Gender*", "", "sex"), ("Sex", "", "sex"),
    ("Patient Zip Code*", "", "patient_zip"), ("Postal code", "", "patient_zip"),
    ("Patient Insurance State*", "", "insurance_state"), ("State of insurance plan", "", "insurance_state"),
    ("RxBIN", "", "rx_bin"), ("BIN", "", "rx_bin"),
    ("RxPCN Number", "", "rx_pcn"), ("PCN", "", "rx_pcn"),
    ("RxGroup", "", "rx_group"), ("Group ID", "", "rx_group"),
    ("IIN", "", "rx_bin"), ("State", "Insurance Information", "insurance_state"),
])
def test_label_mapping(label, section, field):
    assert F.classify(label, section) == field


@pytest.mark.parametrize("label,section", [
    ("Diagnosis", ""), ("Plan or PBM Name", ""), ("Prescriber First Name", ""),
    ("First name", "Prescriber Information"), ("State", "Patient Address"), ("Notes", ""),
])
def test_labels_that_must_not_map(label, section):
    assert F.classify(label, section) is None


def test_option_matching():
    assert F.option_matches("insurance_state", "OK", "Oklahoma", "OK") == 3
    assert F.option_matches("insurance_state", "OK", "Oklahoma") == 2
    assert F.option_matches("insurance_state", "OK", "Oregon") == 0
    assert F.option_matches("sex", "F", "Female", "F") == 3
    assert F.option_matches("sex", "X", "Unspecified") == 2
    assert F.option_matches("medication_search", "Simponi Aria", "Simponi Aria 50MG/4ML solution") == 1
    assert F.option_matches("medication_search", "Simponi", "Simponi Aria 50MG/4ML solution") == 1
    assert F.option_matches("medication_search", "Simponi Aria", "Simponi 50MG/0.5ML auto-injector") == 0
    assert F.search_text("insurance_state", "OK") == "Oklahoma"


def test_date_formatting_is_presentation_only():
    assert F.format_date("11/13/1986", "MM/DD/YYYY", "text") == "11/13/1986"
    assert F.format_date("11/13/1986", "", "date") == "1986-11-13"
    assert F.format_date("11/13/1986", "YYYY-MM-DD", "text") == "1986-11-13"
    assert F.format_date("11/13/1986", "DD/MM/YYYY", "text") == "13/11/1986"


# ---------------------------------------------------------------- popup policy
def cand(kind, title, text, buttons, label=""):
    return {"i": 0, "kind": kind, "title": title, "label": label, "text": text,
            "buttons": [{"j": j, "text": b, "aria": ""} for j, b in enumerate(buttons)]}


def test_benign_popups_pick_safe_button():
    assert interrupts.classify(cand("dialog", "How are we doing?", "survey", ["No thanks", "Take survey"])) == ("survey", 0)
    assert interrupts.classify(cand("dialog", "Your session is about to expire", "", ["Sign out", "Stay signed in"])) == ("session_keepalive", 1)
    assert interrupts.classify(cand("dialog", "What's new in CoverRx", "", ["×", "Got it"])) == ("announcement", 1)
    assert interrupts.classify(cand("overlay", "", "Important message: forms changed", ["×"], "Important message"))[0] == "announcement"
    assert interrupts.classify(cand("dialog", "Support FAQs & Resources", "faqs", ["Close"]))[0] == "chat_widget"


def test_duplicate_and_unknown_dialogs_escalate():
    with pytest.raises(Escalate) as e:
        interrupts.classify(cand("dialog", "Possible existing patient",
                                 "This patient may already exist in your Patient Address Book",
                                 ["Use existing patient", "Create new patient anyway"]))
    assert e.value.field == "patient"
    with pytest.raises(Escalate):
        interrupts.classify(cand("dialog", "Attestation required", "Confirm medical necessity", ["I attest"]))


def test_unknown_fixed_elements_are_ignored():
    assert interrupts.classify(cand("overlay", "", "Requests Cases Account Logout", ["Logout"])) is None


def test_masking():
    assert mask("first_name", "Anne-Marie") == "A***"
    assert mask("date_of_birth", "11/13/1986") == "**/**/1986"
    assert mask("rx_bin", "610602") == "610602"


# ---------------------------------------------------------------- added for the second (mock B) portal
@pytest.mark.parametrize("label,section,field", [
    ("Month (MM)", "Date of birth *", "date_of_birth"), ("Day (DD)", "Date of birth", "date_of_birth"),
    ("Year (YYYY)", "DOB", "date_of_birth"), ("Legal first name", "", "first_name"),
    ("Home ZIP", "", "patient_zip"), ("Plan state", "", "insurance_state"),
    ("Processor control number", "", "rx_pcn"), ("Drug to authorize", "", "medication_search"),
])
def test_mock_b_labels(label, section, field):
    assert F.classify(label, section) == field


def test_month_day_year_outside_a_birth_group_do_not_map():
    assert F.classify("Month (MM)", "Card expiry") is None
    assert F.classify("Year", "") is None


def test_split_date_is_the_same_digits_in_pieces():
    assert [F.format_date("04/02/1975", "", "text", l) for l in ("Month (MM)", "Day (DD)", "Year (YYYY)")] == ["04", "02", "1975"]
    assert F.format_date("04/02/1975", "MM/DD/YYYY", "text", "Date of birth (MM/DD/YYYY)") == "04/02/1975"


def test_sex_x_matches_unknown_or_other_but_f_does_not():
    assert F.option_matches("sex", "X", "Unknown / other") == 2
    assert F.option_matches("sex", "F", "Unknown / other") == 0


# ---------------------------------------------------------------- brief Section 4 (medical) contract
from agent.validate import contract_for, npi_ok  # noqa: E402

MED = {"first_name": "Maria", "last_name": "Gonzalez", "date_of_birth": "1984-03-22", "sex": "F",
       "payer_name": "Aetna", "member_id": "W123456789", "group_number": "GRP-44821",
       "subscriber_relationship": "self", "provider_npi": "1003000126", "service_date": "2026-11-10",
       "cpt_code": "97110", "icd10_code": "M54.50", "place_of_service": "11", "urgency": "standard"}


def med_issues(**over):
    rec = dict(MED)
    for k, v in over.items():
        if v is None:
            rec.pop(k, None)
        else:
            rec[k] = v
    return [i.field for i in validate_record(rec, TODAY)[1]]


def test_contract_detection():
    assert contract_for(GOOD) == ["pharmacy"]
    assert contract_for(MED) == ["medical"]


def test_brief_example_record_is_valid():
    assert med_issues() == []


def test_npi_check_digit():
    assert npi_ok("1003000126") and npi_ok("1234567893")
    assert not npi_ok("1003000127")


@pytest.mark.parametrize("over,field", [
    ({"member_id": "W12345678"}, "member_id"), ({"member_id": None}, "member_id"),
    ({"group_number": "GRP 44821"}, "group_number"),
    ({"subscriber_relationship": "parent"}, "subscriber_relationship"),
    ({"subscriber_relationship": "spouse"}, "subscriber_name"),
    ({"provider_npi": "100300012"}, "provider_npi"), ({"provider_npi": "1003000127"}, "provider_npi"),
    ({"service_date": "2026-11-01"}, "service_date"), ({"service_date": "2027-05-02"}, "service_date"),
    ({"service_date": "2026-02-30"}, "service_date"),
    ({"cpt_code": "9711A"}, "cpt_code"), ({"icd10_code": "M5"}, "icd10_code"),
    ({"icd10_code": "M54.50123"}, "icd10_code"), ({"place_of_service": "1"}, "place_of_service"),
    ({"urgency": "Expedited"}, "urgency"), ({"date_of_birth": "1984-02-30"}, "date_of_birth"),
    ({"date_of_birth": "1880-01-01"}, "date_of_birth"), ({"sex": "female"}, "sex"),
])
def test_medical_rules(over, field):
    assert field in med_issues(**over)


def test_service_date_window_edges_and_subscriber_ok():
    assert med_issues(service_date="2026-11-02") == []          # today
    assert med_issues(service_date="2027-05-01") == []          # 180 days ahead
    assert med_issues(subscriber_relationship="child", subscriber_first_name="Ana",
                      subscriber_last_name="Gonzalez", subscriber_dob="1980-01-01") == []


@pytest.mark.parametrize("label,field", [
    ("Provider NPI", "provider_npi"), ("Member ID", "member_id"), ("Payer", "payer_name"),
    ("Patient relationship to subscriber", "subscriber_relationship"), ("Subscriber first name", "subscriber_first_name"),
    ("Subscriber date of birth", "subscriber_dob"), ("Date of service", "service_date"),
    ("CPT code", "cpt_code"), ("ICD-10 diagnosis code", "icd10_code"), ("Place of service", "place_of_service"),
    ("Urgency", "urgency"), ("Group number", "rx_group"),
])
def test_medical_labels(label, field):
    assert F.classify(label, "") == field


def test_medical_values_reach_the_right_boxes():
    assert F.value_for("rx_group", MED) == "GRP-44821"
    assert F.format_date("1984-03-22", "MM/DD/YYYY") == "03/22/1984"
    assert F.format_date("1984-03-22", "", "date") == "1984-03-22"
    assert F.option_matches("subscriber_relationship", "self", "Self") >= 2
    assert F.option_matches("urgency", "expedited", "Urgent") == 2
    assert F.option_matches("place_of_service", "11", "11 - Office") == 1


@pytest.mark.parametrize("text", ["Show 8 More", "Show more forms (8)", "View all", "Load more"])
def test_show_more_labels(text):
    from agent.runner import MORE_RE
    assert MORE_RE.search(text)


@pytest.mark.parametrize("text", ["Start Request", "Start PA"])
def test_start_labels_from_trace(text):
    from agent.runner import START_RE
    assert START_RE.search(text)


def _dialog(text):
    return {"kind": "dialog", "title": "EXISTING PA INFORMATION", "label": "", "text": text,
            "buttons": [{"j": 0, "text": "Cancel", "aria": ""}, {"j": 1, "text": "Continue With New PA", "aria": ""}]}


def test_existing_pa_active_escalates_and_marks_nothing_created():
    with pytest.raises(Escalate) as e:
        interrupts.classify(_dialog("Key: B7QK2M4X  Status: Sent to Plan  Created: 08/14/2026"))
    assert e.value.field == "patient" and "sent to plan" in e.value.problem and e.value.nothing_created


def test_existing_pa_expired_continues_with_new_pa():
    assert interrupts.classify(_dialog("Key: B7QK2M4X  Status: Expired  Created: 08/14/2026")) == ("existing_pa_expired", 1)


@pytest.mark.parametrize("text", ["No, Proceed to PA Forms", "No, continue to prior authorization forms"])
def test_eligibility_offer_is_skippable(text):
    from agent.runner import SKIP_RE
    assert SKIP_RE.search(text)


def test_continue_prior_auth_is_a_continue_button():
    from agent.runner import CONTINUE_RE
    assert CONTINUE_RE.search("Continue Prior Auth")


@pytest.mark.parametrize("title,states", [
    ("Navitus Health Solutions Texas Medicaid Standard Prior Authorization Request Form", {"TX"}),
    ("Colorado Access Injectable Medication Form", {"CO"}),
    ("LA Care Health Plan California Commercial and Exchange Prescription Drug Prior Authorization", {"CA"}),
    ("Navitus Health Solutions Commercial Exception to Coverage Request Form", set()),
])
def test_states_named_in_form_titles(title, states):
    assert F.states_named(title) == states


def test_api_form_titles_shapes():
    assert F.api_form_titles({"forms": [{"title": "A"}, {"title": "B"}]}) == ["A", "B"]
    assert F.api_form_titles({"data": {"forms": [{"name": "A"}]}}) == ["A"]
    assert F.api_form_titles({"forms": []}) == []
    assert F.api_form_titles({"drugs": [{"name": "x"}]}) is None


def test_api_form_titles_prefers_description_to_internal_name():
    assert F.api_form_titles({"forms": [{"name": "epacc123", "description": "Oklahoma Form"}]}) == ["Oklahoma Form"]


def test_state_names_do_not_match_inside_longer_state_names():
    assert F.states_named("West Virginia Medicaid") == {"WV"}
    assert F.states_named("Virginia and West Virginia Medicaid") == {"VA", "WV"}
