"""Conservative IPv4 drivers. Existing policies/routes are never overwritten."""
from ipaddress import IPv4Interface, IPv4Network
import re
import shlex
from .model import Snapshot, Plan, identifier


def ios_blocks(text):
    result, current = {}, None
    for line in text.splitlines():
        if line and not line[0].isspace():
            current = line.strip()
            result.setdefault(current, [])
        elif current and line.strip(): result[current].append(line.strip())
    return result


def forti_tables(text):
    tables, stack, current = {}, [], None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"): continue
        if line.startswith("config "):
            stack.append((line[7:], current))
            current = None
            if len(stack) == 1: tables.setdefault(line[7:], {})
        elif line.startswith("edit ") and len(stack) == 1:
            key = shlex.split(line)[1]
            current = tables[stack[0][0]].setdefault(key, {})
        elif line.startswith("set ") and len(stack) == 1:
            if current is None: current = tables[stack[0][0]].setdefault("__settings__", {})
            parts = shlex.split(line)
            current[parts[1]] = parts[2:]
        elif line.startswith("config "): pass
        elif line == "next": current = None
        elif line == "end":
            if not stack: raise ValueError("Unbalanced FortiOS configuration.")
            _, current = stack.pop()
    if stack: raise ValueError("Incomplete FortiOS configuration.")
    return tables


def routeros_rows(text):
    rows, section = {}, ""
    text = re.sub(r"\\\s*\n\s*", "", text)
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"): continue
        if line.startswith("/"):
            section = line
            rows.setdefault(section, [])
        elif line.startswith(("add ", "set ")):
            parts = shlex.split(line)
            values = {p.split("=", 1)[0]: p.split("=", 1)[1] for p in parts[1:] if "=" in p and not p.startswith("[find")}
            rows.setdefault(section, []).append(values)
    return rows


