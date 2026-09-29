from dataclasses import dataclass, field, asdict
from ipaddress import IPv4Address, IPv4Interface, IPv4Network
import re


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.:/-]{0,62}", value):
        raise ValueError("Use a simple identifier: letters, digits, underscore, dot, slash, colon or hyphen.")
    return value


def network(value):
    return str(IPv4Network(value, strict=True))


def address(value):
    ip = IPv4Address(value)
    if ip.is_unspecified or ip.is_multicast or ip.is_loopback or int(ip) == 0xffffffff:
        raise ValueError("Use a unicast IPv4 address.")
    return str(ip)


@dataclass
class Intent:
    interfaces: list[dict] = field(default_factory=list)
    routes: list[dict] = field(default_factory=list)
    policies: list[dict] = field(default_factory=list)
    nat: list[dict] = field(default_factory=list)
    services: list[dict] = field(default_factory=list)

    def to_dict(self): return asdict(self)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) - {"interfaces", "routes", "policies", "nat", "services"}:
            raise ValueError("Invalid provisioning draft schema.")
        intent = cls(**value)
        intent.validate()
        return intent

    def validate(self):
        schemas = {
            "interfaces": {"name", "address"},
            "routes": {"id", "destination", "gateway", "interface"},
            "policies": {"id", "source", "destination", "in_interface", "out_interface", "protocol", "port", "action"},
            "nat": {"id", "source", "out_interface"},
        }
        from .network_services import validate
        validate(self.services)
        count = len(self.services)
        for kind, keys in schemas.items():
            rows = getattr(self, kind)
            if not isinstance(rows, list) or len(rows) > 100: raise ValueError("Use at most 100 entries per section.")
            seen = set()
            for row in rows:
                count += 1
                optional = {"nat"} if kind == "policies" else set()
                if not isinstance(row, dict) or not keys <= set(row) or set(row) - keys - optional: raise ValueError(f"Invalid {kind} fields; expected {sorted(keys)}.")
                for key, value in row.items():
                    if not isinstance(value, str): raise ValueError("Draft values must be strings.")
                    if key in ("name", "interface", "in_interface", "out_interface", "id"): identifier(value)
                    elif key in ("source", "destination"): network(value)
                    elif key == "gateway": address(value)
                    elif key == "address":
                        ip = IPv4Interface(value)
                        address(str(ip.ip))
                        if ip.network.prefixlen < 31 and ip.ip in (ip.network.network_address, ip.network.broadcast_address):
                            raise ValueError("Interface address cannot be a subnet or broadcast address.")
                        if str(ip) != value: raise ValueError("Use canonical IPv4/prefix notation.")
                    elif key == "protocol" and value not in ("tcp", "udp", "icmp", "ip"): raise ValueError("Unsupported protocol.")
                    elif key == "action" and value not in ("allow", "deny"): raise ValueError("Choose allow or deny.")
                    elif key == "nat" and value not in ("enable", "disable"): raise ValueError("Choose enable or disable for policy NAT.")
                    elif key == "port" and value and (not value.isdigit() or not 1 <= int(value) <= 65535): raise ValueError("Port must be 1–65535 or empty.")
                key = row.get("id", row.get("name"))
                if key in seen: raise ValueError(f"Duplicate {kind} identifier: {key}")
                seen.add(key)
                if kind == "policies" and row["port"] and row["protocol"] not in ("tcp", "udp"):
                    raise ValueError("Destination ports apply only to TCP or UDP.")
                if kind == "policies" and row["in_interface"] == row["out_interface"]:
                    raise ValueError("Ingress and egress must differ; same-interface policies are not supported.")
                if kind == "policies" and row.get("nat") == "enable" and row["action"] != "allow":
                    raise ValueError("Source NAT applies only to allow policies.")
            if kind == "routes" and len({r["destination"] for r in rows}) != len(rows):
                raise ValueError("Only one new route per destination prefix can be staged.")
        if not count: raise ValueError("Add at least one provisioning change.")


@dataclass
class Snapshot:
    platform: str
    hostname: str
    running: str
    interfaces: dict
    facts: dict
    evidence: dict = field(default_factory=dict)


@dataclass
class Plan:
    snapshot: Snapshot
    intent: Intent
    commands: list[str]
    expected: dict
    warnings: list[str]
    persistence: str
