"""EOS, NX-OS, AOS-CX, OS10 and JetStream drivers. No IOS identity substitution."""
import re
from .base import Driver, CORE, VLAN_FIELDS, blocks, standard_vlans, compact, quoted
from ..driver import parse_port, field_command
from ..model import Port, vlan_set


def hostname(text):
    match = re.search(r'(?m)^hostname\s+"?([\w.-]+)"?\s*$', text)
    if not match: raise ValueError("Missing hostname in configuration; refusing incomplete discovery.")
    return match[1]


class EOS(Driver):
    id = "arista_eos"
    label = "Arista EOS"
    fingerprint = r"\bArista\b"
    status_command = "show interfaces status"
    vlan_command = "show vlan"
    optional = ("show inventory", "show lldp neighbors detail")
    interface_pattern = r"Ethernet\d+(?:/\d+){0,2}"
    capabilities = CORE | {"portfast", "bpduguard"}

    def canonical(self, name): return re.sub(r"^(?:Et|Eth)(?=\d)", "Ethernet", name)

    def parse(self, outputs):
        running = outputs[self.running_command]
        ports = {}
        for name, lines in blocks(running).items():
            name = self.canonical(name)
            if not re.fullmatch(self.interface_pattern, name): continue
            p = parse_port(name, ["switchport mode access"] + lines)
            if "spanning-tree portfast normal" in lines: p.config["portfast"] = "disabled"
            if self.id == "cisco_nxos":
                p.config["enabled"] = "no shutdown" in lines
                if "switchport" not in lines and not any(line.startswith("switchport ") for line in lines): p.manageable = False
            ports[name] = p
        for line in outputs[self.status_command].splitlines():
            m = re.match(r"^\s*(\S+)\s+(.*?)\s+(connected|notconnect|disabled|errdisabled|err-disabled|inactive|suspended|notpresent|sfpAbsent)\s+(\S+)\s+(\S+)\s+(\S+)", line, re.I)
            if not m: continue
            name = self.canonical(m[1])
            if not re.fullmatch(self.interface_pattern, name): continue
            p = ports.setdefault(name, Port(name))
            if p.config["mode"] == "dynamic auto":
                p.config["mode"] = "access"
                p.manageable = False  # no configuration stanza was observed
            p.status = {"errdisabled": "err-disabled"}.get(m[3].lower(), m[3].lower())
            p.speed = m[6]
            if m[4] == "routed": p.manageable = False
        return self.finish_device(outputs, ports, standard_vlans(outputs[self.vlan_command]), hostname(running), *self.identity(outputs[self.version_command]))

    def commands(self, changes, device):
        self.validate(changes, device)
        result = ["configure terminal"]
        for number, name in sorted(changes.vlans.items()): result += [f"vlan {number}", f"name {name}", "exit"]
        for name, patch in changes.ports.items():
            result.append("interface " + name)
            if patch.get("enabled") is False: result.append("shutdown")
            if patch.get("portfast") == "disabled": result.append("spanning-tree portfast normal")
            for key in ("description", "mode", "access_vlan", "native_vlan", "allowed_vlans", "bpduguard"):
                if key in patch: result.append(field_command(key, patch[key]))
            if "portfast" in patch and patch["portfast"] != "disabled": result.append(field_command("portfast", patch["portfast"]))
            if patch.get("enabled") is True: result.append("no shutdown")
            result.append("exit")
        return result + ["end"]


class NXOS(EOS):
    id = "cisco_nxos"
    label = "Cisco NX-OS (standalone)"
    fingerprint = r"Cisco.*(?:NX-OS|Nexus Operating System)"
    interface_pattern = r"Ethernet\d+/\d+(?:/\d+)?"
    capabilities = CORE
    vlan_command = "show vlan brief"


