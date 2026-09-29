"""PAN-OS local-vsys rules using candidate locks and acknowledged commit jobs."""
import copy
import re
import time
from xml.etree import ElementTree as ET
from .model import Snapshot, Plan, validate_rules, name


def xml(element): return ET.tostring(element, encoding="unicode")


def normalized(element):
    return ET.canonicalize(xml(element), strip_text=True, exclude_attrs={"dirtyId", "admin", "time"})


def leaves(element, prefix=""):
    result = {}
    for child in element:
        key = prefix + child.tag
        if len(child):
            for path, values in leaves(child, key + "/").items(): result.setdefault(path, []).extend(values)
        else: result.setdefault(key, []).append((child.text or "").strip())
    return result


class PANOS:
    id = "panos_api"
    label = "Palo Alto PAN-OS — local security rules"
    def __init__(self, transport, username, api_key, vsys="vsys1"):
        if not re.fullmatch(r"vsys[1-9][0-9]*", vsys): raise ValueError("Use a vsys identifier such as vsys1.")
        name(username)
        if not api_key or any(ord(c) < 32 for c in api_key): raise ValueError("Enter a PAN-OS API key.")
        self.transport, self.username, self.vsys = transport, username, vsys
        self.transport.headers["X-PAN-KEY"] = api_key
        self.log = lambda text: None
        self.locks = []
        self.dirty = False
        self.poll_interval, self.job_timeout = 2, 300
        self.base = "/config/devices/entry[@name='localhost.localdomain']/vsys/entry[@name='" + vsys + "']"

    def call(self, form):
        self.log("POST /api/ • " + form["type"] + " " + form.get("action", ""))
        response = self.transport.request("POST", "/api/", form=form, xml=True)
        if response.tag != "response" or response.get("status") != "success": raise RuntimeError("PAN-OS rejected the API request; inspect the device for details.")
        return response

    def op(self, command): return self.call({"type": "op", "cmd": command})

    def config(self, candidate=False):
        result = self.call({"type": "config", "action": "get" if candidate else "show", "xpath": "/config"})
        config = result.find("./result/config")
        if config is None: raise ValueError("Complete PAN-OS configuration was not returned.")
        return config

    def connect(self): return self.discover()

    def discover(self):
        identity = self.op("<show><system><info/></system></show>")
        version = identity.findtext("./result/system/sw-version", "")
        model = identity.findtext("./result/system/model", "")
        if not re.match(r"(?:10|11|12)\.", version) or not model.upper().startswith("PA-"):
            raise ValueError("Select a PAN-OS 10–12 firewall; Panorama is not supported.")
        active = self.config()
        if any((n.text or "").strip() for n in active.findall(".//panorama-server") + active.findall(".//panorama-server-2")):
            raise ValueError("Panorama-managed configuration is outside this local firewall adapter.")
        if active.findtext(".//high-availability/enabled") == "yes": raise ValueError("HA firewall deployment requires a dedicated workflow.")
        vsys = active.find("./devices/entry[@name='localhost.localdomain']/vsys/entry[@name='" + self.vsys + "']")
        if vsys is None: raise ValueError("Selected vsys was not found.")
        choices = {"zones": sorted(n.get("name") for n in vsys.findall("./zone/entry") if n.get("name") and n.find("./network/layer3") is not None),
                   "addresses": sorted(n.get("name") for n in vsys.findall("./address/entry") if n.get("name")),
                   "services": sorted(n.get("name") for n in vsys.findall("./service/entry") if n.get("name"))}
        data = {"config": normalized(active), "version": version, "vsys": self.vsys, "serial": identity.findtext("./result/system/serial", "")}
        target = getattr(self.transport, "origin", "simulation")
        return Snapshot(self.id, model + " @ " + target + " / " + self.vsys, data, choices)

    def plan(self, rules, snapshot):
        rules = copy.deepcopy(rules); validate_rules(rules)
        if snapshot.platform != self.id or snapshot.data["vsys"] != self.vsys: raise ValueError("Wrong PAN-OS context.")
        config = ET.fromstring(snapshot.data["config"])
        vsys = config.find("./devices/entry/vsys/entry[@name='" + self.vsys + "']")
        existing = {entry.get("name") for entry in vsys.findall("./rulebase/security/rules/entry")}
        expected, operations = [], []
        for row in rules:
            if row["name"] in existing: raise ValueError("A security rule with this name already exists.")
            for field, scope in (("from_zone", "zones"), ("to_zone", "zones"), ("source", "addresses"), ("destination", "addresses"), ("service", "services")):
                if row[field] not in snapshot.choices[scope]: raise ValueError("Select an existing local " + scope + " object.")
            entry = ET.Element("entry", {"name": row["name"]})
            for field, value in (("from", row["from_zone"]), ("to", row["to_zone"]), ("source", row["source"]), ("destination", row["destination"]), ("service", row["service"]), ("application", "any"), ("source-user", "any"), ("category", "any")):
                ET.SubElement(ET.SubElement(entry, field), "member").text = value
            for field, value in (("action", row["action"]), ("disabled", "no"), ("log-end", "yes"), ("negate-source", "no"), ("negate-destination", "no")):
                ET.SubElement(entry, field).text = value
            operations.append({"method": "POST", "path": "/api/", "form": {"type": "config", "action": "set", "xpath": self.base + "/rulebase/security/rules", "element": xml(entry)}})
            expected.append({"name": row["name"], "fields": leaves(entry)})
        commit = ET.Element("commit"); partial = ET.SubElement(commit, "partial")
        ET.SubElement(ET.SubElement(partial, "admin"), "member").text = self.username
        operations.append({"method": "POST", "path": "/api/", "form": {"type": "commit", "action": "partial", "cmd": xml(commit)}})
        return Plan(snapshot, rules, operations, expected, ["Experimental local PAN-OS API adapter; no hardware qualification.",
            "Requires a dedicated API administrator, clean candidate and exclusive configuration/commit locks. Enter the administrator that owns the API key.",
            "New rules append to the local rulebase. Earlier rules may shadow them. Application is any; the selected service constrains layer-4 traffic.",
            "No threat-prevention profiles, NAT or VPN are added. Readback does not prove traffic behavior. Failed candidates are retained for manual inspection."])

    def acquire(self):
        for kind in ("config", "commit"):
            response = self.op(f"<show><{kind}-locks/></show>")
            result = response.find("result")
            if result is None or result.findall(".//entry"): raise RuntimeError("Existing or unrecognized PAN-OS locks; refusing to take ownership.")
        for kind in ("config", "commit"):
            self.op(f"<request><{kind}-lock><add><comment>Network Provisioning Studio</comment></add></{kind}-lock></request>")
            self.locks.append(kind)

    def release(self):
        for kind in reversed(self.locks):
            try: self.op(f"<request><{kind}-lock><remove/></{kind}-lock></request>")
            except Exception: self.log("Could not confirm release of this session's " + kind + " lock; inspect the firewall.")
        self.locks = []

    def deploy(self, plan):
        if self.dirty: raise RuntimeError("A prior candidate or commit outcome requires manual inspection before retrying.")
        try:
            self.acquire()
            active, candidate = self.config(), self.config(True)
            if normalized(active) != plan.snapshot.data["config"]: raise RuntimeError("Active configuration changed before lock acquisition.")
            if normalized(active) != normalized(candidate): raise RuntimeError("Existing PAN-OS candidate changes; nothing staged or committed.")
            for operation in plan.operations[:-1]:
                self.dirty = True
                self.call(operation["form"])
            # Verify every requested field before committing. Locks guard ownership;
            # readback alone is never used as an ownership claim.
            staged = self.config(True)
            self.verify(plan, Snapshot(self.id, "candidate", {"config": normalized(staged)}, {}))
            # Remove only our new entries from a copy, then compare the complete
            # remaining candidate to the locked baseline before any commit.
            baseline, remainder = copy.deepcopy(active), copy.deepcopy(staged)
            for config in (baseline, remainder):
                node = config.find("./devices/entry[@name='localhost.localdomain']/vsys/entry[@name='" + self.vsys + "']")
                for tag in ("rulebase", "security", "rules"):
                    child = node.find(tag)
                    if child is None: child = ET.SubElement(node, tag)
                    node = child
                if config is remainder:
                    wanted_names = {r["name"] for r in plan.expected}
                    for entry in list(node):
                        if entry.get("name") in wanted_names: node.remove(entry)
            if normalized(baseline) != normalized(remainder): raise RuntimeError("Unrelated candidate changes detected under lock; commit refused.")
            response = self.call(plan.operations[-1]["form"])
            job = response.findtext("./result/job", "")
            if not re.fullmatch(r"[0-9]+", job): raise RuntimeError("Commit job was not acknowledged; inspect candidate/running state.")
            self.log("Commit job " + job)
            deadline = time.monotonic() + self.job_timeout
            while time.monotonic() < deadline:
                result = self.op(f"<show><jobs><id>{job}</id></jobs></show>").find("./result/job")
                if result is None or result.findtext("id") != job: raise RuntimeError("Commit job identity was not confirmed.")
                if result.findtext("status") == "FIN":
                    if result.findtext("result") != "OK": raise RuntimeError("PAN-OS commit failed; inspect job " + job)
                    self.dirty = False
                    return
                if result.findtext("status") not in ("ACT", "PEND"): raise RuntimeError("Unrecognized commit job state; inspect job " + job)
                time.sleep(self.poll_interval)
            raise RuntimeError("Commit job timed out; outcome unknown. Inspect job " + job + " before retrying.")
        finally: self.release()

    def verify(self, plan, snapshot):
        config = ET.fromstring(snapshot.data["config"])
        entries = config.findall("./devices/entry/vsys/entry[@name='" + self.vsys + "']/rulebase/security/rules/entry")
        for wanted in plan.expected:
            matches = [entry for entry in entries if entry.get("name") == wanted["name"]]
            if len(matches) != 1: raise RuntimeError("PAN-OS rule identity not confirmed.")
            observed = leaves(matches[0])
            if any(observed.get(k) != v for k, v in wanted["fields"].items()): raise RuntimeError("PAN-OS rule fields did not match reviewed intent.")

    def close(self):
        self.release(); self.transport.close()
