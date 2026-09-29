"""Platform driver contract and shared, conservative parsing utilities."""
import re
from .. import driver as ios
from ..model import Device, Port, natural_key, safe_text, vlan_set

CORE = frozenset({"description", "enabled", "mode", "access_vlan", "native_vlan", "allowed_vlans"})
VLAN_FIELDS = {"mode", "access_vlan", "native_vlan", "allowed_vlans"}


def compact(numbers):
    values = sorted(set(numbers))
    ranges = []
    while values:
        first = last = values.pop(0)
        while values and values[0] == last + 1: last = values.pop(0)
        ranges.append(str(first) if first == last else f"{first}-{last}")
    return ",".join(ranges) or "none"


def quoted(value):
    safe_text(value)
    if any(char in value for char in '\\"'):
        raise ValueError('Quoted vendor descriptions cannot contain a double quote or backslash.')
    return '"' + value + '"'


def blocks(text):
    """Configuration stanzas keyed by their full interface identifier."""
    result, current = {}, None
    for line in text.splitlines():
        if line.startswith("interface "):
            current = line[10:].strip()
            result[current] = []
        elif line and not line[0].isspace(): current = None
        elif current and line.strip(): result[current].append(line.strip())
    return result


def standard_vlans(text):
    result = {}
    current = None
    for line in text.splitlines():
        match = re.match(r"^\s*\*?\s*(\d+)\s+(\S+)\s+(?:active|up|down|suspend|act/unsup|port-based)\b", line, re.I)
        if match: result[int(match[1])] = match[2]
        match = re.match(r"^\s*VLAN\s*(?:ID)?\s*:?\s*(\d+)\s*$", line, re.I)
        if match: current = int(match[1])
        match = re.match(r"^\s*(?:VLAN )?Name\s*:\s*(\S+)", line, re.I)
        if match and current is not None: result[current] = match[1]
    return result


class Driver:
    id = ""
    label = ""
    fingerprint = r"(?!)"
    version_command = "show version"
    running_command = "show running-config"
    setup = ("terminal length 0",)
    optional = ()
    capabilities = CORE
    interface_pattern = r"(?!)"
    persistence = "Changes affect running-config only; startup-config is not saved."
    experimental = True

    @property
    def required(self):
        return (self.version_command, self.running_command, self.status_command, self.vlan_command)

    def matches(self, text): return bool(re.search(self.fingerprint, text, re.I))

    def is_error(self, output):
        return bool(ios.ERROR.search(output) or re.search(r"(?im)^\s*(?:error:|syntax error|invalid (?:command|input)|unknown command|unrecognized command|permission denied|configuration database locked|failed\b)", output))

    def normalize_config(self, text):
        return "\n".join(line.rstrip() for line in text.splitlines() if not re.match(
            r"^(?:Building configuration|Current configuration|! Last configuration|! NVRAM config|!Time:|# Generated|\s*$)", line))

    def validate(self, changes, device):
        if device.driver_id != self.id: raise ValueError("Device/driver mismatch; reconnect.")
        changes.validate(device)
        if self.id in ("juniper_junos", "extreme_exos"):
            names = list((device.vlans | changes.vlans).values())
            if len(names) != len(set(names)):
                raise ValueError("VLAN names must be unique on this platform.")
        for patch in changes.ports.values():
            if "description" in patch and self.id != "cisco_ios": quoted(patch["description"])

    def finish_device(self, outputs, ports, vlans, hostname, model="Unknown model", version="Unknown version"):
        if not self.matches(outputs[self.version_command]):
            raise ValueError(f"Device identity does not match {self.label}; no configuration is allowed.")
        if not ports or not vlans or all(p.status == "unknown" for p in ports.values()):
            raise ValueError(f"{self.label}: required port/VLAN output was not recognized. Discovery stopped.")
        for p in ports.values():
            if p.status == "unknown": p.manageable = False
            for key in set(p.config) - self.capabilities: p.config[key] = None
            p.vlan = "trunk" if p.config["mode"] == "trunk" else str(p.config["access_vlan"])
        warnings = [f"Optional discovery unavailable: {cmd}" for cmd in self.optional if self.is_error(outputs.get(cmd, ""))]
        if self.experimental: warnings.append(f"{self.label}: experimental driver; not hardware-qualified.")
        return Device(hostname, model, version, dict(sorted(ports.items(), key=lambda item: natural_key(item[0]))),
                      vlans, outputs[self.running_command], outputs, warnings, self.id, self.label,
                      self.capabilities, self.interface_pattern, self.persistence)

    def identity(self, text):
        model = re.search(r"(?im)^\s*(?:Model(?: Number)?|Product Name|Platform)\s*:\s*(\S+)", text)
        version = re.search(r"(?im)(?:Software (?:image )?version|OS Version|Version|Junos)\s*[: ]\s*([\w.()/-]+)", text)
        return model[1] if model else "Unknown model", version[1] if version else "Unknown version"

    def deploy(self, service, preview):
        for command in preview.commands: service.execute(command)

    def recover(self, service): service.execute("end")

    def verify(self, changes, after): return ios.verify(changes, after)

    def vlan_intent(self, patch, port, device, changes):
        desired = port.config | patch
        mode = desired["mode"]
        if mode not in ("access", "trunk"): raise ValueError("Select access or trunk mode explicitly.")
        if "access_vlan" in patch and mode != "access": raise ValueError("Access VLAN edits require access mode.")
        if ("native_vlan" in patch or "allowed_vlans" in patch) and mode != "trunk":
            raise ValueError("Native/allowed VLAN edits require trunk mode.")
        native = desired["access_vlan"] if mode == "access" else desired["native_vlan"]
        if native not in device.vlans and native not in changes.vlans:
            raise ValueError("Select an existing/staged native or access VLAN explicitly.")
        tagged = set() if mode == "access" else vlan_set(desired["allowed_vlans"])
        return desired, native, tagged


class CiscoIOS(Driver):
    id = "cisco_ios"
    label = "Cisco IOS / IOS-XE"
    fingerprint = r"Cisco.*(?:IOS|Internetwork Operating)"
    status_command = "show interfaces status"
    vlan_command = "show vlan brief"
    optional = ("show inventory", "show switch", "show power inline", "show cdp neighbors detail")
    capabilities = frozenset(Port("unused").config)
    interface_pattern = Device.__dataclass_fields__["interface_pattern"].default
    experimental = False

    def matches(self, text):
        return super().matches(text) and not re.search(r"NX-OS|Nexus Operating", text, re.I)

    def parse(self, outputs): return ios.parse_device(outputs)
    def commands(self, changes, device):
        self.validate(changes, device)
        return ios.commands(changes, device)
