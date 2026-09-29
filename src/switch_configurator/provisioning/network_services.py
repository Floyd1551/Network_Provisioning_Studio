"""Conservative IOS service plans with semantic configuration readback."""
import re
from ipaddress import IPv4Address, IPv4Interface, IPv4Network, IPv6Address, IPv6Interface, IPv6Network
from .model import address, identifier

SCHEMAS = {
    "dns": ("DNS resolver", (("server", "DNS server IPv4"),)),
    "ntp": ("NTP client", (("server", "NTP server IPv4"),)),
    "ipv6": ("IPv6 interface", (("interface", "Routed interface"), ("address", "IPv6 address / prefix"))),
    "route6": ("IPv6 static route", (("destination", "IPv6 destination / prefix"), ("interface", "Outgoing interface"), ("gateway", "Directly connected IPv6 next hop"))),
    "dhcp": ("DHCP server pool", (("interface", "Existing LAN interface"), ("start", "First lease IPv4"), ("end", "Last lease IPv4"), ("server", "Client DNS server IPv4"))),
    "ospf": ("OSPFv2 single-area neighbor", (("process", "New process ID (1–65535)"), ("router_id", "Router ID (IPv4)"), ("interface", "Adjacency interface"), ("area", "Area ID (dotted decimal)"))),
    "svi": ("Existing VLAN interface IPv4", (("interface", "Existing unaddressed VLAN interface"), ("address", "IPv4 address / prefix"))),
    "wireguard": ("WireGuard VPN peer + route", (("address", "Local tunnel IPv4 / prefix"), ("remote_network", "Remote IPv4 network / prefix"), ("public_key", "Remote peer public key (base64)"), ("endpoint", "Remote endpoint IPv4"), ("listen_port", "Local UDP listen port"), ("endpoint_port", "Remote UDP port"))),
}


def validate(rows):
    if not isinstance(rows, list) or len(rows) > 100: raise ValueError("Use at most 100 service entries.")
    ids = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("type") not in SCHEMAS: raise ValueError("Unknown network service.")
        keys = {"id", "type"} | {k for k, _ in SCHEMAS[row["type"]][1]}
        if set(row) != keys or any(not isinstance(v, str) for v in row.values()): raise ValueError("Invalid network service fields.")
        identifier(row["id"])
        if row["id"] in ids: raise ValueError("Duplicate service identifier.")
        ids.add(row["id"])
        if "interface" in row: identifier(row["interface"])
        for key in ("server", "start", "end", "router_id"):
            if key in row: address(row[key])
        if row["type"] == "ospf":
            if not re.fullmatch(r"[1-9][0-9]{0,4}", row["process"]) or int(row["process"]) > 65535: raise ValueError("OSPF process must be 1–65535.")
            IPv4Address(row["area"])
        if row["type"] in ("svi", "wireguard"):
            ip = IPv4Interface(row["address"]); address(str(ip.ip))
            if str(ip) != row["address"] or (ip.network.prefixlen < 31 and ip.ip in (ip.network.network_address, ip.network.broadcast_address)):
                raise ValueError("Use a canonical IPv4 host address/prefix.")
        if row["type"] == "wireguard":
            import base64
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}", row["id"]): raise ValueError("VPN identifier must use 1–32 letters, digits, underscore or hyphen.")
            address(row["endpoint"])
            net = IPv4Network(row["remote_network"])
            if str(net) != row["remote_network"] or net.prefixlen == 0: raise ValueError("Use a canonical remote network; full-tunnel default routes require a separate plan.")
            for field in ("listen_port", "endpoint_port"):
                if not re.fullmatch(r"[1-9][0-9]{0,4}", row[field]) or int(row[field]) > 65535: raise ValueError("UDP ports must be 1–65535.")
            try: key = base64.b64decode(row["public_key"], validate=True)
            except ValueError: raise ValueError("Enter a valid WireGuard public key.") from None
            if len(key) != 32 or key == bytes(32) or base64.b64encode(key).decode() != row["public_key"]: raise ValueError("WireGuard public keys must encode 32 bytes canonically.")
        if row["type"] == "ipv6":
            ip = IPv6Interface(row["address"])
            if str(ip) != row["address"] or ip.ip.is_multicast or ip.ip.is_unspecified or ip.ip.is_loopback or ip.ip.is_link_local:
                raise ValueError("Use a canonical unicast IPv6 address/prefix, excluding link-local.")
        if row["type"] == "route6":
            net, gateway = IPv6Network(row["destination"]), IPv6Address(row["gateway"])
            if str(net) != row["destination"] or str(gateway) != row["gateway"] or gateway.is_multicast or gateway.is_unspecified or gateway.is_loopback:
                raise ValueError("Use canonical IPv6 prefix and unicast next hop.")


