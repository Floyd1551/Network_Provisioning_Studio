"""Synthetic SonicOS API session. No network access or hardware qualification."""
import copy


class SonicDemo:
    simulated = True
    def __init__(self):
        self.headers, self.sent, self.pending = {}, [], {}
        self.data = {
            "/version": {"firmware_version": "SonicOS 7.0.1-12", "model": "DEMO-TZ", "serial_number": "SIMULATED"},
            "/zones": {"zones": [{"name": "LAN"}, {"name": "WAN"}]},
            "/address-objects/ipv4": {"address_objects": [{"ipv4": {"name": "Lab clients", "zone": "LAN", "network": {"subnet": "10.20.0.0", "mask": "255.255.255.0"}}}, {"ipv4": {"name": "Lab server", "zone": "WAN", "host": {"ip": "192.0.2.20"}}}]},
            "/service-objects": {"service_objects": [{"name": "HTTPS", "TCP": {"begin": 443, "end": 443}}]},
            "/access-rules/ipv4": {"access_rules": []},
        }

    def request(self, method, path, payload=None, **kwargs):
        self.sent.append((method, path, copy.deepcopy(payload)))
        key = path.removeprefix("/api/sonicos")
        ok = {"status": {"success": True}}
        if (method, key) in (("POST", "/auth"), ("POST", "/start-management"), ("DELETE", "/auth")): return ok
        if key == "/config/pending":
            if method == "GET": return copy.deepcopy(self.pending)
            if method == "POST":
                self.data["/access-rules/ipv4"]["access_rules"].extend({"ipv4": r["ipv4"]} for r in self.pending.get("access_rules", []))
                self.pending = {}; return ok
        if key == "/access-rules/ipv4" and method == "POST":
            self.pending = {"access_rules": [{"pending": "ADD", **copy.deepcopy(row)} for row in payload["access_rules"]]}
            return ok
        if method == "GET" and key in self.data: return copy.deepcopy(self.data[key])
        return {"status": {"success": False}}

    def close(self): self.headers.clear()


class PANDemo:
    simulated = True
    def __init__(self):
        from xml.etree import ElementTree as ET
        self.headers, self.sent, self.locks = {}, [], set()
        self.running = ET.fromstring('''<config version="11.1.0"><devices><entry name="localhost.localdomain"><vsys><entry name="vsys1">
<zone><entry name="trust"><network><layer3><member>ethernet1/1</member></layer3></network></entry><entry name="untrust"><network><layer3><member>ethernet1/2</member></layer3></network></entry></zone>
<address><entry name="Lab clients"><ip-netmask>10.20.0.0/24</ip-netmask></entry><entry name="Lab server"><ip-netmask>192.0.2.20/32</ip-netmask></entry></address>
<service><entry name="HTTPS"><protocol><tcp><port>443</port></tcp></protocol></entry></service>
<rulebase><security><rules/></security></rulebase></entry></vsys></entry></devices></config>''')
        self.candidate = copy.deepcopy(self.running)
        self.fail_job = False

    def request(self, method, path, payload=None, form=None, **kwargs):
        from xml.etree import ElementTree as ET
        self.sent.append(copy.deepcopy(form))
        response = ET.Element("response", {"status": "success"}); result = ET.SubElement(response, "result")
        if form["type"] == "config":
            if form["action"] in ("show", "get"):
                result.append(copy.deepcopy(self.candidate if form["action"] == "get" else self.running))
            elif form["action"] == "set":
                self.candidate.find("./devices/entry/vsys/entry/rulebase/security/rules").append(ET.fromstring(form["element"]))
            else: response.set("status", "error")
        elif form["type"] == "commit": ET.SubElement(result, "job").text = "1"
        elif form["type"] == "op":
            cmd = ET.fromstring(form["cmd"])
            if cmd.find("./system/info") is not None:
                system = ET.SubElement(result, "system")
                ET.SubElement(system, "model").text = "PA-DEMO"; ET.SubElement(system, "sw-version").text = "11.1.4"
            elif cmd.find("./jobs/id") is not None:
                job = ET.SubElement(result, "job")
                ET.SubElement(job, "id").text = "1"; ET.SubElement(job, "status").text = "FIN"
                ET.SubElement(job, "result").text = "FAIL" if self.fail_job else "OK"
                if not self.fail_job: self.running = copy.deepcopy(self.candidate)
            elif cmd.tag == "show":
                kind = list(cmd)[0].tag.removesuffix("-locks")
                if kind in self.locks: ET.SubElement(result, "entry", {"name": "another-admin"})
            elif cmd.tag == "request":
                node = list(cmd)[0]; kind = node.tag.removesuffix("-lock")
                if node.find("add") is not None:
                    if kind in self.locks: response.set("status", "error")
                    else: self.locks.add(kind)
                elif node.find("remove") is not None: self.locks.discard(kind)
        return response

    def close(self): self.headers.clear()


