import base64
import copy
import re
from .model import Snapshot, Plan, validate_rules, canonical, contains


class SonicOS:
    id = "sonicos_api"
    label = "SonicWall SonicOS 7 — IPv4 access rules"
    scopes = {"zones": "/zones", "addresses": "/address-objects/ipv4", "services": "/service-objects", "rules": "/access-rules/ipv4"}

    def __init__(self, transport, username, password):
        self.transport, self.username, self.password = transport, username, password
        self.clean, self.dirty = False, False
        self.log = lambda text: None

    def call(self, method, path, payload=None, require_success=False):
        self.log(method + " /api/sonicos" + path)
        data = self.transport.request(method, "/api/sonicos" + path, payload)
        status = data.get("status", {})
        if status.get("success") is False or (require_success and status.get("success") is not True):
            raise RuntimeError("SonicOS did not confirm API success for " + path + ". Inspect the device for details.")
        if any(item.get("level") in ("error", "warning") for item in status.get("info", [])):
            raise RuntimeError("SonicOS returned an advisory for " + path + "; inspect it before continuing.")
        return {k: v for k, v in data.items() if k != "status"}

    def connect(self):
        if not self.username or not self.password: raise ValueError("Enter API username and password.")
        value = base64.b64encode((self.username + ":" + self.password).encode()).decode()
        self.transport.headers["Authorization"] = "Basic " + value
        self.password = ""
        try:
            self.call("POST", "/auth", require_success=True)
            self.call("POST", "/start-management", require_success=True)
            self.assert_clean()
            self.clean = True
            return self.discover()
        except Exception:
            self.close()
            raise

    def assert_clean(self):
        if self.call("GET", "/config/pending"):
            raise RuntimeError("Existing SonicOS pending configuration. Nothing will be staged or committed.")

    @staticmethod
    def collection(data, key):
        rows = data.get(key)
        if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
            raise ValueError("Incomplete SonicOS " + key + " discovery.")
        return rows

    def discover(self):
        version = self.call("GET", "/version")
        if not re.search(r"(?:^|\s)7\.", version.get("firmware_version", "")):
            raise ValueError("This adapter requires SonicOS 7; other versions are not qualified.")
        data = {key: self.call("GET", path) for key, path in self.scopes.items()}
        zones = self.collection(data["zones"], "zones")
        addresses = self.collection(data["addresses"], "address_objects")
        services = self.collection(data["services"], "service_objects")
        self.collection(data["rules"], "access_rules")
        choices = {"zones": sorted(r["name"] for r in zones if isinstance(r.get("name"), str)),
                   "addresses": sorted(r["ipv4"]["name"] for r in addresses if isinstance(r.get("ipv4", {}).get("name"), str)),
                   "services": sorted(r["name"] for r in services if isinstance(r.get("name"), str))}
        data["identity"] = {key: version.get(key, "") for key in ("firmware_version", "model", "serial_number")}
        target = getattr(self.transport, "origin", "simulation")
        return Snapshot(self.id, version.get("model", "SonicOS") + " @ " + target, data, choices)

    def plan(self, rules, snapshot):
        rules = copy.deepcopy(rules); validate_rules(rules)
        if snapshot.platform != self.id: raise ValueError("Wrong platform snapshot.")
        existing = {r.get("ipv4", {}).get("name") for r in snapshot.data["rules"]["access_rules"]}
        expected = []
        for row in rules:
            if row["name"] in existing: raise ValueError("Rule name already exists; replacement is not supported.")
            for key in ("from_zone", "to_zone"):
                if row[key] not in snapshot.choices["zones"]: raise ValueError("Select an existing zone.")
            for key in ("source", "destination"):
                if row[key] not in snapshot.choices["addresses"]: raise ValueError("Select an existing IPv4 address object.")
            if row["service"] not in snapshot.choices["services"]: raise ValueError("Select an existing service object.")
            expected.append({"ipv4": {"name": row["name"], "enable": True,
                "from": row["from_zone"], "to": row["to_zone"], "action": row["action"],
                "source": {"address": {"name": row["source"]}, "port": {"any": True}},
                "destination": {"address": {"name": row["destination"]}},
                "service": {"name": row["service"]}, "schedule": {"always_on": True},
                "logging": True, "management": False, "reflexive": False}})
        payload = copy.deepcopy(expected)
        for item in payload: item["ipv4"]["priority"] = {"end": True}
        operations = [{"method": "POST", "path": "/api/sonicos/access-rules/ipv4", "body": {"access_rules": payload}},
                      {"method": "POST", "path": "/api/sonicos/config/pending", "body": None}]
        warnings = ["Experimental SonicOS 7 API adapter; no physical qualification.",
                    "Adds rules at the end using existing address/service objects. Earlier rules can shadow these rules.",
                    "Only selected API configuration scopes are backed up; this is not a full appliance restore image.",
                    "No NAT, interface changes, security profiles or VPN are configured. Configuration readback does not verify traffic."]
        return Plan(snapshot, rules, operations, expected, warnings)

    def deploy(self, plan):
        self.assert_clean()
        self.dirty = True  # A timeout may occur after the server stages the request.
        operation = plan.operations[0]
        self.call("POST", "/access-rules/ipv4", operation["body"], require_success=True)
        pending = self.call("GET", "/config/pending")
        if set(pending) != {"access_rules"}: raise RuntimeError("Unexpected pending configuration; commit refused.")
        rows = pending["access_rules"]
        if not isinstance(rows, list) or len(rows) != len(plan.expected): raise RuntimeError("Pending rule count changed; commit refused.")
        for wanted in plan.expected:
            matches = [r for r in rows if r.get("ipv4", {}).get("name") == wanted["ipv4"]["name"]]
            if len(matches) != 1 or matches[0].get("pending") != "ADD" or not contains(matches[0], wanted):
                raise RuntimeError("Pending changes differ from this plan; commit refused.")
        self.call("POST", "/config/pending", require_success=True)
        self.assert_clean()
        self.dirty = False

    def verify(self, plan, snapshot):
        rows = snapshot.data["rules"]["access_rules"]
        for wanted in plan.expected:
            matches = [r for r in rows if r.get("ipv4", {}).get("name") == wanted["ipv4"]["name"]]
            if len(matches) != 1 or not contains(matches[0], wanted): raise RuntimeError("Access rule readback did not confirm " + wanted["ipv4"]["name"])

    def close(self):
        try:
            if self.clean and not self.dirty:
                # Never log out a session with newly observed pending changes:
                # SonicOS logout can discard those changes.
                try: self.assert_clean()
                except Exception: self.log("Pending state could not be confirmed clean; remote logout skipped.")
                else: self.call("DELETE", "/auth", require_success=True)
        finally:
            self.transport.close(); self.password = ""; self.clean = False