class ArubaCX(Driver):
    id = "aruba_cx"
    label = "HPE Aruba AOS-CX"
    fingerprint = r"\b(?:ArubaOS-CX|AOS-CX)\b"
    setup = ("no page",)
    status_command = "show interface brief"
    vlan_command = "show vlan"
    optional = ("show system", "show lldp neighbor-info")
    interface_pattern = r"\d+/\d+/\d+(?::\d+)?"

    def parse(self, outputs):
        running = outputs[self.running_command]
        ports = {}
        for name, lines in blocks(running).items():
            if not re.fullmatch(self.interface_pattern, name): continue
            p = Port(name)
            p.config.update(mode="access", enabled=False)
            # Only confirmed L2 ports may be edited; never convert routed interfaces implicitly.
            p.manageable = "no routing" in lines or any(x.startswith("vlan ") for x in lines)
            for line in lines:
                if line == "shutdown": p.config["enabled"] = False
                elif line == "no shutdown": p.config["enabled"] = True
                elif line.startswith("description "): p.config["description"] = line[12:].strip('"')
                elif line.startswith("vlan access "):
                    p.config.update(mode="access", access_vlan=int(line.split()[-1]))
                elif line.startswith("vlan trunk native "):
                    p.config.update(mode="trunk", native_vlan=int(line.split()[3]))
                    if line.endswith("tag"): p.manageable = False
                elif line.startswith("vlan trunk allowed "):
                    p.config.update(mode="trunk", allowed_vlans=line.split()[-1])
                if line == "routing" or line.startswith(("lag ", "apply ")): p.manageable = False
            ports[name] = p
        for line in outputs[self.status_command].splitlines():
            m = re.match(r"^\s*(\d+/\d+/\d+(?::\d+)?)\s+(\S+)\s+(access|trunk|routed)\s+\S+\s+(yes|no)\s+(up|down)\s+(.*)", line, re.I)
            if not m: continue
            p = ports.setdefault(m[1], Port(m[1], manageable=False))
            p.status = "disabled" if m[4].lower() == "no" else "connected" if m[5].lower() == "up" else "notconnect"
            speed = re.search(r"(?:^|\s)(\d+)(?:\s|$)", m[6])
            p.speed = speed[1] if speed else "unknown"
            if m[3] == "routed": p.manageable = False
        return self.finish_device(outputs, ports, standard_vlans(outputs[self.vlan_command]), hostname(running), *self.identity(outputs[self.version_command]))

    def commands(self, changes, device):
        self.validate(changes, device)
        result = ["configure terminal"]
        for number, name in sorted(changes.vlans.items()): result += [f"vlan {number}", f"name {name}", "exit"]
        for name, patch in changes.ports.items():
            result.append("interface " + name)
            if patch.get("enabled") is False: result.append("shutdown")
            if "description" in patch: result.append("description " + patch["description"] if patch["description"] else "no description")
            if VLAN_FIELDS & patch.keys():
                desired, native, tagged = self.vlan_intent(patch, device.ports[name], device, changes)
                if desired["mode"] == "access": result.append(f"vlan access {native}")
                else:
                    if desired["allowed_vlans"] == "none": raise ValueError("AOS-CX does not support an empty trunk VLAN list; disable the port instead.")
                    result.append(f"vlan trunk native {native}")
                    old = device.ports[name].config["allowed_vlans"]
                    # AOS-CX allowed VLANs are additive. Remove obsolete members explicitly.
                    if old != "all":
                        remove = vlan_set(old) - tagged
                        if remove: result.append("no vlan trunk allowed " + compact(remove))
                    elif desired["allowed_vlans"] != "all":
                        result.append("no vlan trunk allowed " + compact(vlan_set("all") - tagged))
                    result.append("vlan trunk allowed " + desired["allowed_vlans"])
            if patch.get("enabled") is True: result.append("no shutdown")
            result.append("exit")
        return result + ["end"]