class CheckPointDemo:
    simulated = True
    def __init__(self):
        self.headers, self.sent, self.rules, self.candidate = {}, [], [], []
        self.sessions, self.tasks, self.fail_install = 0, {}, False
        self.package = {"name": "Lab", "uid": "package-1", "access": True, "access-layers": [{"name": "Network", "uid": "layer-1"}]}
        self.gateway = {"name": "Lab gateway", "uid": "gateway-1", "type": "simple-gateway"}
        self.collections = {
            "show-hosts": [{"name": "Lab server", "uid": "host-1", "type": "host", "ipv4-address": "192.0.2.20"}],
            "show-networks": [{"name": "Lab clients", "uid": "network-1", "type": "network", "subnet4": "10.20.0.0", "mask-length4": 24}],
            "show-services-tcp": [{"name": "HTTPS", "uid": "service-1", "type": "service-tcp", "port": "443"}],
            "show-services-udp": [],
        }

    def request(self, method, path, payload=None, **kwargs):
        command = path.removeprefix("/web_api/"); payload = payload or {}
        # Login payload deliberately is not retained in this synthetic activity log.
        self.sent.append((command, {} if command == "login" else copy.deepcopy(payload)))
        if command == "login":
            self.sessions += 1; self.candidate = copy.deepcopy(self.rules)
            return {"sid": "demo-session-" + str(self.sessions), "api-server-version": "1.9"}
        if command == "logout": return {"message": "OK"}
        if command == "show-package": return copy.deepcopy(self.package)
        if command == "show-simple-gateway": return copy.deepcopy(self.gateway)
        if command in self.collections or command == "show-access-rulebase":
            rows = self.candidate if command == "show-access-rulebase" else self.collections[command]
            key = "rulebase" if command == "show-access-rulebase" else "objects"
            return {key: copy.deepcopy(rows[payload["offset"]:payload["offset"] + payload["limit"]]), "total": len(rows)}
        if command == "add-access-rule":
            rule = {k: copy.deepcopy(v) for k, v in payload.items() if k not in ("layer", "position", "ignore-warnings", "ignore-errors")}
            rule.update(uid="rule-" + str(len(self.candidate) + 1), type="access-rule")
            rule["action"] = {"name": rule["action"], "uid": "action-1"}
            rule["track"]["type"] = {"name": "Log", "uid": "track-1"}
            self.candidate.append(rule); return copy.deepcopy(rule)
        if command in ("publish", "install-policy"):
            task = "task-" + str(len(self.tasks) + 1); self.tasks[task] = command
            if command == "publish": self.rules = copy.deepcopy(self.candidate)
            return {"task-id": task}
        if command == "show-task":
            status = "failed" if self.fail_install and self.tasks[payload["task-id"]] == "install-policy" else "succeeded"
            return {"tasks": [{"task-id": payload["task-id"], "status": status}]}
        return {"code": "generic_error"}

    def close(self): self.headers.clear()