class Driver:
    capabilities = ("interfaces", "routes", "policies")
    persistence = "Running configuration only; save startup configuration manually."
    setup = ()
    end = ()

    def normalize(self, text):
        return "\n".join(line.rstrip() for line in text.splitlines()
                         if line.strip() and not re.match(r"^(?:#|Building configuration|Current configuration|! Last configuration|! NVRAM)", line))

    def error(self, text):
        return bool(re.search(r"(?im)^(?:%\s*(?:Invalid|Error|Incomplete|Ambiguous)|(?:error|failure|syntax error|bad command name|expected end of command|command parse error|command fail|value parse error|entry not found|input does not match|not enough permissions|permission denied)\b)", text))

    def preflight(self, intent, snapshot):
        intent.validate()
        if self.id != "fortios" and any(r.get("nat") == "enable" for r in intent.policies):
            raise ValueError("Policy source NAT is supported only on FortiOS; use a separate RouterOS NAT entry.")
        if snapshot.platform != self.id: raise ValueError("Draft platform does not match the connected device.")
        for kind in ("interfaces", "routes", "policies", "nat", "services"):
            if getattr(intent, kind) and kind not in self.capabilities: raise ValueError(f"{self.label} does not support {kind} provisioning.")
        for row in intent.interfaces:
            if row["name"] not in snapshot.interfaces or not snapshot.interfaces[row["name"]]["editable"]:
                raise ValueError(f"{row['name']}: only discovered standalone routed interfaces are editable.")
        for row in intent.routes + intent.policies + intent.nat:
            for key in ("interface", "in_interface", "out_interface"):
                if key in row and (row[key] not in snapshot.interfaces or not snapshot.interfaces[row[key]]["editable"]):
                    raise ValueError(f"{row[key]}: unsupported or undiscovered routed interface.")
        networks = {}
        updates = {r["name"]: r["address"] for r in intent.interfaces}
        for name, item in snapshot.interfaces.items():
            cidr = updates.get(name, item.get("address"))
            if cidr:
                net = IPv4Interface(cidr).network
                if any(net.overlaps(other) for other in networks.values()): raise ValueError("Overlapping interface subnets are not supported.")
                networks[name] = net
        for row in intent.routes:
            from ipaddress import IPv4Address
            gateway = IPv4Address(row["gateway"])
            net = networks.get(row["interface"])
            if net is None or gateway not in net: raise ValueError("The next hop must be on the selected interface's configured subnet.")
            if str(gateway) == str(IPv4Interface(updates.get(row["interface"], snapshot.interfaces[row["interface"]].get("address"))).ip):
                raise ValueError("The next hop cannot be this device's own address.")
            if net.prefixlen < 31 and gateway in (net.network_address, net.broadcast_address): raise ValueError("Invalid next-hop host address.")

    def plan(self, intent, snapshot):
        self.preflight(intent, snapshot)
        commands, expected = self.build(intent, snapshot)
        if intent.services:
            from .network_services import build, build_junos, build_routeros
            if self.id == "routeros":
                service_commands, service_expected = build_routeros(intent.services, snapshot, intent.interfaces, intent.routes)
                commands += service_commands
                for section, entries in service_expected.items():
                    if set(expected.get(section, {})) & set(entries): raise ValueError("Conflicting VPN and draft identifiers.")
                    expected.setdefault(section, {}).update(entries)
            elif self.id == "junos_routing":
                service_commands, service_expected = build_junos(intent.services, snapshot)
                commands = commands[:-3] + service_commands + commands[-3:]
                expected["lines"].update(service_expected)
            else:
                service_commands, service_expected = build(intent.services, snapshot, intent.interfaces)
                commands = commands[:-1] + service_commands + ["end"]
                expected["service_lines"] = service_expected
        warnings = ["Experimental driver: synthetic tests only; no physical hardware qualification.",
                    "Changes can interrupt management and traffic. No automatic rollback or connectivity guarantee."]
        if intent.policies: warnings += self.policy_warnings
        if intent.nat: warnings.append("Source NAT is appended after existing NAT rules; earlier rules may take precedence.")
        if intent.services:
            warnings += ["Network services are feature-specific and require model/firmware/license qualification.",
                         "DHCP may compete with another server; OSPF can learn routes and change traffic paths. DNS/NTP reachability and IPv6 security policy are not verified.",
                         "Existing interface administrative state is preserved. IOS IPv6 forwarding must already be enabled."]
            if self.id == "routeros": warnings += ["WireGuard creates a local key pair on the router; configure its public key and return routing on the remote peer. No private key is supplied in the draft.", "Configure endpoint UDP input permission and tunnel forwarding policy separately. No firewall bypass, NAT, keepalive or handshake verification is added."]
        return Plan(snapshot, intent, commands, expected, warnings, self.persistence)

    def verify(self, plan, after):
        errors = []
        for name, expected in plan.expected.get("interfaces", {}).items():
            if after.interfaces.get(name, {}).get("address") != expected or not after.interfaces.get(name, {}).get("editable"):
                errors.append(f"Interface {name}: standalone IPv4 address not confirmed")
        for section, entries in plan.expected.items():
            if section == "interfaces": continue
            actual = after.facts.get(section, {})
            for key, wanted in entries.items():
                found = actual.get(key)
                if found is None or any(found.get(k) != v for k, v in wanted.items()): errors.append(f"{section} {key}: configuration not confirmed")
        return errors