class DellOS10(Driver):
    id = "dell_os10"
    label = "Dell SmartFabric OS10 (Full Switch)"
    fingerprint = r"(?:Dell|SmartFabric).*OS10|OS10 Enterprise"
    running_command = "show running-configuration"
    status_command = "show interface status"
    vlan_command = "show vlan"
    optional = ("show inventory", "show lldp neighbors")
    interface_pattern = r"ethernet\d+/\d+/\d+(?::\d+)?"

    def parse(self, outputs):
        running = outputs[self.running_command]
        ports, vlans = {}, {1: "default"}
        for raw, lines in blocks(running).items():
            name = raw.replace(" ", "").lower()
            match = re.fullmatch(r"vlan(\d+)", name)
            if match:
                number = int(match[1])
                vlans[number] = next((line[10:] for line in lines if line.startswith("vlan-name ")), f"VLAN{number}")
            if not re.fullmatch(self.interface_pattern, name): continue
            p = parse_port(name, ["switchport mode access", "switchport trunk allowed vlan none"] + lines)
            p.config["native_vlan"] = p.config["access_vlan"]
            if any(x.startswith(("ip address ", "virtual-network ")) for x in lines): p.manageable = False
            ports[name] = p
        observed_vlans = set()
        for line in outputs[self.vlan_command].splitlines():
            m = re.match(r"^\s*\*?\s*(\d+)\s+(?:Active|Inactive|active|inactive|up|down)\b", line)
            if m: observed_vlans.add(int(m[1]))
        observed_vlans.update(standard_vlans(outputs[self.vlan_command]))
        if not observed_vlans: raise ValueError("OS10 VLAN table not recognized.")
        vlans = {number: name for number, name in vlans.items() if number in observed_vlans}
        for line in outputs[self.status_command].splitlines():
            m = re.match(r"^\s*(?:Eth|ethernet)\s*(\d+/\d+/\d+(?::\d+)?)\s+(.*?)\s*(up|down)\s+(\S+)\s+(.*)", line, re.I)
            if not m: continue
            name = "ethernet" + m[1]
            p = ports.setdefault(name, Port(name, manageable=False))
            p.status = "disabled" if not p.config["enabled"] else "connected" if m[3] == "up" else "notconnect"
            p.speed = m[4]
        if re.search(r"(?m)^smartfabric\b|^switch-operating-mode smartfabric", running):
            raise ValueError("OS10 SmartFabric-managed mode is not supported; use Full Switch mode.")
        return self.finish_device(outputs, ports, vlans, hostname(running), *self.identity(outputs[self.version_command]))

    def commands(self, changes, device):
        self.validate(changes, device)
        if any(number == 4094 for number in changes.vlans): raise ValueError("OS10 VLAN 4094 is reserved.")
        result = ["configure terminal"]
        for number, name in sorted(changes.vlans.items()): result += [f"interface vlan {number}", f"vlan-name {name}", "exit"]
        for name, patch in changes.ports.items():
            port = device.ports[name]
            result.append("interface ethernet " + name.removeprefix("ethernet"))
            if patch.get("enabled") is False: result.append("shutdown")
            if "description" in patch: result.append(field_command("description", patch["description"]))
            if VLAN_FIELDS & patch.keys():
                desired, native, tagged = self.vlan_intent(patch, port, device, changes)
                if 4094 in tagged or native == 4094: raise ValueError("OS10 supports VLAN IDs through 4093; use an explicit trunk list.")
                old = vlan_set(port.config["allowed_vlans"])
                remove, add = old - tagged, tagged - old
                # OS10's allowed-vlan command adds membership; explicitly remove stale members.
                if remove: result.append("no switchport trunk allowed vlan " + compact(remove))
                result += ["switchport mode " + desired["mode"], f"switchport access vlan {native}"]
                if add: result.append("switchport trunk allowed vlan " + compact(add))
            if patch.get("enabled") is True: result.append("no shutdown")
            result.append("exit")
        return result + ["end"]


