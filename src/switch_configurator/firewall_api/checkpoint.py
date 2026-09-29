"""Check Point Management API: isolated sessions, publish and explicit install target."""
import copy
import time
from .model import Snapshot, Plan, validate_rules, name, canonical


def uid(value): return value.get("uid") if isinstance(value, dict) else value


class CheckPoint:
    id, label = "checkpoint_api", "Check Point Management — access policy"
    zoned = False
    def __init__(self, transport, username, password, layer, package, target, domain=""):
        for value in (username, layer, package, target): name(value)
        if not password: raise ValueError("Enter a Management API password.")
        if domain: name(domain)
        self.transport, self.username, self.password = transport, username, password
        self.layer, self.package, self.target, self.domain = layer, package, target, domain
        self.sid, self.dirty = "", False
        self.log = lambda text: None
        self.poll_interval, self.job_timeout = 2, 300

    def call(self, command, payload=None):
        self.log("POST /web_api/" + command)
        result = self.transport.request("POST", "/web_api/" + command, payload or {})
        if result.get("code") or result.get("errors") or result.get("warnings"):
            raise RuntimeError("Check Point rejected or warned on " + command + "; inspect the management server.")
        return result

    def new_session(self):
        if self.dirty: raise RuntimeError("An unpublished session or unknown outcome requires manual inspection before reconnecting.")
        if self.sid:
            self.call("logout"); self.sid = ""; self.transport.headers.pop("X-chkp-sid", None)
        payload = {"user": self.username, "password": self.password, "session-name": "Network Provisioning Studio", "session-timeout": 600}
        if self.domain: payload["domain"] = self.domain
        response = self.call("login", payload)
        sid = response.get("sid")
        if not isinstance(sid, str) or not sid or any(ord(c) < 32 for c in sid): raise RuntimeError("Management API session was not acknowledged.")
        self.sid = sid; self.transport.headers["X-chkp-sid"] = sid

    def connect(self):
        self.new_session()
        return self.discover()

    def fresh_discover(self):
        # A fresh isolated session sees newly published changes by other admins.
        self.new_session()
        return self.discover()

    def collect(self, command, key="objects", extra=None):
        rows, total = [], None
        while total is None or len(rows) < total:
            response = self.call(command, {"limit": 100, "offset": len(rows), "details-level": "full", **(extra or {})})
            batch, count = response.get(key), response.get("total")
            if not isinstance(batch, list) or type(count) is not int or not 0 <= count <= 10000:
                raise ValueError("Incomplete or oversized Management API collection.")
            if total is not None and total != count: raise RuntimeError("Collection changed during pagination; rediscover.")
            total = count
            if not batch and len(rows) < total: raise RuntimeError("Truncated Management API collection.")
            if any(not isinstance(r, dict) or not r.get("uid") for r in batch): raise ValueError("Unrecognized Management API object.")
            rows.extend(batch)
            if len(rows) > total or len({r["uid"] for r in rows}) != len(rows): raise ValueError("Duplicate or inconsistent API pagination.")
        return rows

    def discover(self):
        package = self.call("show-package", {"name": self.package, "details-level": "full"})
        layers = package.get("access-layers", [])
        if package.get("access") is not True or len(layers) != 1 or layers[0].get("name") != self.layer:
            raise ValueError("Select an access-enabled policy package with exactly the specified single layer.")
        gateway = self.call("show-simple-gateway", {"name": self.target, "details-level": "full"})
        if gateway.get("type") != "simple-gateway" or not gateway.get("uid"):
            raise ValueError("This adapter requires an existing standalone simple gateway target; clusters are not supported.")
        objects = self.collect("show-hosts") + self.collect("show-networks")
        services = self.collect("show-services-tcp") + self.collect("show-services-udp")
        rules = self.collect("show-access-rulebase", "rulebase", {"name": self.layer, "use-object-dictionary": False})
        if any(r.get("type") != "access-rule" or r.get("inline-layer") for r in rules):
            raise ValueError("Sections or inline layers require a dedicated policy plan.")
        for collection in (objects, services):
            if len({r.get("name") for r in collection}) != len(collection): raise ValueError("Ambiguous object names in management inventory.")
        data = {"package": package, "gateway": gateway, "objects": objects, "services": services, "rules": rules,
                "context": {"layer": self.layer, "package": self.package, "target": self.target, "domain": self.domain}}
        choices = {"addresses": sorted(r["name"] for r in objects), "services": sorted(r["name"] for r in services)}
        return Snapshot(self.id, getattr(self.transport, "origin", "simulation") + " / " + self.package + " → " + self.target, data, choices)

    def plan(self, rules, snapshot):
        rules = copy.deepcopy(rules); validate_rules(rules, zoned=False)
        context = {"layer": self.layer, "package": self.package, "target": self.target, "domain": self.domain}
        if snapshot.platform != self.id or snapshot.data["context"] != context: raise ValueError("Wrong policy package, domain or target context.")
        objects = {r["name"]: r["uid"] for r in snapshot.data["objects"]}
        services = {r["name"]: r["uid"] for r in snapshot.data["services"]}
        existing = {r.get("name") for r in snapshot.data["rules"]}
        operations, expected = [], []
        for row in rules:
            if row["name"] in existing: raise ValueError("Rule name already exists.")
            if row["source"] not in objects or row["destination"] not in objects or row["service"] not in services: raise ValueError("Select discovered network/service objects.")
            action = "Accept" if row["action"] == "allow" else "Drop"
            body = {"layer": self.layer, "position": "bottom", "name": row["name"], "enabled": True,
                    "source": [objects[row["source"]]], "destination": [objects[row["destination"]]],
                    "service": [services[row["service"]]], "action": action,
                    "source-negate": False, "destination-negate": False, "service-negate": False,
                    "track": {"type": "Log"}, "install-on": [snapshot.data["gateway"]["uid"]],
                    "ignore-warnings": False, "ignore-errors": False}
            operations.append({"method": "POST", "path": "/web_api/add-access-rule", "body": body})
            expected.append({k: copy.deepcopy(v) for k, v in body.items() if k not in ("layer", "position", "ignore-warnings", "ignore-errors")})
        operations += [{"method": "POST", "path": "/web_api/publish", "body": {}},
                       {"method": "POST", "path": "/web_api/install-policy", "body": {"policy-package": self.package, "targets": [self.target], "access": True, "threat-prevention": False, "desktop-security": False, "qos": False, "ignore-warnings": False}}]
        return Plan(snapshot, rules, operations, expected, ["Experimental Management API adapter; hardware-untested. Connect to the management server, not Gaia SSH.",
            "Rules append at the bottom; an existing cleanup/drop rule can shadow them. No existing rule is moved.",
            "Publishing is followed by Access Control policy installation to the named standalone gateway. This installs the entire published package, including previously published changes by other administrators.",
            "Only one flat access layer and existing host/network/TCP/UDP objects are supported. No NAT, VPN or threat-prevention policy is changed.",
            "Backups cover the selected management scopes, not a full server restore. Failed sessions are retained for manual inspection."])

    def wait_task(self, response, operation):
        task_id = response.get("task-id")
        if not isinstance(task_id, str) or not task_id: raise RuntimeError(operation + " task was not acknowledged.")
        self.log(operation + " task " + task_id)
        deadline = time.monotonic() + self.job_timeout
        while time.monotonic() < deadline:
            result = self.call("show-task", {"task-id": task_id, "details-level": "full"})
            tasks = result.get("tasks")
            if not isinstance(tasks, list) or len(tasks) != 1 or tasks[0].get("task-id") != task_id: raise RuntimeError("Task identity not confirmed.")
            status = tasks[0].get("status")
            if status == "succeeded": return
            if status != "in progress": raise RuntimeError(operation + " did not succeed; inspect task " + task_id)
            time.sleep(self.poll_interval)
        raise RuntimeError(operation + " timed out; outcome unknown. Inspect task " + task_id)

    def deploy(self, plan):
        if self.dirty: raise RuntimeError("Inspect prior session changes before retrying.")
        # APIService has just opened a fresh session and compared its snapshot.
        for operation in plan.operations[:-2]:
            self.dirty = True
            result = self.call("add-access-rule", operation["body"])
            if not result.get("uid"): raise RuntimeError("New rule identity was not acknowledged.")
        self.verify(plan, self.discover())
        self.wait_task(self.call("publish"), "Publish")
        self.dirty = False
        self.wait_task(self.call("install-policy", plan.operations[-1]["body"]), "Policy installation")

    def verify(self, plan, snapshot):
        for wanted in plan.expected:
            matches = [r for r in snapshot.data["rules"] if r.get("name") == wanted["name"]]
            if len(matches) != 1: raise RuntimeError("Access rule identity was not confirmed.")
            observed = matches[0]
            for field in ("source", "destination", "service", "install-on"):
                if [uid(v) for v in observed.get(field, [])] != wanted[field]: raise RuntimeError("Rule references do not match reviewed intent.")
            action = observed.get("action", {})
            if not isinstance(action, dict) or action.get("name") != wanted["action"]: raise RuntimeError("Rule action was not confirmed.")
            for field in ("enabled", "source-negate", "destination-negate", "service-negate"):
                if observed.get(field) is not wanted[field]: raise RuntimeError("Rule flags were not confirmed.")
            track = observed.get("track", {}).get("type", {})
            if (track.get("name") if isinstance(track, dict) else track) != "Log": raise RuntimeError("Rule logging was not confirmed.")

    def close(self):
        try:
            if self.sid and not self.dirty: self.call("logout")
        finally:
            self.sid = ""; self.password = ""; self.transport.close()