class IOSRouter(Driver):
    capabilities = ("interfaces", "routes", "policies", "services")
    id, label, ssh_type = "ios_router", "Cisco IOS / IOS-XE — routing + ACL", "cisco_ios"
    identity_command, running_command = "show version", "show running-config"
    setup, end = ("terminal length 0",), ("end",)
    policy_warnings = ["IOS ACLs are stateless, not a stateful firewall. Each new ACL is attached inbound and ends in implicit deny.",
                       "The egress interface is validated for planning but IOS interface ACLs do not match egress; the rule matches the specified destination prefix."]

    def matches(self, text): return bool(re.search(r"Cisco IOS|IOS[- ]XE", text, re.I))

    def parse(self, running, identity, extra=""):
        if not self.matches(identity) or not re.search(r"(?m)^end\s*$", running): raise ValueError("Not a complete IOS configuration.")
        blocks = ios_blocks(running)
        ports, facts = {}, {"routes": {}, "acls": {}, "bindings": {}}
        from .network_services import facts as service_facts
        facts["service_lines"] = service_facts(blocks)
        for header, lines in blocks.items():
            if header.startswith("interface "):
                name = header[10:]
                ip = next((re.fullmatch(r"ip address (\S+) (\S+)", line) for line in lines if re.fullmatch(r"ip address (\S+) (\S+)", line)), None)
                cidr = str(IPv4Interface(ip[1] + "/" + ip[2])) if ip else None
                unsupported = any(re.match(r"(?:switchport(?:\s|$)|(?:ip )?vrf|channel-group|ip unnumbered|ip address .* (?:secondary|dhcp)|encapsulation|service instance|zone-member|ip policy)", l) for l in lines)
                unsupported |= any(l.startswith("ip address") and not re.fullmatch(r"ip address \S+ \S+", l) for l in lines)
                physical = bool(re.fullmatch(r"(?:GigabitEthernet|TenGigabitEthernet|FastEthernet|Ethernet)\d+(?:/\d+){0,2}", name))
                ports[name] = dict(address=cidr, editable=physical and not unsupported and (bool(ip) or "no switchport" in lines), lines=lines)
                for line in lines:
                    m = re.fullmatch(r"ip access-group (\S+) (in|out)", line)
                    if m: facts["bindings"][name + ":" + m[2]] = {"acl": m[1]}
            elif header.startswith("ip route "):
                facts["routes"][header] = {"line": header}
            elif header.startswith("ip access-list extended "):
                # IOS may display automatic sequence numbers; retain rule ordering.
                facts["acls"][header.split()[-1]] = {"rules": [re.sub(r"^\d+ ", "", l) for l in lines]}
        if not ports: raise ValueError("No routed interfaces recognized.")
        host = re.search(r"(?m)^hostname (\S+)", running)
        return Snapshot(self.id, host[1] if host else "IOS router", running, ports, facts)

    def build(self, intent, snap):
        commands, expected = ["configure terminal"], {"interfaces": {}, "routes": {}, "acls": {}, "bindings": {}}
        for row in intent.interfaces:
            ip = IPv4Interface(row["address"])
            commands += ["interface " + row["name"], f"ip address {ip.ip} {ip.netmask}", "exit"]
            expected["interfaces"][row["name"]] = row["address"]
        for row in intent.routes:
            net = IPv4Network(row["destination"])
            if any(key.startswith(f"ip route {net.network_address} {net.netmask} ") for key in snap.facts["routes"]): raise ValueError("A route for this prefix already exists; replacement is not supported.")
            cmd = f"ip route {net.network_address} {net.netmask} {row['interface']} {row['gateway']}"
            if cmd in expected["routes"]: raise ValueError("Duplicate route prefix.")
            commands.append(cmd)
            expected["routes"][cmd] = {"line": cmd}
        used_interfaces = set()
        for row in intent.policies:
            acl = "VSC_" + row["id"]
            interface = row["in_interface"]
            if acl in snap.facts["acls"] or interface + ":in" in snap.facts["bindings"] or interface in used_interfaces:
                raise ValueError("An inbound ACL already exists, or multiple new ACLs target this interface. No ACL will be overwritten.")
            used_interfaces.add(interface)
            def match(cidr):
                n = IPv4Network(cidr)
                return "any" if n.prefixlen == 0 else f"{n.network_address} {n.hostmask}"
            line = f"{'permit' if row['action'] == 'allow' else 'deny'} {row['protocol']} {match(row['source'])} {match(row['destination'])}"
            if row["port"]: line += " eq " + str(int(row["port"]))
            commands += ["ip access-list extended " + acl, line, "exit", "interface " + interface, "ip access-group " + acl + " in", "exit"]
            expected["acls"][acl] = {"rules": [line]}
            expected["bindings"][interface + ":in"] = {"acl": acl}
        return commands + ["end"], expected