class JetStream(Driver):
    id = "tplink_jetstream"
    label = "TP-Link JetStream (General ports)"
    fingerprint = r"TP-LINK|TP-Link|JetStream"
    version_command = "show system-info"
    status_command = "show interface status"
    vlan_command = "show vlan"
    optional = ()
    interface_pattern = r"(?:gigabitEthernet|ten-gigabitEthernet|fastEthernet) \d+/\d+/\d+"

    @property
    def required(self): return super().required + ("show interface switchport",)

    def canonical(self, name):
        for prefix, full in (("Gi", "gigabitEthernet"), ("Te", "ten-gigabitEthernet"), ("Fa", "fastEthernet")):
            if re.match(prefix + r"\d", name): return full + " " + name[len(prefix):]
        return name

    def parse(self, outputs):
        running = outputs[self.running_command]
        ports = {}
        for name, lines in blocks(running).items():
            if not re.fullmatch(self.interface_pattern, name): continue
            p = Port(name)
            tagged, untagged, pvid = set(), {1}, 1
            for line in lines:
                if line.startswith("description "): p.config["description"] = line[12:].strip('"')
                elif line == "shutdown": p.config["enabled"] = False
                elif line == "no shutdown": p.config["enabled"] = True
                elif line.startswith("switchport pvid "): pvid = int(line.split()[-1])
                m = re.fullmatch(r"switchport general allowed vlan ([\d,-]+) (tagged|untagged)", line)
                if m:
                    members = vlan_set(m[1])
                    if m[2] == "tagged": tagged |= members; untagged -= members
                    else: untagged |= members; tagged -= members
                m = re.fullmatch(r"no switchport general allowed vlan ([\d,-]+)", line)
                if m: tagged -= vlan_set(m[1]); untagged -= vlan_set(m[1])
                if line == "no switchport" or line.startswith(("channel-group ", "lag ", "switchport mode access", "switchport mode trunk")): p.manageable = False
            p.config.update(mode="trunk" if tagged else "access", access_vlan=pvid, native_vlan=pvid, allowed_vlans=compact(tagged))
            p.metadata.update(tagged=sorted(tagged), untagged=sorted(untagged))
            if untagged != {pvid}: p.manageable = False
            ports[name] = p
        general = set()
        for line in outputs["show interface switchport"].splitlines():
            m = re.match(r"^\s*(\S+)\s+(\S+)\s+General\s+(\d+)", line, re.I)
            if m and m[2].upper() in ("N/A", "--", "-"): general.add(self.canonical(m[1]))
        for line in outputs[self.status_command].splitlines():
            m = re.match(r"^\s*(\S+)\s+(?:Link)?(Up|Down)\s+(\S+)", line, re.I)
            if not m: continue
            name = self.canonical(m[1])
            if name not in ports: continue
            p = ports[name]
            p.status = "disabled" if not p.config["enabled"] else "connected" if m[2].lower() == "up" else "notconnect"
            p.speed = m[3]
        for name, port in ports.items():
            if name not in general: port.manageable = False
        return self.finish_device(outputs, ports, standard_vlans(outputs[self.vlan_command]), hostname(running), *self.identity(outputs[self.version_command]))

    def commands(self, changes, device):
        self.validate(changes, device)
        result = ["configure"]
        for number, name in sorted(changes.vlans.items()): result += [f"vlan {number}", f"name {name}", "exit"]
        for name, patch in changes.ports.items():
            p = device.ports[name]
            result.append("interface " + name)
            if patch.get("enabled") is False: result.append("shutdown")
            if "description" in patch: result.append("description " + quoted(patch["description"]) if patch["description"] else "no description")
            if VLAN_FIELDS & patch.keys():
                desired, native, tagged = self.vlan_intent(patch, p, device, changes)
                if desired["mode"] == "trunk" and desired["allowed_vlans"] in ("all", "none"):
                    raise ValueError("JetStream trunks require an explicit nonempty tagged VLAN list.")
                if native in tagged: raise ValueError("JetStream allowed VLANs list tagged VLANs only; exclude the native VLAN.")
                if tagged - (device.vlans.keys() | changes.vlans.keys()): raise ValueError("Create every tagged VLAN before assigning it.")
                old = set(p.metadata["tagged"]) | set(p.metadata["untagged"])
                remove = old - tagged - {native}
                result += [f"switchport general allowed vlan {native} untagged", f"switchport pvid {native}"]
                if remove: result.append("no switchport general allowed vlan " + compact(remove))
                if tagged: result.append("switchport general allowed vlan " + compact(tagged) + " tagged")
            if patch.get("enabled") is True: result.append("no shutdown")
            result.append("exit")
        return result + ["end"]
