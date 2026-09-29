"""Scenario compilers stage intent only; device drivers remain the authority."""
from dataclasses import dataclass
from copy import deepcopy
from ipaddress import IPv4Interface
from .model import Intent
from .drivers import DRIVERS
from ..model import ChangeSet, vlan_id, vlan_set, safe_text
from ..vendors import get_driver


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    description: str
    requires: tuple
    fields: tuple
    follow_up: tuple


ROUTER_SCENARIOS = (
    Scenario("branch", "Branch routing foundation", "Address a LAN interface and add a route through an existing WAN. Optionally stage a traffic rule and source NAT.",
             ("interfaces", "routes"), ("lan", "lan_address", "wan", "destination", "gateway", "base_id", "access", "source_nat"),
             ("Configure DHCP, DNS, switch VLANs and VPN separately if needed.", "This is one device's routing foundation, not a complete site deployment.")),
    Scenario("outbound", "Outbound network access", "Permit a chosen traffic type from an existing LAN toward an existing WAN. Optionally add source NAT and a default route.",
             ("policies",), ("lan", "wan", "source", "destination", "protocol", "port", "base_id", "source_nat", "add_default", "gateway"),
             ("Existing rules retain their order; inspect earlier rules and the return path.", "A single service rule does not provide DNS or every application dependency.")),
    Scenario("service", "Application / service access", "Allow or deny one explicit source-to-destination service between existing routed interfaces.",
             ("policies",), ("lan", "wan", "source", "destination", "protocol", "port", "action", "base_id"),
             ("Validate the application and its return traffic after deployment.",)),
    Scenario("routed_lan", "Add a routed LAN", "Set a static IPv4 address on an existing routed interface while preserving its administrative state.",
             ("interfaces",), ("lan", "lan_address"),
             ("Configure downstream addressing, DHCP and access policy separately.", "A shutdown interface remains shutdown.")),
    Scenario("route", "Reach another network", "Add a static route to a destination through a directly connected next hop.",
             ("routes",), ("wan", "destination", "gateway", "base_id"),
             ("Check the remote network's return route and firewall policy.",)),
    Scenario("nat", "Source NAT / masquerade", "Translate a source network to the outgoing interface address on RouterOS. Existing rule order is preserved.",
             ("nat",), ("wan", "source", "base_id"),
             ("NAT does not grant forwarding permission; review the filter rules too.",)),
)

SWITCH_SCENARIOS = (
    Scenario("workstations", "Workstation access ports", "Assign selected endpoint ports to an access VLAN.", (), ("ports", "vlan", "vlan_name", "description", "enable"), ("Provide a gateway and DHCP service separately if needed.",)),
    Scenario("guest", "Guest VLAN — switch ports", "Place selected guest-facing ports in an access VLAN. This does not create an SSID or firewall isolation.", (), ("ports", "vlan", "vlan_name", "description", "enable"), ("Configure guest isolation on the router/firewall; VLAN assignment alone is not an isolation policy.", "Configure wireless SSIDs, gateway and DHCP separately.")),
    Scenario("cameras", "Camera / IoT VLAN", "Assign camera or IoT endpoint ports to an access VLAN.", (), ("ports", "vlan", "vlan_name", "description", "enable"), ("Restrict traffic to required controllers/recorders on the firewall.", "PoE settings are preserved; check device power requirements.")),
    Scenario("servers", "Server access ports", "Assign untagged server-facing ports to an access VLAN.", (), ("ports", "vlan", "vlan_name", "description", "enable"), ("This scenario does not create trunks, link aggregation or server NIC configuration.",)),
    Scenario("uplink", "Switch uplink / trunk", "Set an explicit native VLAN and allowed/tagged VLAN list on selected ports.", (), ("ports", "native", "allowed", "description", "enable"), ("Match native VLAN and tagging on the peer before use.", "Referenced VLANs must already exist on the device or in the draft.")),
    Scenario("unused", "Disable unused ports", "Administratively disable selected ports without changing VLAN membership or PoE configuration.", (), ("ports",), ("Check that selected ports do not carry management or required uplinks.",)),
)


def scenario_by_id(kind, ident):
    for scenario in ROUTER_SCENARIOS if kind == "router" else SWITCH_SCENARIOS:
        if scenario.id == ident: return scenario
    raise ValueError("Unknown provisioning scenario.")