class FortiOS(Driver):
    id, label, ssh_type = "fortios", "Fortinet FortiOS — routing + firewall", "fortinet"
    capabilities = ("interfaces", "routes", "policies")
    identity_command, running_command = "get system status", "show full-configuration"
    end = ("end",)
    persistence = "FortiOS writes changes immediately and persists them automatically in automatic-save mode."
    policy_warnings = ["New policies are appended after existing policies. Earlier matching rules take precedence.",
                       "Only standalone NAT-mode, single-VDOM, profile-based policies are supported. Central SNAT, HA and managed configurations are excluded."]

    def matches(self, text): return bool(re.search(r"Version: Forti(?:Gate|WiFi).*v7\.", text))

    def parse(self, running, identity, extra=""):
        if not self.matches(identity): raise ValueError("Expected FortiOS 7.x identity.")
        if not re.search(r"(?im)^Virtual domain configuration:\s*disable", identity) or not re.search(r"(?im)^Current HA mode:\s*standalone", identity):
            raise ValueError("FortiOS requires standalone mode and disabled VDOMs.")
        if not re.search(r"(?im)^Operation Mode:\s*NAT", identity): raise ValueError("Only FortiOS NAT operation mode is supported.")
        if re.search(r"set (?:central-nat enable|ngfw-mode policy-based|cfg-save (?:manual|revert)|type fortimanager)", running):
            raise ValueError("Central NAT, policy-based NGFW, manual-save and FortiManager-managed configurations are unsupported.")
        tables = forti_tables(running)
        if "system interface" not in tables: raise ValueError("Missing interface configuration.")
        # Features whose interface ownership cannot be safely inferred by this driver.
        blocked = bool(tables.get("system zone") or tables.get("system switch-interface") or tables.get("system virtual-switch") or tables.get("system sdwan", {}).get("__settings__", {}).get("status") == ["enable"])
        ports = {}
        for name, item in tables["system interface"].items():
            ip = item.get("ip", ["0.0.0.0", "0.0.0.0"])
            cidr = str(IPv4Interface("/".join(ip))) if ip[0] != "0.0.0.0" else None
            editable = not blocked and item.get("type") == ["physical"] and item.get("mode", ["static"]) == ["static"] and item.get("vrf", ["0"]) == ["0"] and item.get("secondary-IP", ["disable"]) == ["disable"]
            ports[name] = dict(address=cidr, editable=editable)
        host = re.search(r'(?m)^\s*set hostname "?([^"\n]+)', running)
        return Snapshot(self.id, host[1] if host else "FortiGate", running, ports, tables)

    def build(self, intent, snap):
        commands, expected = [], {"interfaces": {}}
        def add(table, key, values):
            if key in snap.facts.get(table, {}) or key in expected.get(table, {}): raise ValueError(f"{table} {key} already exists; objects are never overwritten.")
            commands.extend(["config " + table, 'edit "' + key + '"'])
            for k, v in values.items(): commands.append("set " + k + " " + " ".join('"' + x + '"' for x in v))
            commands.extend(["next", "end"])
            expected.setdefault(table, {})[key] = values
        for row in intent.interfaces:
            ip = IPv4Interface(row["address"])
            commands += ["config system interface", 'edit "' + row["name"] + '"', f"set ip {ip.ip} {ip.netmask}", "next", "end"]
            expected["interfaces"][row["name"]] = row["address"]
        for row in intent.routes:
            if not row["id"].isdigit() or not 1 <= int(row["id"]) <= 4294967295 or str(int(row["id"])) != row["id"]: raise ValueError("FortiOS route/policy IDs must be canonical positive integers.")
            net = IPv4Network(row["destination"])
            if any(v.get("dst", ["0.0.0.0", "0.0.0.0"]) == [str(net.network_address), str(net.netmask)] for v in snap.facts.get("router static", {}).values()): raise ValueError("A static route for this prefix already exists.")
            add("router static", row["id"], {"dst": [str(net.network_address), str(net.netmask)], "gateway": [row["gateway"]], "device": [row["interface"]], "status": ["enable"], "distance": ["10"]})
        if intent.nat: raise ValueError("Use the source NAT option on a FortiOS policy rather than a standalone NAT entry.")
        for row in intent.policies:
            ident = row["id"]
            if not ident.isdigit() or not 1 <= int(ident) <= 4294967295 or str(int(ident)) != ident: raise ValueError("FortiOS policy IDs must be canonical positive integers.")
            names = []
            for suffix, cidr in (("src", row["source"]), ("dst", row["destination"])):
                net = IPv4Network(cidr)
                name = f"VSC_{ident}_{suffix}"
                add("firewall address", name, {"type": ["ipmask"], "subnet": [str(net.network_address), str(net.netmask)]})
                names.append(name)
            service = "ALL" if row["protocol"] == "ip" else "ALL_ICMP"
            if row["protocol"] in ("tcp", "udp"):
                service = "VSC_" + ident + "_svc"
                add("firewall service custom", service, {"protocol": ["TCP/UDP/SCTP"], row["protocol"] + "-portrange": [row["port"] or "1-65535"]})
            add("firewall policy", ident, {"name": ["VSC_" + ident], "srcintf": [row["in_interface"]], "dstintf": [row["out_interface"]], "srcaddr": [names[0]], "dstaddr": [names[1]], "action": ["accept" if row["action"] == "allow" else "deny"], "schedule": ["always"], "service": [service], "nat": [row.get("nat", "disable")], "status": ["enable"], "logtraffic": ["all"]})
        return commands, expected


