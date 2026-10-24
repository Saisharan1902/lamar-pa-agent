"""Reference data for the synthetic Portal A.

FORMS comes straight from the forms-API response captured in the trace
(ids, titles, BIN and PCN lists). The trace includes short BIN representations such as "22022".
The portal preserves input values and compares lookup representations numerically.
"""
import json
from pathlib import Path

FORMS = json.loads((Path(__file__).parent / "forms_from_trace.json").read_text())

# id, display name, NDC. "Simponi Aria" (from the trace) has one match; Humira, Enbrel
# and Simponi have several, so a bare brand search is ambiguous.
DRUGS = [
    ("180335", "Simponi Aria 50MG/4ML solution", "57894035001"),
    ("180340", "Simponi 50MG/0.5ML solution auto-injector", "57894007002"),
    ("180341", "Simponi 100MG/ML solution prefilled syringe", "57894007101"),
    ("170100", "Humira Pen 40MG/0.4ML pen-injector kit", "00074055402"),
    ("170101", "Humira 40MG/0.8ML prefilled syringe kit", "00074379902"),
    ("170102", "Humira Pen-CD/UC/HS Starter 80MG/0.8ML kit", "00074012403"),
    ("160200", "Enbrel 50MG/ML solution prefilled syringe", "58406043504"),
    ("160201", "Enbrel SureClick 50MG/ML solution auto-injector", "58406044504"),
    ("190300", "Dupixent 300MG/2ML solution prefilled syringe", "00024591401"),
    ("200400", "Ozempic 2MG/3ML solution pen-injector", "00169413212"),
]

STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}

# Approximate USPS ZIP3 prefix ranges -> state, used to pre-fill the patient's state
# from the ZIP code (the trace shows the state row appear, already filled, after the ZIP).
ZIP3_RANGES = [
    (10, 27, "MA"), (28, 29, "RI"), (30, 38, "NH"), (39, 49, "ME"), (50, 59, "VT"), (60, 69, "CT"),
    (70, 89, "NJ"), (100, 149, "NY"), (150, 196, "PA"), (197, 199, "DE"), (200, 205, "DC"),
    (206, 219, "MD"), (220, 246, "VA"), (247, 268, "WV"), (270, 289, "NC"), (290, 299, "SC"),
    (300, 319, "GA"), (320, 349, "FL"), (350, 369, "AL"), (370, 385, "TN"), (386, 397, "MS"),
    (398, 399, "GA"), (400, 427, "KY"), (430, 459, "OH"), (460, 479, "IN"), (480, 499, "MI"),
    (500, 528, "IA"), (530, 549, "WI"), (550, 567, "MN"), (570, 577, "SD"), (580, 588, "ND"),
    (590, 599, "MT"), (600, 629, "IL"), (630, 658, "MO"), (660, 679, "KS"), (680, 693, "NE"),
    (700, 714, "LA"), (716, 729, "AR"), (730, 749, "OK"), (750, 799, "TX"), (800, 816, "CO"),
    (820, 831, "WY"), (832, 838, "ID"), (840, 847, "UT"), (850, 865, "AZ"), (870, 884, "NM"),
    (885, 885, "TX"), (889, 898, "NV"), (900, 961, "CA"), (967, 968, "HI"), (970, 979, "OR"),
    (980, 994, "WA"), (995, 999, "AK"),
]


def state_for_zip(zip5):
    if not (zip5 or "").isdigit() or len(zip5) != 5:
        return None
    z3 = int(zip5[:3])
    return next((s for lo, hi, s in ZIP3_RANGES if lo <= z3 <= hi), None)
