"""Diffable action log.

Entries have no timestamps or durations, so two runs of the same record against
the same portal produce byte-identical logs. Patient identifiers are masked.
"""
import json

NAME_FIELDS = {"first_name", "last_name", "subscriber_first_name", "subscriber_last_name", "subscriber_name"}
DOB_FIELDS = {"date_of_birth", "subscriber_dob"}


def mask(field, value):
    if value is None or value == "":
        return value
    v = str(value)
    if field in NAME_FIELDS:
        return v[0] + "***"
    if field in DOB_FIELDS:                      # keep the year only, in either date format
        if "/" in v and len(v) >= 4:
            return "**/**/" + v[-4:]
        return v[:4] + "-**-**" if len(v) >= 4 else "****"
    if field == "member_id":
        return "*" * max(len(v) - 4, 0) + v[-4:]
    return v


class ActionLog:
    def __init__(self):
        self.entries = []

    def add(self, action, **detail):
        self.entries.append({"seq": len(self.entries) + 1, "action": action, **detail})

    def write(self, path):
        with open(path, "w", encoding="utf-8") as f:
            for e in self.entries:
                f.write(json.dumps(e, sort_keys=True, ensure_ascii=False) + "\n")