class RouterOS(Driver):
    id, label, ssh_type = "routeros", "MikroTik RouterOS 7 — routing + firewall + NAT", "mikrotik_routeros"
    capabilities = ("interfaces", "routes", "policies", "nat", "services")
    identity_command, running_command = "/system resource print", "/export terse"
    persistence = "RouterOS applies and persists each change immediately."
    policy_warnings = ["Forward-chain filter rules are appended. Existing rules, FastTrack and established connections can take precedence.", "No default-deny or stateful baseline is installed automatically; review the complete existing ruleset."]

    def matches(self, text): return bool(re.search(r"(?m)^\s*version:\s*7\.", text))

    def parse(self, running, identity, extra=""):
        if not self.matches(identity): raise ValueError("Expected RouterOS 7.x identity.")
        # Terse exports repeat the section prefix on each command; expand to section+row.
        expanded = re.sub(r"(?m)^(/[^\n]*?) (add|set) ", r"\1\n\2 ", running)
        rows = routeros_rows(expanded)
        if not running.startswith("#") or not extra.strip(): raise ValueError("Incomplete RouterOS export or interface inventory.")
        ports = {}
        for name in re.findall(r'(?<![\w-])name=(?:"([^"]+)"|(\S+))', extra):
            key = name[0] or name[1]
            if re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.:/-]{0,62}", key): ports[key] = dict(address=None, editable=True)
        blocked = {r.get("interface") for section in ("/interface bridge port", "/ip dhcp-client") for r in rows.get(section, [])}
        if rows.get("/ip vrf") or rows.get("/interface bonding") or rows.get("/interface vrrp"):
            blocked.update(ports)
        for row in rows.get("/ip address", []):
            name = row.get("interface")
            if name in ports:
                if ports[name]["address"] or row.get("disabled") == "yes" or row.get("network") not in (None, str(IPv4Interface(row["address"]).network.network_address)): blocked.add(name)
                ports[name]["address"] = row.get("address")
        for name in blocked:
            if name in ports: ports[name]["editable"] = False
        if not ports: raise ValueError("No interface names recognized.")
        facts = {}
        for section, items in rows.items():
            defaults = {"/ip address": {"disabled": "no"}, "/ip route": {"disabled": "no", "routing-table": "main", "distance": "1", "dst-address": "0.0.0.0/0"}, "/ip firewall filter": {"disabled": "no"}, "/ip firewall nat": {"disabled": "no"}}
            items = [defaults.get(section, {}) | r for r in items]
            if section in ("/interface wireguard", "/interface wireguard peers"):
                items = [{"disabled": "no"} | r for r in items]
            if section == "/interface wireguard": items = [{"listen-port": "13231"} | r for r in items]
            facts[section] = {r.get("comment", "unmanaged-" + str(i)): r for i, r in enumerate(items)}
        return Snapshot(self.id, "RouterOS", running, ports, facts)

    def build(self, intent, snap):
        commands, expected = [], {"interfaces": {}}
        def add(section, row):
            key = row["comment"]
            if key in snap.facts.get(section, {}) or key in expected.get(section, {}): raise ValueError("An object with this VSC identifier already exists.")
            commands.append(section + " add " + " ".join(k + "=" + v for k, v in row.items()))
            expected.setdefault(section, {})[key] = row
        for row in intent.interfaces:
            if snap.interfaces[row["name"]]["address"]: raise ValueError("RouterOS adds addresses only to unaddressed interfaces; replacement is not supported.")
            add("/ip address", {"address": row["address"], "interface": row["name"], "comment": "VSC_" + row["name"], "disabled": "no"})
            expected["interfaces"][row["name"]] = row["address"]
        for row in intent.routes:
            if any(r.get("dst-address", "0.0.0.0/0") == row["destination"] for r in snap.facts.get("/ip route", {}).values()): raise ValueError("A static route for this prefix already exists.")
            add("/ip route", {"dst-address": row["destination"], "gateway": row["gateway"] + "%" + row["interface"], "distance": "1", "routing-table": "main", "disabled": "no", "comment": "VSC_" + row["id"]})
        for row in intent.policies:
            values = {"chain": "forward", "src-address": row["source"], "dst-address": row["destination"], "in-interface": row["in_interface"], "out-interface": row["out_interface"], "action": "accept" if row["action"] == "allow" else "drop", "disabled": "no", "comment": "VSC_" + row["id"]}
            if row["protocol"] != "ip": values["protocol"] = row["protocol"]
            if row["port"]: values["dst-port"] = str(int(row["port"]))
            add("/ip firewall filter", values)
        for row in intent.nat:
            add("/ip firewall nat", {"chain": "srcnat", "src-address": row["source"], "out-interface": row["out_interface"], "action": "masquerade", "disabled": "no", "comment": "VSC_" + row["id"]})
        return commands, expected

