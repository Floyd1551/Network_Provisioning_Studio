import re
import shlex
from .base import Driver, VLAN_FIELDS, compact, quoted
from ..model import Port, vlan_set


class JunosELS(Driver):
    id = "juniper_junos"
    label = "Juniper Junos (EX/QFX, ELS)"
    fingerprint = r"\bJunos\b|JUNOS Software"
    setup = ("set cli screen-length 0", "set cli screen-width 511")
    running_command = "show configuration | display set | no-more"
    status_command = "show interfaces terse | no-more"
    vlan_command = "show vlans | no-more"
    optional = ("show chassis hardware | no-more", "show lldp neighbors | no-more")
    interface_pattern = r"(?:ge|xe|et)-\d+/\d+/\d+(?::\d+)?"
    persistence = "Junos commits the candidate configuration. Successful changes are persistent across reboots."

    def __init__(self):
        self.locked = False
        self.owned_candidate = False

    def parse(self, outputs):
        running = outputs[self.running_command]
        host = re.search(r"(?m)^set system host-name ([\w.-]+)$", running)
        if not host: raise ValueError("Junos set-format configuration is incomplete or unreadable.")
        model, version = self.identity(outputs[self.version_command])
        if not re.match(r"(?:ex|qfx)\d", model, re.I): raise ValueError("Only Junos EX/QFX switches are supported.")
        vlans = {}
        for line in running.splitlines():
            m = re.fullmatch(r"set vlans ([\w.-]+) vlan-id (\d+)", line)
            if m:
                if int(m[2]) in vlans: raise ValueError("Ambiguous VLAN IDs in Junos configuration.")
                vlans[int(m[2])] = m[1]
        by_name = {name: number for number, name in vlans.items()}
        observed = set()
        for line in outputs[self.vlan_command].splitlines():
            for name, number in by_name.items():
                if re.search(r"(?:^|\s)" + re.escape(name) + r"\s+" + str(number) + r"(?:\s|$)", line): observed.add(number)
        vlans = {n: v for n, v in vlans.items() if n in observed}
        ports = {}
        for line in outputs[self.status_command].splitlines():
            m = re.match(r"^\s*((?:ge|xe|et)-\d+/\d+/\d+(?::\d+)?)\s+(up|down)\s+(up|down)\s*$", line)
            if m:
                p = Port(m[1])
                p.config.update(mode="access", access_vlan=None, native_vlan=None, allowed_vlans="none")
                p.status = "disabled" if m[2] == "down" else "connected" if m[3] == "up" else "notconnect"
                p.metadata = dict(members=[], switching=False)
                ports[p.name] = p
        for line in running.splitlines():
            tokens = shlex.split(line)
            if len(tokens) < 4 or tokens[:2] != ["set", "interfaces"] or tokens[2] not in ports: continue
            p = ports[tokens[2]]
            rest = tokens[3:]
            if rest == ["disable"]: p.config["enabled"] = False
            elif rest[0] == "description": p.config["description"] = " ".join(rest[1:])
            elif rest[0] == "native-vlan-id": p.config["native_vlan"] = int(rest[1])
            elif rest[:4] == ["unit", "0", "family", "ethernet-switching"]:
                p.metadata["switching"] = True
                if rest[4:5] == ["interface-mode"]: p.config["mode"] = rest[5]
                elif rest[4:6] == ["vlan", "members"]: p.metadata["members"] += [s for s in rest[6:] if s not in ("[", "]")]
                elif rest[4:5] == ["port-mode"]: p.manageable = False  # non-ELS
            elif rest[0] in ("ether-options", "gigether-options") and "802.3ad" in rest: p.manageable = False
            elif rest[0] == "unit": p.manageable = False  # routed or multiple logical units
            elif rest[0] in ("flexible-vlan-tagging", "vlan-tagging", "encapsulation", "apply-groups"): p.manageable = False
        inherited = bool(re.search(r"(?m)^set .*\bapply-groups\b|^set interfaces interface-range\b|^deactivate interfaces\b", running))
        for p in ports.values():
            if inherited or not p.metadata["switching"]: p.manageable = False
            members = set()
            for value in p.metadata["members"]:
                if value in by_name: members.add(by_name[value])
                else:
                    try: members |= vlan_set(value)
                    except ValueError: p.manageable = False
            if p.config["mode"] == "access":
                if len(members) == 1: p.config["access_vlan"] = next(iter(members))
                else: p.manageable = False
            else: p.config["allowed_vlans"] = "all" if "all" in p.metadata["members"] else compact(members)
        return self.finish_device(outputs, ports, vlans, host[1], model, version)

    def commands(self, changes, device):
        self.validate(changes, device)
        result = ["configure exclusive", "show | compare", "run " + self.running_command]
        for number, name in sorted(changes.vlans.items()):
            if number in device.vlans and device.vlans[number] != name:
                raise ValueError("Junos VLAN names are configuration keys. Renaming is not supported; retain the existing name.")
            if number not in device.vlans and name in device.vlans.values(): raise ValueError("VLAN name already exists.")
            result.append(f"set vlans {name} vlan-id {number}")
        for name, patch in changes.ports.items():
            port = device.ports[name]
            base = f"interfaces {name}"
            switching = base + " unit 0 family ethernet-switching"
            if "description" in patch:
                result.append(f"set {base} description {quoted(patch['description'])}" if patch["description"] else f"delete {base} description")
            if "enabled" in patch:
                if not patch["enabled"]: result.append(f"set {base} disable")
                elif port.config["enabled"] is False: result.append(f"delete {base} disable")
            if VLAN_FIELDS & patch.keys():
                desired = port.config | patch
                if desired["mode"] not in ("access", "trunk"): raise ValueError("Choose access/trunk mode.")
                if "access_vlan" in patch and desired["mode"] != "access": raise ValueError("Access VLAN needs access mode.")
                if ("allowed_vlans" in patch or "native_vlan" in patch) and desired["mode"] != "trunk": raise ValueError("Native/allowed VLAN needs trunk mode.")
                if desired["mode"] == "access":
                    if desired["access_vlan"] not in (device.vlans.keys() | changes.vlans.keys()): raise ValueError("Choose an existing/staged access VLAN.")
                    members = str(desired["access_vlan"])
                else:
                    if desired["allowed_vlans"] == "none": raise ValueError("Choose nonempty trunk membership.")
                    members = desired["allowed_vlans"].replace(",", " ")
                if port.metadata["members"]: result.append(f"delete {switching} vlan members")
                result += [f"set {switching} interface-mode {desired['mode']}", f"set {switching} vlan members [ {members} ]"]
                if desired["mode"] == "access" and port.config["native_vlan"] is not None: result.append(f"delete {base} native-vlan-id")
                elif desired["mode"] == "trunk" and desired["native_vlan"] is not None:
                    result.append(f"set {base} native-vlan-id {desired['native_vlan']}")
        return result + ["commit check", "commit", "exit"]

    def deploy(self, service, preview):
        self.locked = self.owned_candidate = False
        for command in preview.commands:
            output = service.execute(command)
            if command == "configure exclusive":
                if "Entering configuration mode" not in output: raise RuntimeError("Junos exclusive lock was not acknowledged.")
                self.locked = True
            elif command == "show | compare":
                if output.strip(): raise RuntimeError("Existing Junos candidate edits detected. They were not modified or committed.")
                self.owned_candidate = True
            elif command == "run " + self.running_command:
                if self.normalize_config(output) != self.normalize_config(preview.device.running):
                    raise RuntimeError("Junos active configuration changed before exclusive lock; no edits sent.")
            elif command == "commit check" and "configuration check succeeds" not in output:
                raise RuntimeError("Junos commit check did not confirm success.")
            elif command == "commit":
                if "commit complete" not in output: raise RuntimeError("Junos commit outcome is unknown; inspect the device.")
                self.owned_candidate = False
            elif command == "exit": self.locked = False

    def recover(self, service):
        if self.locked:
            if self.owned_candidate:
                service.execute("rollback 0")
                if service.execute("show | compare").strip(): raise RuntimeError("Junos candidate cleanup not confirmed; use raw console.")
            # Never discard a pre-existing candidate, and never commit during error recovery.
            if not self.owned_candidate and service.execute("show | compare").strip():
                raise RuntimeError("Pre-existing candidate retained. Use raw console to leave configuration mode.")
            service.execute("exit")
            self.locked = False
