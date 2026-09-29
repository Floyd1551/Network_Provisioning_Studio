import re
import shlex
from .base import Driver, VLAN_FIELDS, compact, quoted
from ..model import Port


def port_list(expression, known):
    if expression == "all": return set(known)
    result = set()
    for part in expression.replace(" ", "").split(","):
        if part in known: result.add(part); continue
        match = re.fullmatch(r"(?:(\d+):)?(\d+)-(?:(\d+):)?(\d+)", part)
        if not match: raise ValueError(f"Unsupported EXOS port list {expression!r}")
        slot, start, end_slot, end = match.groups()
        if end_slot and end_slot != slot: raise ValueError("Cross-slot EXOS ranges are not supported.")
        if not 0 < int(start) <= int(end) <= 1024: raise ValueError("Invalid EXOS port range.")
        values = {((slot + ":") if slot else "") + str(n) for n in range(int(start), int(end) + 1)}
        if values - known: raise ValueError("EXOS range refers to undiscovered ports.")
        result |= values
    return result


class ExtremeEXOS(Driver):
    id = "extreme_exos"
    label = "Extreme Switch Engine / EXOS"
    fingerprint = r"ExtremeXOS|Switch Engine"
    setup = ("disable clipaging",)
    running_command = "show configuration"
    status_command = "show ports no-refresh"
    vlan_command = "show vlan"
    optional = ("show switch", "show lldp neighbors")
    interface_pattern = r"\d+(?::\d+)?"

    def parse(self, outputs):
        running = outputs[self.running_command]
        if "# Module" not in running and "configure vlan" not in running:
            raise ValueError("EXOS configuration output is unrecognized.")
        ports = {}
        for line in outputs[self.status_command].splitlines():
            m = re.match(r"^\s*(\d+(?::\d+)?)\s+.*?\s+([EDFL])\s+(A|R|NP|L|D|d)(?:\s+(.*))?$", line)
            if not m: continue
            p = Port(m[1])
            p.config.update(enabled=m[2] == "E", mode="access", allowed_vlans="none")
            p.status = "disabled" if m[2] == "D" else "err-disabled" if m[2] in ("F", "L") else "connected" if m[3] == "A" else "notconnect"
            speed = re.match(r"(\d+)", m[4] or "")
            p.speed = speed[1] if speed else "unknown"
            p.metadata = dict(untagged=[1], tagged=[])
            ports[p.name] = p
        vlans = {}
        for line in outputs[self.vlan_command].splitlines():
            m = re.match(r"^\s*([\w.-]+)\s+(\d+)\s+", line)
            if m and 1 <= int(m[2]) <= 4094: vlans[int(m[2])] = m[1]
        by_name = {name: number for number, name in vlans.items()}
        for line in running.splitlines():
            if not line or line.startswith("#"): continue
            tokens = shlex.split(line)
            if tokens[:3] == ["configure", "snmp", "sysName"]: continue
            if len(tokens) == 5 and tokens[:2] == ["configure", "ports"] and tokens[3] == "description-string":
                for name in port_list(tokens[2], ports.keys()): ports[name].config["description"] = tokens[4]
            elif len(tokens) == 3 and tokens[0] in ("enable", "disable") and tokens[1] == "ports":
                for name in port_list(tokens[2], ports.keys()): ports[name].config["enabled"] = tokens[0] == "enable"
            elif len(tokens) >= 6 and tokens[:2] == ["configure", "vlan"] and tokens[3] in ("add", "delete") and tokens[4] == "ports":
                if tokens[2] not in by_name: raise ValueError("EXOS configuration references an unrecognized VLAN.")
                number = by_name[tokens[2]]
                targets = port_list(tokens[5], ports.keys())
                if len(tokens) > 7 or (tokens[3] == "add" and (len(tokens) != 7 or tokens[6] not in ("tagged", "untagged"))):
                    for name in targets: ports[name].manageable = False
                    continue
                for name in targets:
                    p = ports[name]
                    for kind in ("tagged", "untagged"):
                        if number in p.metadata[kind]: p.metadata[kind].remove(number)
                    if tokens[3] == "add": p.metadata[tokens[6]].append(number)
            elif len(tokens) >= 5 and tokens[:2] == ["enable", "sharing"] and tokens[3] == "grouping":
                for name in port_list(tokens[4], ports.keys()) | {tokens[2]}:
                    if name in ports: ports[name].manageable = False
        for p in ports.values():
            untagged, tagged = p.metadata["untagged"], p.metadata["tagged"]
            native = untagged[0] if len(untagged) == 1 else None
            p.config.update(mode="trunk" if tagged else "access", access_vlan=native, native_vlan=native, allowed_vlans=compact(tagged))
            if native is None: p.manageable = False
        # Membership owned by virtual routers, authentication, or translation is outside this driver.
        if re.search(r"(?m)^(?:configure .* (?:private-vlan|translated)\b|create vman\b|enable netlogin ports\b|configure vr (?!VR-Default))", running):
            for p in ports.values(): p.manageable = False
        host = re.search(r'(?m)^configure snmp sysName "?([\w.-]+)"?', running)
        return self.finish_device(outputs, ports, vlans, host[1] if host else "EXOS switch", *self.identity(outputs[self.version_command]))

    def commands(self, changes, device):
        self.validate(changes, device)
        vlans = device.vlans | changes.vlans
        result = []
        for number, name in sorted(changes.vlans.items()):
            if number in device.vlans:
                if device.vlans[number] != name: raise ValueError("EXOS VLAN renaming is not implemented; retain the existing name.")
            else:
                if name in device.vlans.values(): raise ValueError("VLAN name already exists.")
                result += ["create vlan " + quoted(name), f"configure vlan {quoted(name)} tag {number}"]
        for name, patch in changes.ports.items():
            p = device.ports[name]
            if patch.get("enabled") is False: result.append("disable ports " + name)
            if "description" in patch:
                result.append(f"configure ports {name} description-string {quoted(patch['description'])}" if patch["description"] else f"unconfigure ports {name} description-string")
            if VLAN_FIELDS & patch.keys():
                desired, native, tagged = self.vlan_intent(patch, p, device, changes)
                if desired["mode"] == "trunk" and desired["allowed_vlans"] in ("all", "none"):
                    raise ValueError("EXOS trunks require an explicit nonempty tagged VLAN list.")
                if native in tagged: raise ValueError("EXOS allowed VLANs list tagged VLANs only; exclude the native VLAN.")
                if tagged - vlans.keys(): raise ValueError("Create every tagged VLAN before assigning it.")
                old = {n: kind for kind in ("tagged", "untagged") for n in p.metadata[kind]}
                desired_members = {n: "tagged" for n in tagged} | {native: "untagged"}
                for number, kind in old.items():
                    if desired_members.get(number) != kind: result.append(f"configure vlan {quoted(vlans[number])} delete ports {name}")
                for number, kind in desired_members.items():
                    if old.get(number) != kind: result.append(f"configure vlan {quoted(vlans[number])} add ports {name} {kind}")
            if patch.get("enabled") is True: result.append("enable ports " + name)
        return result

    def recover(self, service): pass  # EXOS has a flat CLI; no IOS 'end' command.