def unavailable(scenario, snapshot):
    driver = DRIVERS[snapshot.platform]()
    missing = set(scenario.requires) - set(driver.capabilities)
    if missing: return "This platform does not provide " + ", ".join(sorted(missing)) + "."
    count = sum(p["editable"] for p in snapshot.interfaces.values())
    minimum = 2 if scenario.id in ("branch", "outbound", "service") else 1
    if count < minimum: return f"Discover at least {minimum} editable routed interface(s) first."
    return ""


def merge_intents(existing, incoming):
    """Never overwrite a user's staged entry or silently combine policy order."""
    merged = deepcopy(existing)
    for section, rows in incoming.to_dict().items():
        target = getattr(merged, section)
        for row in rows:
            identity = "name" if section == "interfaces" else "id"
            previous = next((r for r in target if r[identity] == row[identity]), None)
            if previous is not None:
                if previous != row: raise ValueError(f"Draft conflict: {section} {row[identity]} already has different settings. Remove that entry or choose another identifier.")
            else: target.append(deepcopy(row))
    merged.validate()
    return merged


def merge_switch_changes(existing, incoming):
    merged = deepcopy(existing)
    for number, name in incoming.vlans.items():
        if number in merged.vlans and merged.vlans[number] != name: raise ValueError(f"Draft conflict: VLAN {number} has another staged name.")
        merged.vlans[number] = name
    for name, patch in incoming.ports.items():
        current = merged.ports.setdefault(name, {})
        for field, value in patch.items():
            if field in current and current[field] != value: raise ValueError(f"Draft conflict: {name} already has a different {field}. Discard or edit that change first.")
            current[field] = value
    return merged


def compile_router(ident, values, snapshot, existing=None):
    scenario = scenario_by_id("router", ident)
    reason = unavailable(scenario, snapshot)
    if reason: raise ValueError(reason)
    incoming = Intent()
    driver = DRIVERS[snapshot.platform]()
    def text(key):
        value = values.get(key, "")
        if not isinstance(value, str) or not value.strip(): raise ValueError("Enter " + key.replace("_", " ") + ".")
        return value.strip()
    def checked(key):
        value = values.get(key, False)
        if not isinstance(value, bool): raise ValueError("Invalid option: " + key)
        return value
    def numbered(offset=0):
        value = text("base_id")
        if not value.isascii() or not value.isdigit() or not 1 <= int(value) <= 2147483000: raise ValueError("Starting identifier must be a positive number below 2147483001.")
        return str(int(value) + offset)
    if ident in ("branch", "outbound", "service") and text("lan") == text("wan"):
        raise ValueError("Choose different LAN and WAN interfaces.")
    if ident in ("branch", "routed_lan"):
        incoming.interfaces.append(dict(name=text("lan"), address=text("lan_address")))
    if ident in ("branch", "route") or (ident == "outbound" and checked("add_default")):
        incoming.routes.append(dict(id=numbered(), destination="0.0.0.0/0" if ident == "outbound" else text("destination"), gateway=text("gateway"), interface=text("wan")))
    access = values.get("access", "routing_only")
    if ident == "branch" and access not in ("routing_only", "https", "all"): raise ValueError("Choose a supported access option.")
    make_policy = ident in ("outbound", "service") or (ident == "branch" and access != "routing_only")
    if make_policy:
        if "policies" not in driver.capabilities: raise ValueError("This platform supports routing only; choose Routing only.")
        staged_addresses = {r["name"]: r["address"] for r in (existing or Intent()).interfaces + incoming.interfaces}
        for key in ("lan", "wan"):
            name = text(key)
            if not staged_addresses.get(name, snapshot.interfaces.get(name, {}).get("address")):
                raise ValueError(f"{name} needs a discovered or staged IPv4 address before this traffic scenario.")
        source = str(IPv4Interface(text("lan_address")).network) if ident == "branch" else text("source")
        protocol = ("tcp" if access == "https" else "ip") if ident == "branch" else text("protocol")
        port = ("443" if access == "https" else "") if ident == "branch" else values.get("port", "").strip()
        if protocol not in ("tcp", "udp") and port: raise ValueError("Clear the destination port for ICMP or all-IP traffic.")
        destination = "0.0.0.0/0" if ident == "branch" else text("destination")
        policy = dict(id=numbered(1), source=source, destination=destination, in_interface=text("lan"), out_interface=text("wan"), protocol=protocol, port=port, action=text("action") if ident == "service" else "allow")
        if checked("source_nat"):
            if snapshot.platform == "fortios": policy["nat"] = "enable"
            elif snapshot.platform == "routeros": incoming.nat.append(dict(id=numbered(2), source=source, out_interface=text("wan")))
            else: raise ValueError("Source NAT for this scenario is available only on FortiOS and RouterOS.")
        incoming.policies.append(policy)
    elif checked("source_nat"):
        raise ValueError("Select an access rule before enabling source NAT.")
    if ident == "nat":
        staged_addresses = {r["name"]: r["address"] for r in (existing or Intent()).interfaces}
        wan = text("wan")
        if not staged_addresses.get(wan, snapshot.interfaces.get(wan, {}).get("address")):
            raise ValueError("The NAT egress needs a discovered or staged IPv4 address.")
        incoming.nat.append(dict(id=numbered(), source=text("source"), out_interface=wan))
    merged = merge_intents(existing or Intent(), incoming)
    plan = driver.plan(merged, snapshot)
    return merged, plan.commands, list(scenario.follow_up) + plan.warnings + [plan.persistence]