class ArubaRouting(Driver):
    id, label, ssh_type = "aruba_routing", "Aruba AOS-CX — routed ports + static routes", "aruba_aoscx"
    capabilities = ("interfaces", "routes")
    identity_command, running_command = "show version", "show running-config"
    setup, end = ("no page",), ("end",)

    def matches(self, text): return bool(re.search(r"ArubaOS-CX|AOS-CX", text))

    def parse(self, running, identity, extra=""):
        if not self.matches(identity): raise ValueError("Expected AOS-CX identity.")
        ports, routes = {}, {}
        for head, lines in ios_blocks(running).items():
            if head.startswith("interface "):
                name = head[10:]
                ips = [l[11:] for l in lines if l.startswith("ip address ")]
                editable = bool(re.fullmatch(r"\d+/\d+/\d+", name)) and "routing" in lines and len(ips) <= 1 and not any(re.match(r"vrf attach|lag |apply |ip address .*secondary", l) for l in lines)
                cidr = str(IPv4Interface(ips[0])) if ips and editable else None
                ports[name] = dict(address=cidr, editable=editable, lines=lines)
            elif head.startswith("ip route "): routes[head] = {"line": head}
        if not ports: raise ValueError("No AOS-CX interfaces recognized.")
        host = re.search(r"(?m)^hostname (\S+)", running)
        return Snapshot(self.id, host[1] if host else "AOS-CX", running, ports, {"routes": routes})

    def build(self, intent, snap):
        commands, expected = ["configure terminal"], {"interfaces": {}, "routes": {}}
        for row in intent.interfaces:
            commands.append("interface " + row["name"])
            old = snap.interfaces[row["name"]].get("address")
            if old and old != row["address"]: commands.append("no ip address " + old)
            commands += ["ip address " + row["address"], "exit"]
            expected["interfaces"][row["name"]] = row["address"]
        for row in intent.routes:
            prefix = "ip route " + row["destination"] + " "
            if any(k.startswith(prefix) for k in snap.facts["routes"]): raise ValueError("A static route for this prefix already exists.")
            line = prefix + row["gateway"]
            commands.append(line)
            expected["routes"][line] = {"line": line}
        return commands + ["end"], expected


