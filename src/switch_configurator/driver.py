"""IOS-specific parsing and generation. No GUI or serial dependencies."""
import re
from .model import Device, Port, ChangeSet, interface_name, physical_interface, natural_key, vlan_set

# Percent-prefixed CLI diagnostics are conservative failures. Normal IOS syslog
# facility-severity-mnemonic messages are distinct from command diagnostics.
ERROR = re.compile(r"(?im)^[ \t]*(?:%(?![A-Z0-9_]+-\d-|Warning:\s*portfast should only|Portfast has been configured)|(?:Error|Invalid input|Incomplete command|Ambiguous command):?|Command rejected|This command is not supported|Command not supported|Command is not allowed)")


def config_blocks(text):
    blocks = {}
    current = None
    for line in text.splitlines():
        if line.startswith("interface "):
            current = interface_name(line.split(maxsplit=1)[1].strip())
            blocks[current] = []
        elif line and not line[0].isspace():
            current = None
        elif current and line.strip():
            blocks[current].append(line.strip())
    return blocks


def parse_port(name, lines):
    port = Port(name)
    for line in lines:
        if line == "shutdown": port.config["enabled"] = False
        elif line == "no shutdown": port.config["enabled"] = True
        elif line.startswith("description "): port.config["description"] = line[12:]
        elif line.startswith("switchport mode "): port.config["mode"] = line[16:]
        elif line.startswith("switchport access vlan "): port.config["access_vlan"] = int(line.split()[-1])
        elif line.startswith("switchport voice vlan "):
            value = line.split()[-1]
            port.config["voice_vlan"] = int(value) if value.isdigit() else value
        elif line.startswith("switchport trunk native vlan "): port.config["native_vlan"] = int(line.split()[-1])
        elif line.startswith("switchport trunk allowed vlan "):
            value = line[len("switchport trunk allowed vlan "):]
            parts = value.split()
            if len(parts) == 1: port.config["allowed_vlans"] = value
            else:
                old = vlan_set(port.config["allowed_vlans"])
                operand = vlan_set(parts[-1])
                if parts[0] == "add": old |= operand
                elif parts[0] == "remove": old -= operand
                elif parts[0] == "except": old = vlan_set("all") - operand
                port.config["allowed_vlans"] = ",".join(map(str, sorted(old))) or "none"
        elif re.match(r"power inline (?:auto|never|static)(?: |$)", line): port.config["poe"] = line.split()[2]
        elif line.startswith("speed "): port.config["speed"] = line.split()[1]
        elif line.startswith("duplex "): port.config["duplex"] = line.split()[1]
        elif line in ("spanning-tree portfast", "spanning-tree portfast edge", "spanning-tree portfast trunk", "spanning-tree portfast edge trunk"):
            port.config["portfast"] = "enabled"
        elif line in ("spanning-tree portfast disable", "spanning-tree portfast edge disable"):
            port.config["portfast"] = "disabled"
        elif line.startswith("spanning-tree bpduguard "):
            port.config["bpduguard"] = "enabled" if line.endswith("enable") else "disabled"
        if line == "no switchport" or line.startswith(("channel-group ", "source template ")):
            port.manageable = False
    return port