def compile_switch(ident, values, device, existing=None):
    scenario = scenario_by_id("switch", ident)
    names = values.get("ports", [])
    if not isinstance(names, list) or not names or len(set(names)) != len(names): raise ValueError("Select at least one distinct port.")
    if any(name not in device.ports or not device.ports[name].manageable for name in names): raise ValueError("Select discovered, editable standalone switch ports only.")
    changes = ChangeSet()
    existing = existing or ChangeSet()
    notes = list(scenario.follow_up)
    if ident == "unused": patch = {"enabled": False}
    else:
        description = safe_text(values.get("description", ""))
        patch = {"description": description} if description else {}
        enable = values.get("enable", False)
        if not isinstance(enable, bool): raise ValueError("Invalid enable option.")
        if enable: patch["enabled"] = True
        if ident == "uplink":
            native = vlan_id(values.get("native", ""), device.driver_id in ("cisco_ios", "cisco_nxos"))
            allowed = values.get("allowed", "").strip()
            if allowed in ("all", "none"): raise ValueError("The uplink wizard requires an explicit, nonempty VLAN list.")
            tagged = vlan_set(allowed)
            known = device.vlans | existing.vlans
            if (tagged | {native}) - known.keys(): raise ValueError("Create all native and allowed VLANs before staging the uplink.")
            patch.update(mode="trunk", native_vlan=native, allowed_vlans=allowed)
            if "portfast" in device.capabilities: patch["portfast"] = "disabled"
            if "bpduguard" in device.capabilities: patch["bpduguard"] = "disabled"
            if device.driver_id in ("extreme_exos", "tplink_jetstream"):
                notes.append("Allowed VLANs are tagged memberships on this platform; exclude the native VLAN.")
            notes.append("PortFast and BPDU Guard are disabled on platforms where this driver supports those fields.")
        else:
            number = vlan_id(values.get("vlan", ""), device.driver_id in ("cisco_ios", "cisco_nxos"))
            name = values.get("vlan_name", "").strip()
            known_name = existing.vlans.get(number, device.vlans.get(number))
            if known_name:
                if name and name != known_name: raise ValueError(f"VLAN {number} already uses name {known_name}. Leave the name blank or retain it; this wizard does not rename VLANs.")
            else:
                if not name: raise ValueError("Enter a name for the new VLAN.")
                changes.vlans[number] = name
            patch.update(mode="access", access_vlan=number)
            notes.append("STP, BPDU Guard, voice VLAN, speed, duplex and PoE settings are preserved.")
        if not enable: notes.append("Administrative state is preserved, including any shutdown ports.")
    changes.ports = {name: deepcopy(patch) for name in names}
    merged = merge_switch_changes(existing, changes)
    commands = get_driver(device.driver_id).commands(merged, device)
    return merged, commands, notes + [device.persistence]
