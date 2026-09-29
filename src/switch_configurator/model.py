from dataclasses import dataclass, field
import re


def interface_name(value: str) -> str:
    for short, full in (("Gi", "GigabitEthernet"), ("Te", "TenGigabitEthernet"),
                        ("Fa", "FastEthernet"), ("Tw", "TwoGigabitEthernet"),
                        ("Fo", "FortyGigabitEthernet"), ("Hu", "HundredGigE")):
        if re.fullmatch(short + r"\d+(?:/\d+){1,2}", value):
            return full + value[len(short):]
    return value


def physical_interface(value: str) -> bool:
    return bool(re.fullmatch(r"(?:GigabitEthernet|TenGigabitEthernet|FastEthernet|TwoGigabitEthernet|FortyGigabitEthernet|HundredGigE)\d+(?:/\d+){1,2}", value))


def natural_key(value: str):
    return tuple(int(part) if part.isdigit() else part for part in re.split(r"(\d+)", value))


def safe_text(value: str, maximum=80) -> str:
    if len(value) > maximum or any(ord(c) < 32 or ord(c) > 126 for c in value) or any(c in value for c in "?;"):
        raise ValueError(f"Use at most {maximum} printable ASCII characters without ? or ;.")
    return value.strip()


def vlan_id(value, cisco_reserved=True) -> int:
    number = int(value)
    if not 1 <= number <= 4094 or (cisco_reserved and 1002 <= number <= 1005):
        raise ValueError("VLAN must be 1–4094; Cisco VLANs 1002–1005 are reserved.")
    return number


def vlan_set(value: str) -> set[int]:
    if value == "all":
        return set(range(1, 4095))
    if value == "none":
        return set()
    result = set()
    for part in value.split(","):
        if not re.fullmatch(r"\d+(?:-\d+)?", part):
            raise ValueError("Allowed VLANs must be all, none, or a list such as 10,20,30-40.")
        ends = [int(n) for n in part.split("-")]
        lo, hi = ends[0], ends[-1]
        if not 1 <= lo <= hi <= 4094:
            raise ValueError("Invalid VLAN range.")
        result.update(range(lo, hi + 1))
    return result


@dataclass
class Port:
    name: str
    config: dict = field(default_factory=lambda: dict(description="", enabled=True, mode="dynamic auto",
        access_vlan=1, voice_vlan=0, native_vlan=1, allowed_vlans="all", poe="auto",
        speed="auto", duplex="auto", portfast="default", bpduguard="default"))
    status: str = "unknown"
    speed: str = "unknown"
    vlan: str = "unknown"
    poe: str = "unknown"
    watts: str = "—"
    neighbor: str = "Not reported"
    manageable: bool = True
    metadata: dict = field(default_factory=dict)


@dataclass
class Device:
    hostname: str
    model: str
    version: str
    ports: dict[str, Port]
    vlans: dict[int, str]
    running: str
    evidence: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    driver_id: str = "cisco_ios"
    platform: str = "Cisco IOS / IOS-XE"
    capabilities: frozenset = field(default_factory=lambda: frozenset(Port("unused").config))
    interface_pattern: str = r"(?:GigabitEthernet|TenGigabitEthernet|FastEthernet|TwoGigabitEthernet|FortyGigabitEthernet|HundredGigE)\d+(?:/\d+){1,2}"
    persistence: str = "Changes affect running-config only; startup-config is not saved."


@dataclass
class ChangeSet:
    ports: dict[str, dict] = field(default_factory=dict)
    vlans: dict[int, str] = field(default_factory=dict)

    def validate(self, device: Device):
        if not self.ports and not self.vlans:
            raise ValueError("Stage at least one change first.")
        for number, name in self.vlans.items():
            vlan_id(number, device.driver_id in ("cisco_ios", "cisco_nxos"))
            if not name or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", name):
                raise ValueError("VLAN names need 1–32 letters, numbers, underscores or hyphens.")
        allowed = {"description", "enabled", "mode", "access_vlan", "voice_vlan", "native_vlan",
                   "allowed_vlans", "poe", "speed", "duplex", "portfast", "bpduguard"}
        for name, patch in self.ports.items():
            if not re.fullmatch(device.interface_pattern, name) or name not in device.ports or not device.ports[name].manageable:
                raise ValueError(f"{name}: only discovered standalone Layer 2 physical ports are editable.")
            if set(patch) - allowed:
                raise ValueError("Unsupported configuration field.")
            unsupported = set(patch) - device.capabilities
            if unsupported:
                raise ValueError(f"{device.platform} driver does not support: {', '.join(sorted(unsupported))}")
            for key, value in patch.items():
                if key == "description": safe_text(value)
                elif key == "enabled" and not isinstance(value, bool): raise ValueError("Invalid enabled value.")
                elif key in ("access_vlan", "native_vlan", "voice_vlan"):
                    if key == "voice_vlan" and value == 0: continue
                    vlan_id(value, device.driver_id in ("cisco_ios", "cisco_nxos"))
                    if int(value) not in device.vlans and int(value) not in self.vlans:
                        raise ValueError(f"VLAN {value} must exist or be staged for creation.")
                elif key == "allowed_vlans": vlan_set(value)
                elif key in ("mode", "poe", "speed", "duplex", "portfast", "bpduguard"):
                    options = {"mode": ("access", "trunk"), "poe": ("auto", "never"),
                               "speed": ("auto", "10", "100", "1000"), "duplex": ("auto", "full", "half"),
                               "portfast": ("default", "enabled", "disabled"),
                               "bpduguard": ("default", "enabled", "disabled")}
                    if value not in options[key]: raise ValueError(f"Invalid {key}.")
            desired = device.ports[name].config | patch
            if desired["mode"] == "trunk" and desired["portfast"] == "enabled":
                raise ValueError(f"{name}: disable PortFast before configuring a switch trunk.")


PROFILES = {
    "Workstation": dict(mode="access", enabled=True, portfast="enabled", bpduguard="enabled"),
    "IP Phone + Workstation": dict(mode="access", enabled=True, poe="auto", portfast="enabled", bpduguard="enabled"),
    "Wireless Access Point": dict(mode="access", enabled=True, poe="auto", portfast="enabled", bpduguard="enabled"),
    "Security Camera": dict(mode="access", enabled=True, poe="auto", portfast="enabled", bpduguard="enabled"),
    "Printer": dict(mode="access", enabled=True, portfast="enabled", bpduguard="enabled"),
    "Server": dict(mode="access", enabled=True, portfast="enabled", bpduguard="enabled"),
    "Switch Uplink": dict(mode="trunk", enabled=True, portfast="disabled", bpduguard="disabled"),
    "Disabled / Unused": dict(enabled=False, poe="never"),
}