class JunosRouting(Driver):
    capabilities = ("interfaces", "routes", "policies", "services")
    id, label, ssh_type = "junos_routing", "Juniper Junos — routing + SRX policies", "juniper_junos"
    identity_command, running_command = "show version", "show configuration | display set | no-more"
    setup = ("set cli screen-length 0", "set cli screen-width 511")
    persistence = "Junos commit applies the candidate configuration and persists it across reboot."
    policy_warnings = ["SRX policies require existing security zones and global address-book support. New policies are appended; earlier rules take precedence."]

    def matches(self, text): return bool(re.search(r"Junos:|JUNOS Software", text))

    def parse(self, running, identity, extra=""):
        if not self.matches(identity) or not running.startswith("set "): raise ValueError("Expected Junos display-set configuration.")
        lines = [shlex.join(shlex.split(l)) for l in running.splitlines() if l.strip()]
        ports, zones = {}, {}
        inherited = bool(re.search(r"(?m)^(?:set (?:apply-groups|groups|routing-instances)|deactivate|set interfaces interface-range)", running))
        for line in running.splitlines():
            m = re.match(r"set interfaces ((?:ge|xe|et)-\d+/\d+/\d+) ", line)
            if m: ports.setdefault(m[1], dict(address=None, editable=not inherited, lines=[]))["lines"].append(line)
            z = re.fullmatch(r"set security zones security-zone (\S+) interfaces (\S+)", line)
            if z: zones[z[2]] = z[1]
        for name, item in ports.items():
            prefix = "set interfaces " + name + " "
            own = item["lines"]
            ips = [l.split()[-1] for l in own if re.fullmatch(re.escape(prefix) + r"unit 0 family inet address \S+", l)]
            unsupported = any(re.search(r"family (?:ethernet-switching|bridge)|802.3ad|unit [1-9]|vlan-tagging|flexible-vlan|unnumbered|dhcp", l) for l in own)
            if len(ips) > 1 or unsupported: item["editable"] = False
            if ips: item["address"] = str(IPv4Interface(ips[0]))
        if not ports: raise ValueError("No standalone Junos interfaces recognized.")
        host = re.search(r"(?m)^set system host-name (\S+)", running)
        return Snapshot(self.id, host[1] if host else "Junos", running, ports,
                        {"lines": {line: {"present": True} for line in lines}, "zones": zones, "srx": bool(re.search(r"(?i)Model: srx", identity))})

    def build(self, intent, snap):
        commands = ["configure exclusive", "show | compare", "run " + self.running_command]
        expected = {"interfaces": {}, "lines": {}}
        def add(line):
            commands.append(line)
            expected["lines"][shlex.join(shlex.split(line))] = {"present": True}
        for row in intent.interfaces:
            base = "interfaces " + row["name"] + " unit 0 family inet address "
            old = snap.interfaces[row["name"]]["address"]
            if old and old != row["address"]: commands.append("delete " + base + old)
            add("set " + base + row["address"])
            expected["interfaces"][row["name"]] = row["address"]
        for row in intent.routes:
            prefix = "set routing-options static route " + row["destination"] + " "
            if any(l.startswith(prefix) for l in snap.facts["lines"]): raise ValueError("A route for this prefix already exists.")
            add(prefix + "next-hop " + row["gateway"])
        for row in intent.policies:
            if not snap.facts["srx"]: raise ValueError("Security policies require an SRX platform.")
            zones = snap.facts["zones"]
            src, dst = zones.get(row["in_interface"] + ".0"), zones.get(row["out_interface"] + ".0")
            if not src or not dst or src == dst: raise ValueError("Select interfaces in two existing distinct security zones.")
            identifier(src); identifier(dst)
            name = "VSC_" + row["id"]
            if name in snap.running or re.search(r"set security (?:zones .* address-book|address-book (?!global))", snap.running):
                raise ValueError("Identifier already exists or zone-specific address books are present.")
            add(f"set security address-book global address {name}_src {row['source']}")
            add(f"set security address-book global address {name}_dst {row['destination']}")
            application = "any" if row["protocol"] == "ip" else "junos-icmp-all"
            if row["protocol"] in ("tcp", "udp"):
                application = name + "_app"
                add(f"set applications application {application} protocol {row['protocol']}")
                add(f"set applications application {application} destination-port {row['port'] or '1-65535'}")
            base = f"set security policies from-zone {src} to-zone {dst} policy {name} "
            add(base + "match source-address " + name + "_src")
            add(base + "match destination-address " + name + "_dst")
            add(base + "match application " + application)
            add(base + "then " + ("permit" if row["action"] == "allow" else "deny"))
        return commands + ["commit check", "commit", "exit"], expected

    def deploy(self, service, plan):
        self.locked, self.owned = False, False
        for command in plan.commands:
            output = service.execute(command)
            if command == "configure exclusive":
                if "Entering configuration mode" not in output: raise RuntimeError("Junos exclusive lock not confirmed.")
                self.locked = True
            elif command == "show | compare":
                if output.strip(): raise RuntimeError("Existing Junos candidate changes; nothing staged or committed.")
                self.owned = True
            elif command == "run " + self.running_command:
                if self.normalize(output) != self.normalize(plan.snapshot.running): raise RuntimeError("Active configuration changed before exclusive lock.")
            elif command == "commit check" and "configuration check succeeds" not in output: raise RuntimeError("Commit check did not confirm success.")
            elif command == "commit":
                if "commit complete" not in output: raise RuntimeError("Commit outcome unknown; inspect the device.")
                self.owned = False
            elif command == "exit": self.locked = False

    def recover(self, service):
        if getattr(self, "locked", False):
            if self.owned: service.execute("rollback 0")
            if service.execute("show | compare").strip(): raise RuntimeError("Candidate retained; exit manually without committing.")
            service.execute("exit")
            self.locked = False