def parse_device(outputs):
    running = outputs["show running-config"]
    if not re.search(r"(?m)^end\s*$", running) or not re.search(r"(?m)^hostname \S+", running):
        raise ValueError("Running configuration is incomplete or unreadable; discovery stopped.")
    version = outputs["show version"]
    if not re.search(r"Cisco.*(?:IOS|Internetwork Operating)", version, re.I):
        raise ValueError("This device was not identified as Cisco IOS / IOS-XE.")
    host = re.search(r"(?m)^hostname (\S+)", running).group(1)
    model = re.search(r"(?im)^\s*Model [Nn]umber\s*:\s*(\S+)", version)
    if not model: model = re.search(r"(?im)^cisco (\S+) .*processor", version)
    release = re.search(r"Version ([^,\s]+)", version)
    ports = {name: parse_port(name, lines) for name, lines in config_blocks(running).items() if physical_interface(name)}
    status = outputs["show interfaces status"]
    for line in status.splitlines():
        match = re.match(r"^(\S+)\s+(.*?)\s+(connected|notconnect|disabled|err-disabled|inactive|suspended|monitoring|sfpAbsent)\s+(\S+)\s+(\S+)\s+(\S+)", line)
        if not match: continue
        name = interface_name(match[1])
        if not physical_interface(name): continue
        port = ports.setdefault(name, Port(name))
        port.status, port.vlan, port.speed = match[3], match[4], match[6]
        if port.vlan == "routed": port.manageable = False
    vlans = {}
    for line in outputs["show vlan brief"].splitlines():
        match = re.match(r"^\s*(\d+)\s+(\S+)\s+(?:active|suspend|act/unsup)", line)
        if match: vlans[int(match[1])] = match[2]
    if not ports or all(p.status == "unknown" for p in ports.values()) or not vlans:
        raise ValueError("Required interface/VLAN output was not recognized; refusing incomplete discovery.")
    for line in outputs.get("show power inline", "").splitlines():
        match = re.match(r"^(\S+)\s+(auto|static|off|never)\s+(on|off|denied|faulty)\s+([\d.]+)", line)
        if match and interface_name(match[1]) in ports:
            port = ports[interface_name(match[1])]
            port.poe, port.watts = match[3], match[4]
    neighbor = None
    for line in outputs.get("show cdp neighbors detail", "").splitlines():
        if line.startswith("Device ID:"): neighbor = line.split(":", 1)[1].strip()
        match = re.search(r"Interface:\s*([^,]+)", line)
        if match and interface_name(match[1].strip()) in ports:
            ports[interface_name(match[1].strip())].neighbor = neighbor or "Unknown"
    warnings = [f"Optional discovery unavailable: {cmd}" for cmd, output in outputs.items() if ERROR.search(output)]
    return Device(host, model[1] if model else "Unknown model", release[1] if release else "Unknown version",
                  dict(sorted(ports.items(), key=lambda item: natural_key(item[0]))), vlans, running, outputs, warnings)


def field_command(key, value):
    if key == "description": return "description " + value if value else "no description"
    if key == "enabled": return "no shutdown" if value else "shutdown"
    if key == "voice_vlan": return f"switchport voice vlan {value}" if value else "no switchport voice vlan"
    if key == "portfast": return {"enabled": "spanning-tree portfast", "disabled": "spanning-tree portfast disable", "default": "no spanning-tree portfast"}[value]
    if key == "bpduguard": return {"enabled": "spanning-tree bpduguard enable", "disabled": "spanning-tree bpduguard disable", "default": "no spanning-tree bpduguard"}[value]
    prefix = {"mode": "switchport mode", "access_vlan": "switchport access vlan", "native_vlan": "switchport trunk native vlan",
              "allowed_vlans": "switchport trunk allowed vlan", "poe": "power inline", "speed": "speed", "duplex": "duplex"}
    return f"{prefix[key]} {value}"


def commands(changes: ChangeSet, device: Device):
    changes.validate(device)
    result = ["configure terminal"]
    for number, name in sorted(changes.vlans.items()): result += [f"vlan {number}", f"name {name}", "exit"]
    for name, patch in sorted(changes.ports.items(), key=lambda item: natural_key(item[0])):
        result.append(f"interface {name}")
        # Disable before edits; enable only after the rest of the intended policy is installed.
        if patch.get("enabled") is False: result.append("shutdown")
        if patch.get("portfast") == "disabled": result.append(field_command("portfast", "disabled"))
        order = ("description", "mode", "access_vlan", "voice_vlan",
                 "native_vlan", "allowed_vlans", "poe", "speed", "duplex", "bpduguard")
        result.extend(field_command(key, patch[key]) for key in order if key in patch)
        if "portfast" in patch and patch["portfast"] != "disabled": result.append(field_command("portfast", patch["portfast"]))
        if patch.get("enabled") is True: result.append("no shutdown")
        result.append("exit")
    return result + ["end"]


def verify(changes, after):
    mismatches = []
    for name, patch in changes.ports.items():
        if name not in after.ports:
            mismatches.append(f"{name}: missing after deployment")
            continue
        for key, expected in patch.items():
            actual = after.ports[name].config.get(key)
            equal = vlan_set(actual) == vlan_set(expected) if key == "allowed_vlans" else actual == expected
            if not equal: mismatches.append(f"{name} {key}: expected {expected!r}, read {actual!r}")
    for number, name in changes.vlans.items():
        if after.vlans.get(number) != name: mismatches.append(f"VLAN {number}: name/existence mismatch")
    return mismatches
