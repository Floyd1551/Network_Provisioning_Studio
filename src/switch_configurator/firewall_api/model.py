from dataclasses import dataclass
import json


def canonical(value): return json.dumps(value, sort_keys=True, separators=(",", ":"))


def name(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 63 or any(ord(c) < 32 for c in value):
        raise ValueError("Names must contain 1–63 printable characters.")
    return value


def validate_rules(rules, zoned=True):
    if not isinstance(rules, list) or not 1 <= len(rules) <= 50: raise ValueError("Stage between 1 and 50 rules.")
    seen = set()
    fields = {"name", "source", "destination", "service", "action"} | ({"from_zone", "to_zone"} if zoned else set())
    for row in rules:
        if not isinstance(row, dict) or set(row) != fields: raise ValueError("Invalid firewall rule schema.")
        for value in row.values(): name(value)
        if row["action"] not in ("allow", "deny"): raise ValueError("Choose allow or deny.")
        if zoned and row["from_zone"] == row["to_zone"]: raise ValueError("Select distinct security zones.")
        if row["name"] in seen: raise ValueError("Duplicate rule name.")
        seen.add(row["name"])


def contains(actual, wanted):
    if isinstance(wanted, dict): return isinstance(actual, dict) and all(k in actual and contains(actual[k], v) for k, v in wanted.items())
    if isinstance(wanted, list): return isinstance(actual, list) and len(actual) == len(wanted) and all(contains(a, b) for a, b in zip(actual, wanted))
    return type(actual) is type(wanted) and actual == wanted


@dataclass
class Snapshot:
    platform: str
    hostname: str
    data: dict
    choices: dict

    @property
    def running(self): return json.dumps(self.data, indent=2)


@dataclass
class Plan:
    snapshot: Snapshot
    rules: list
    operations: list
    expected: list
    warnings: list