def facts(blocks):
    """Normalize merged DNS lines and IPv6 casing from IOS show running-config."""
    values = {}
    for header, lines in blocks.items():
        if header.startswith("ip name-server "):
            for server in header.split()[2:]: values["ip name-server " + server] = {"present": True}
        else:
            key = header
            if header.startswith("ipv6 route "):
                parts = header.split()
                parts = [p.lower() if ":" in p else p for p in parts]
                key = " ".join(parts)
            values[key] = {"present": True}
        for line in lines:
            if line.startswith("ipv6 address "): line = line.lower()
            values[header + " | " + line] = {"present": True}
    return values


def eligible(snapshot, name):
    item = snapshot.interfaces.get(name, {})
    if item.get("editable"): return True
    if not re.fullmatch(r"Vlan[1-9][0-9]{0,3}", name) or int(name[4:]) > 4094: return False
    lines = item.get("lines", [])
    if any(re.match(r"(?:ip )?vrf|ip unnumbered|ip address.*(?:secondary|dhcp)|ip policy|zone-member|service instance", line) for line in lines): return False
    if any(line.startswith("ip address ") and not re.fullmatch(r"ip address [0-9.]+ [0-9.]+", line) for line in lines): return False
    return len([line for line in lines if line.startswith("ip address ")]) <= 1