class DiscoveryOnly(Driver):
    read_only = True
    capabilities = ()
    persistence = "Discovery only. Managed provisioning is not implemented for this OS."
    def parse(self, running, identity, extra=""):
        if not self.matches(identity) or not running.strip() or self.error(running): raise ValueError("Identity or configuration output was not recognized.")
        return Snapshot(self.id, self.label, running, {}, {})
    def plan(self, intent, snapshot): raise ValueError(self.persistence)


class PANOS(DiscoveryOnly):
    id, label, ssh_type = "panos", "Palo Alto PAN-OS — discovery only", "paloalto_panos"
    identity_command, running_command = "show system info", "show config running"
    def matches(self, text): return bool(re.search(r"(?m)^sw-version:\s*\d", text) and re.search(r"(?m)^model:", text))


class CheckPoint(DiscoveryOnly):
    id, label, ssh_type = "checkpoint", "Check Point Gaia — discovery only", "checkpoint_gaia"
    identity_command, running_command = "show version all", "show configuration"
    def matches(self, text): return bool(re.search(r"Check Point|Gaia", text, re.I))


class SonicWall(DiscoveryOnly):
    id, label, ssh_type = "sonicwall", "SonicWall SonicOS — discovery only", "terminal_server"
    identity_command, running_command = "show version", "show current-config"
    def matches(self, text): return bool(re.search(r"SonicOS|SonicWall", text, re.I))


DRIVERS = {d.id: d for d in (IOSRouter, FortiOS, PANOS, JunosRouting, CheckPoint, ArubaRouting, SonicWall, RouterOS)}
