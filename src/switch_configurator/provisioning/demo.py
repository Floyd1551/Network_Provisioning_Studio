"""Synthetic fixtures and small CLI interpreters, not hardware certification."""
import copy
import shlex
from .drivers import DRIVERS, ios_blocks, forti_tables

SAMPLES = {
    "ios_router": ("Cisco IOS XE Software, Version 17.12.1", """hostname LAB-ROUTER
ipv6 unicast-routing
interface GigabitEthernet0/0
 no switchport
 ip address 192.0.2.2 255.255.255.0
interface GigabitEthernet0/1
 no switchport
interface Vlan20
 no ip address
 shutdown
end
"""),
    "fortios": ("""Version: FortiGate-60F v7.4.3,build2573
Operation Mode: NAT
Virtual domain configuration: disable
Current HA mode: standalone
""", """config system global
    set hostname "LAB-FORTIGATE"
end
config system interface
    edit "port1"
        set type physical
        set mode static
        set ip 192.0.2.2 255.255.255.0
    next
    edit "port2"
        set type physical
        set mode static
        set ip 0.0.0.0 0.0.0.0
    next
end
"""),
    "routeros": ("version: 7.17.2 (stable)\nboard-name: hEX", """# synthetic RouterOS 7 export
/ip address add address=192.0.2.2/24 interface=ether1 comment=WAN
"""),
    "junos_routing": ("Hostname: LAB-SRX\nModel: srx300\nJunos: 23.4R2", """set system host-name LAB-SRX
set interfaces ge-0/0/0 unit 0 family inet address 192.0.2.2/24
set interfaces ge-0/0/1 unit 0 family inet
set security zones security-zone untrust interfaces ge-0/0/0.0
set security zones security-zone trust interfaces ge-0/0/1.0
"""),
    "aruba_routing": ("ArubaOS-CX Version 10.13.1000", """hostname LAB-CX
interface 1/1/1
    routing
    ip address 192.0.2.2/24
interface 1/1/2
    routing
"""),
    "panos": ("model: PA-440\nsw-version: 11.1.4", '<config version="11.1.0"><devices><entry name="localhost.localdomain" /></devices></config>'),
    "checkpoint": ("Product version Check Point Gaia R81.20", "set hostname LAB-GAIA\nset interface eth0 ipv4-address 192.0.2.2 mask-length 24"),
    "sonicwall": ("SonicWall SonicOS 7.1", "! Synthetic SonicOS configuration\nhostname LAB-SONICWALL\ninterface X0\n ip-assignment LAN static\n exit"),
}


class Demo:
    simulated = True
    def __init__(self, platform):
        self.driver = DRIVERS[platform]()
        self.identity, self.running = SAMPLES[platform]
        self.sent, self.context, self.table = [], None, None
        self.candidate = None
        if platform in ("ios_router", "aruba_routing"): self.blocks = ios_blocks(self.running)
        if platform == "fortios": self.tables = forti_tables(self.running)

    def connect(self): pass
    def close(self): pass

    def command(self, command):
        self.sent.append(command)
        if command == self.driver.identity_command: return self.identity
        if command == self.driver.running_command or command == "run " + self.driver.running_command: return self.running
        if command == "/interface print detail without-paging":
            extra = '0 R name="ether1" type="ether"\n1 R name="ether2" type="ether"'
            for line in self.running.splitlines():
                if line.startswith("/interface wireguard add "):
                    values = dict(token.split("=", 1) for token in shlex.split(line)[3:] if "=" in token)
                    extra += '\n2 R name="' + values["name"] + '" type="wireguard"'
            return extra
        if command in self.driver.setup: return ""
        if getattr(self.driver, "read_only", False): return "error: discovery only"
        if self.driver.id == "junos_routing":
            if command == "configure exclusive":
                self.candidate = self.running.splitlines()
                return "Entering configuration mode"
            if command == "show | compare": return "" if self.candidate == self.running.splitlines() else "+ candidate changed"
            if command == "commit check": return "configuration check succeeds"
            if command == "commit":
                self.running = "\n".join(self.candidate) + "\n"
                return "commit complete"
            if command == "rollback 0": self.candidate = self.running.splitlines()
            elif command == "exit": self.candidate = None
            elif command.startswith("set "):
                if self.candidate is None: return "error: not in configuration mode"
                if command not in self.candidate: self.candidate.append(command)
            elif command.startswith("delete "):
                self.candidate = [l for l in self.candidate if l != "set " + command[7:]]
            else: return "error: unsupported demo command"
            return ""
        if self.driver.id == "routeros":
            if " add " not in command: return "failure: unsupported demo command"
            self.running += command + "\n"
            return ""
        if self.driver.id == "fortios":
            if command.startswith("config "):
                self.table = command[7:]
                self.tables.setdefault(self.table, {})
            elif command.startswith("edit "):
                self.context = shlex.split(command)[1]
                self.tables[self.table].setdefault(self.context, {})
            elif command.startswith("set ") and self.context:
                tokens = shlex.split(command)
                self.tables[self.table][self.context][tokens[1]] = tokens[2:]
            elif command in ("next", "end"):
                self.context = None
                if command == "end": self.table = None
            else: return "command parse error"
            lines = []
            for table, items in self.tables.items():
                lines.append("config " + table)
                for key, fields in items.items():
                    if key != "__settings__": lines.append('    edit "' + key + '"')
                    for k, v in fields.items(): lines.append("        set " + k + " " + " ".join('"' + x + '"' for x in v))
                    if key != "__settings__": lines.append("    next")
                lines.append("end")
            self.running = "\n".join(lines) + "\n"
            return ""
        if command == "configure terminal": return ""
        if command in ("end", "exit"): self.context = None
        elif command.startswith(("interface ", "ip access-list extended ", "ip dhcp pool ", "router ospf ")):
            self.context = command
            self.blocks.setdefault(command, [])
        elif self.context:
            lines = self.blocks[self.context]
            if command.startswith("no ip address "):
                value = command[3:]
                self.blocks[self.context] = [l for l in lines if l != value]
            else:
                if command.startswith("ip address "): lines[:] = [l for l in lines if not l.startswith("ip address ")]
                if command not in lines: lines.append(command)
        elif command.startswith(("ip route ", "ip name-server ", "ntp server ", "ipv6 route ", "ip dhcp excluded-address ")): self.blocks[command] = []
        else: return "% Invalid input"
        self.running = "\n".join(head + ("\n" + "\n".join(" " + l for l in lines) if lines else "") for head, lines in self.blocks.items() if head != "end") + "\n"
        if self.driver.id == "ios_router": self.running += "end\n"
        return ""