def build(rows, snapshot, interface_updates):
    if any(r["type"] == "wireguard" for r in rows): raise ValueError("WireGuard provisioning is available only on RouterOS 7.")
    from .drivers import ios_blocks
    blocks = ios_blocks(snapshot.running)
    commands, expected, claimed = [], {}, set()
    addresses = {name: port.get("address") for name, port in snapshot.interfaces.items()}
    addresses.update({r["name"]: r["address"] for r in interface_updates})
    for row in rows:
        if row["type"] == "svi": addresses[row["interface"]] = row["address"]
    networks = [IPv4Interface(value).network for value in addresses.values() if value]
    if any(a.overlaps(b) for i, a in enumerate(networks) for b in networks[i + 1:]): raise ValueError("Overlapping IPv4 interface networks.")
    def claim(key):
        if key in claimed: raise ValueError("Conflicting service entries: " + key)
        claimed.add(key)
    def add(line, context=None):
        commands.append(line)
        expected[(context + " | " if context else "") + line] = {"present": True}
    def port(row):
        name = row["interface"]
        if name not in snapshot.interfaces or not eligible(snapshot, name):
            raise ValueError("Services require a discovered standalone routed interface or supported SVI.")
        return name
    def ipv4(name):
        if not addresses.get(name): raise ValueError("Configure an IPv4 address on the selected interface first.")
        return IPv4Interface(addresses[name])
    ipv6 = {}
    for name, item in snapshot.interfaces.items():
        ipv6[name] = [IPv6Interface(l.split()[2]) for l in item.get("lines", []) if re.fullmatch(r"ipv6 address [0-9A-Fa-f:]+/\d+", l)]
    for row in rows:
        if row["type"] == "ipv6": ipv6.setdefault(row["interface"], []).append(IPv6Interface(row["address"]))
    if any(row["type"] in ("ipv6", "route6") for row in rows):
        if "ipv6 unicast-routing" not in blocks:
            raise ValueError("IPv6 forwarding must already be enabled. This tool does not globally enable forwarding on existing interfaces.")
    for row in sorted(rows, key=lambda r: 0 if r["type"] in ("svi", "ipv6") else 1):
        kind = row["type"]
        if kind == "svi":
            name = port(row); claim("svi:" + name)
            if not name.startswith("Vlan") or snapshot.interfaces[name].get("address"):
                raise ValueError("Select an existing unaddressed VLAN interface. SVI replacement/creation is not supported.")
            header = "interface " + name; ip = IPv4Interface(row["address"])
            commands.append(header); add(f"ip address {ip.ip} {ip.netmask}", header); commands.append("exit")
        elif kind in ("dns", "ntp"):
            prefix = "ip name-server " if kind == "dns" else "ntp server "
            line = prefix + row["server"]
            claim(line)
            if line in facts(blocks) or any(h.startswith(line + " ") for h in blocks): raise ValueError("That server is already configured.")
            if kind == "ntp" and any(h.startswith(("ntp authenticate", "ntp authentication-key", "ntp trusted-key", "ntp access-group", "ntp source", "ntp master")) for h in blocks):
                raise ValueError("Existing NTP authentication/access/source/master settings require a dedicated plan.")
            if kind == "dns" and any(h.startswith(("ip name-server vrf", "ip domain vrf", "no ip domain lookup", "no ip domain-lookup")) for h in blocks):
                raise ValueError("VRF or disabled DNS lookup is outside this resolver scenario.")
            if kind == "dns":
                servers = {server for h in blocks if h.startswith("ip name-server ") for server in h.split()[2:]}
                servers.update(r["server"] for r in rows if r["type"] == "dns")
                if len(servers) > 6: raise ValueError("This IOS scenario supports at most six DNS resolver addresses.")
            add(line)
        elif kind == "ipv6":
            name = port(row); claim("ipv6:" + name)
            if any(l.startswith("ipv6 address ") for l in snapshot.interfaces[name]["lines"]): raise ValueError("IPv6 address replacement or additional addresses are not supported.")
            new = IPv6Interface(row["address"])
            for other, ips in ipv6.items():
                if other != name and any(new.network.overlaps(ip.network) for ip in ips): raise ValueError("Overlapping IPv6 interface networks.")
            header = "interface " + name
            commands.append(header); add("ipv6 address " + row["address"], header); commands.append("exit")
        elif kind == "route6":
            name = port(row); claim("route6:" + row["destination"])
            if any(h.lower().startswith("ipv6 route " + row["destination"] + " ") for h in blocks): raise ValueError("An IPv6 route for this prefix already exists.")
            gateway = IPv6Address(row["gateway"])
            if not ipv6.get(name): raise ValueError("Configure an explicit IPv6 address on the outgoing interface first.")
            if any(gateway == ip.ip for ips in ipv6.values() for ip in ips): raise ValueError("Next hop cannot be this device's own address.")
            if not gateway.is_link_local and not any(gateway in ip.network for ip in ipv6[name]): raise ValueError("IPv6 next hop must be directly connected.")
            add(f"ipv6 route {row['destination']} {name} {row['gateway']}")
        elif kind == "dhcp":
            name = port(row); ip = ipv4(name); net = ip.network
            claim("dhcp:" + str(net))
            if "no service dhcp" in blocks: raise ValueError("DHCP service is disabled on this device.")
            if net.prefixlen > 29: raise ValueError("DHCP requires a LAN subnet of /29 or larger.")
            lo, hi = IPv4Address(row["start"]), IPv4Address(row["end"])
            if not net.network_address < lo <= hi < net.broadcast_address or lo <= ip.ip <= hi:
                raise ValueError("Lease range must be inside the LAN subnet and exclude the gateway.")
            if any(l.startswith("ip helper-address") for l in snapshot.interfaces[name]["lines"]): raise ValueError("This interface already has DHCP relay configuration.")
            # Existing pools/exclusions can have inherited or complex scope; do not modify their allocation behavior.
            if any(h.startswith(("ip dhcp pool ", "ip dhcp excluded-address ")) for h in blocks): raise ValueError("Existing DHCP pools/exclusions require a dedicated allocation plan.")
            header = "ip dhcp pool VSC_" + row["id"]
            def exclude(first, last):
                add(f"ip dhcp excluded-address {first}" + (f" {last}" if first != last else ""))
            if lo > net.network_address + 1: exclude(net.network_address + 1, lo - 1)
            if hi < net.broadcast_address - 1: exclude(hi + 1, net.broadcast_address - 1)
            commands.append(header)
            add(f"network {net.network_address} {net.netmask}", header)
            add("default-router " + str(ip.ip), header)
            add("dns-server " + row["server"], header)
            commands.append("exit")
        elif kind == "ospf":
            name = port(row); ip = ipv4(name); claim("ospf")
            if any(h.startswith("router ospf ") for h in blocks) or any(l.startswith("ip ospf ") for p in snapshot.interfaces.values() for l in p["lines"]):
                raise ValueError("An existing OSPF configuration requires a dedicated routing plan.")
            if "no ip routing" in blocks: raise ValueError("IPv4 routing is disabled.")
            header = "router ospf " + row["process"]
            commands.append(header)
            add("router-id " + row["router_id"], header)
            add("passive-interface default", header)
            add("no passive-interface " + name, header)
            # Match one exact local address, not every interface in an overlapping wildcard.
            add(f"network {ip.ip} 0.0.0.0 area {int(IPv4Address(row['area']))}", header)
            commands.append("exit")
    return commands, expected


def build_routeros(rows, snapshot, interface_updates, route_updates=()):
    if any(r["type"] != "wireguard" for r in rows): raise ValueError("RouterOS currently supports only the WireGuard service scenario.")
    from .drivers import routeros_rows
    expanded = re.sub(r"(?m)^(/[^\n]*?) (add|set) ", r"\1\n\2 ", snapshot.running)
    existing = routeros_rows(expanded)
    if any(existing.get(section) for section in ("/ip vrf", "/interface bonding", "/interface vrrp")):
        raise ValueError("VRF, bonding or VRRP requires a dedicated VPN plan.")
    networks = [IPv4Interface(p["address"]).network for p in snapshot.interfaces.values() if p.get("address")]
    networks += [IPv4Interface(p["address"]).network for p in interface_updates]
    ports = {r.get("listen-port", "13231") for r in existing.get("/interface wireguard", [])}
    names = set(snapshot.interfaces) | {r.get("name") for r in existing.get("/interface wireguard", [])}
    routes = {r.get("dst-address", "0.0.0.0/0") for r in existing.get("/ip route", [])}
    routes.update(r["destination"] for r in route_updates)
    commands, expected = [], {}
    def add(section, values):
        comment = values["comment"]
        if comment in snapshot.facts.get(section, {}) or comment in expected.get(section, {}): raise ValueError("VPN identifier already exists.")
        commands.append(section + " add " + " ".join(k + "=" + ('"' + v + '"' if k == "public-key" else v) for k, v in values.items()))
        expected.setdefault(section, {})[comment] = values
    for row in rows:
        interface = "VSC_" + row["id"]
        ip, remote = IPv4Interface(row["address"]), IPv4Network(row["remote_network"])
        if interface in names or row["listen_port"] in ports: raise ValueError("VPN interface name or listen port is already in use.")
        if any(ip.network.overlaps(net) or remote.overlaps(net) for net in networks) or ip.ip in remote:
            raise ValueError("VPN local/remote networks overlap an existing or staged network.")
        if IPv4Address(row["endpoint"]) in remote or IPv4Address(row["endpoint"]) in ip.network:
            raise ValueError("The VPN endpoint cannot be reached through the tunnel it establishes.")
        if row["remote_network"] in routes: raise ValueError("A route to this remote network already exists.")
        names.add(interface); ports.add(row["listen_port"]); routes.add(row["remote_network"]); networks.extend([ip.network, remote])
        add("/interface wireguard", {"name": interface, "listen-port": row["listen_port"], "disabled": "no", "comment": interface})
        add("/ip address", {"address": row["address"], "interface": interface, "disabled": "no", "comment": interface + "_addr"})
        add("/interface wireguard peers", {"interface": interface, "public-key": row["public_key"], "allowed-address": row["remote_network"], "endpoint-address": row["endpoint"], "endpoint-port": row["endpoint_port"], "disabled": "no", "comment": interface + "_peer"})
        add("/ip route", {"dst-address": row["remote_network"], "gateway": interface, "distance": "1", "routing-table": "main", "disabled": "no", "comment": interface + "_route"})
    return commands, expected


def build_junos(rows, snapshot):
    """Add system resolvers/time sources through the existing exclusive commit flow."""
    import shlex
    commands, expected, seen = [], {}, set()
    if re.search(r"(?m)^set (?:groups|apply-groups|system apply-groups|routing-instances)", snapshot.running):
        raise ValueError("Inherited or routing-instance configuration requires a dedicated service plan.")
    for row in rows:
        if row["type"] not in ("dns", "ntp"): raise ValueError("Junos currently supports only DNS and NTP service scenarios.")
        prefix = "set system name-server " if row["type"] == "dns" else "set system ntp server "
        command = prefix + row["server"]
        if command in seen or any(l == command or l.startswith(command + " ") for l in snapshot.running.splitlines()):
            raise ValueError("That service/server is already configured or staged.")
        if row["type"] == "ntp" and re.search(r"(?m)^set system ntp (?:authentication-key|trusted-key|source-address|boot-server)", snapshot.running):
            raise ValueError("Existing NTP authentication or source settings require a dedicated plan.")
        seen.add(command); commands.append(command)
        expected[shlex.join(shlex.split(command))] = {"present": True}
    return commands, expected
