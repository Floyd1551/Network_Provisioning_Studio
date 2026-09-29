"""Small native-command simulator for exploring the added platform drivers.

It interprets supported CLI edits independently of command generation. It does
not claim to emulate the OS, forwarding plane, hardware capabilities, or timing.
"""
import copy
import re
import shlex
from .samples import SAMPLES
from .vendors import get_driver
from .vendors.base import blocks, compact
from .model import vlan_set


class VendorDemoTransport:
    simulated = True

    def __init__(self, driver_id):
        self.driver = get_driver(driver_id)
        self.outputs = copy.deepcopy(SAMPLES[driver_id])
        self.running = self.outputs[self.driver.running_command]
        self.context = None
        self.sections = blocks(self.running)
        self.vlans = {1: "default", 10: "STAFF", 20: "VOICE"}
        if driver_id == "tplink_jetstream": self.vlans[1] = "System-VLAN"
        elif driver_id == "extreme_exos": self.vlans[1] = "Default"
        elif driver_id == "aruba_cx": self.vlans[1] = "DEFAULT_VLAN_1"
        self.enabled = {}
        self.candidate = None
        self.sent = []

    def connect(self): pass
    def close(self): pass

    def vlan_output(self):
        if self.driver.id == "dell_os10": return "\n".join(f"{n} Active" for n in sorted(self.vlans))
        if self.driver.id == "extreme_exos": return "\n".join(f"{name} {n} ----- ANY 1/1 VR-Default" for n, name in sorted(self.vlans.items()))
        if self.driver.id == "juniper_junos": return "\n".join(f"default-switch {name} {n}" for n, name in sorted(self.vlans.items()))
        return "\n".join(f"{n} {name} active" for n, name in sorted(self.vlans.items()))

    def status_output(self):
        text = self.outputs[self.driver.status_command]
        lines = text.splitlines()
        for index, line in enumerate(lines):
            for name, enabled in self.enabled.items():
                aliases = {name, name.replace("Ethernet", "Et"), name.replace("Ethernet", "Eth"),
                           name.replace("ethernet", "Eth "), name.replace("gigabitEthernet ", "Gi")}
                if not any(line.startswith(alias + " ") for alias in aliases): continue
                if not enabled:
                    line = line.replace("connected", "disabled").replace("LinkUp", "LinkDown").replace("yes up", "no down").replace("up up", "down down").replace(" E A ", " D R ")
                    if self.driver.id == "dell_os10": line = line.replace(" up ", " down ")
                lines[index] = line
        return "\n".join(lines)

    def serialize(self):
        header = re.search(r"(?m)^hostname .*$", self.running)[0]
        lines = [header]
        for number, name in sorted(self.vlans.items()):
            if self.driver.id == "dell_os10": lines += [f"interface vlan {number}", " vlan-name " + name]
            else: lines += [f"vlan {number}", " name " + name]
        for name, body in self.sections.items():
            if re.fullmatch(r"vlan\s*\d+", name): continue
            lines += ["interface " + name] + [" " + line for line in body]
        self.running = "\n".join(lines + ["end"])

    def command(self, command):
        self.sent.append(command)
        if command == self.driver.version_command: return self.outputs[command]
        if command == "show version" and self.driver.id == "tplink_jetstream": return "% Invalid command"
        if command in self.driver.setup: return ""
        if command == self.driver.running_command or command == "run " + self.driver.running_command: return self.running
        if command == self.driver.vlan_command: return self.vlan_output()
        if command == self.driver.status_command: return self.status_output()
        if command in self.driver.optional: return "% Invalid command (optional, simulated)"
        if command == "show interface switchport": return self.outputs[command]
        if self.driver.id == "juniper_junos": return self.junos_command(command)
        if self.driver.id == "extreme_exos": return self.exos_command(command)
        if command in ("configure", "configure terminal", "exit", "end"):
            self.context = None
            return ""
        match = re.fullmatch(r"(?:interface vlan|vlan) (\d+)", command)
        if match:
            number = int(match[1])
            self.vlans.setdefault(number, f"VLAN{number}")
            self.context = ("vlan", number)
            self.serialize()
            return ""
        if command.startswith("interface "):
            name = command[10:]
            if self.driver.id == "dell_os10": name = name.replace(" ", "")
            if name not in self.sections: return "% Invalid interface"
            self.context = ("port", name)
            return ""
        if not self.context: return "% Invalid command"
        if self.context[0] == "vlan":
            if not command.startswith(("name ", "vlan-name ")): return "% Invalid command"
            self.vlans[self.context[1]] = command.split(maxsplit=1)[1]
        else:
            name = self.context[1]
            body = self.sections[name]
            def replace(prefixes, value=None):
                body[:] = [line for line in body if not any(line == prefix or line.startswith(prefix + " ") for prefix in prefixes)]
                if value: body.append(value)
            if command in ("shutdown", "no shutdown"):
                replace(("shutdown", "no shutdown"), command)
                self.enabled[name] = command == "no shutdown"
            elif command.startswith("description ") or command == "no description": replace(("description",), None if command == "no description" else command)
            elif command.startswith("vlan access "): replace(("vlan access", "vlan trunk"), command)
            elif command.startswith("vlan trunk native "): replace(("vlan access", "vlan trunk native"), command)
            elif command.startswith(("vlan trunk allowed ", "no vlan trunk allowed ")):
                old = next((line.split()[-1] for line in body if line.startswith("vlan trunk allowed ")), "all")
                values = vlan_set(old)
                requested = vlan_set(command.split()[-1])
                if command.startswith("no "): values -= requested
                elif old == "all" or command.endswith(" all"): values = requested
                else: values |= requested
                replace(("vlan access", "vlan trunk allowed"), "vlan trunk allowed " + (compact(values) if values else "all"))
            elif self.driver.id == "tplink_jetstream" and "switchport general allowed vlan" in command:
                # Retain the ordered commands; the simulator's running config includes their net effects.
                body.append(command)
            elif self.driver.id == "dell_os10" and "switchport trunk allowed vlan" in command:
                current = next((line.split()[-1] for line in body if line.startswith("switchport trunk allowed vlan ")), "none")
                values = vlan_set(current)
                if command.startswith("no "): values -= vlan_set(command.split()[-1])
                else: values |= vlan_set(command.split()[-1])
                replace(("switchport trunk allowed vlan",), None if not values else "switchport trunk allowed vlan " + compact(values))
            elif command.startswith(("switchport mode ", "switchport access vlan ", "switchport trunk native vlan ", "switchport trunk allowed vlan ", "switchport pvid ", "spanning-tree ")):
                prefix = " ".join(command.split()[:-1])
                if command == "spanning-tree portfast": prefix = command
                replace((prefix,), command)
            elif command.startswith("no spanning-tree "): replace((command[3:],))
            else: return "% Invalid command (not implemented by simulator)"
        self.serialize()
        return ""

    def junos_command(self, command):
        if command == "configure exclusive":
            self.candidate = self.running
            return "Entering configuration mode"
        if command == "show | compare": return "" if self.candidate == self.running else "+ candidate edits"
        if command == "rollback 0": self.candidate = self.running; return "load complete"
        if command == "commit check": return "configuration check succeeds"
        if command == "commit":
            self.running = self.candidate
            self.vlans = {int(number): name for name, number in re.findall(r"(?m)^set vlans (\S+) vlan-id (\d+)$", self.running)}
            for name in re.findall(r"(?m)^set interfaces (\S+) ", self.running):
                self.enabled[name] = f"set interfaces {name} disable" not in self.running.splitlines()
            return "commit complete"
        if command == "exit": self.candidate = None; return ""
        if self.candidate is None: return "error: no candidate session"
        lines = self.candidate.splitlines()
        if command.startswith("delete "):
            prefix = "set " + command[7:]
            lines = [line for line in lines if line != prefix and not line.startswith(prefix + " ")]
        elif command.startswith("set "):
            tokens = shlex.split(command)
            if "members" in tokens: prefix = command[:command.index("members") + len("members")]
            elif "description" in tokens: prefix = command[:command.index("description") + len("description")]
            else: prefix = " ".join(tokens[:-1]) if tokens[-1] != "disable" else command
            lines = [line for line in lines if line != prefix and not line.startswith(prefix + " ")]
            lines.append(command)
        else: return "error: unsupported simulated command"
        self.candidate = "\n".join(lines)
        return ""

    def exos_command(self, command):
        tokens = shlex.split(command)
        if tokens[:2] == ["create", "vlan"]: return ""
        if len(tokens) == 5 and tokens[:2] == ["configure", "vlan"] and tokens[3] == "tag": self.vlans[int(tokens[4])] = tokens[2]
        elif len(tokens) == 3 and tokens[1] == "ports" and tokens[0] in ("enable", "disable"): self.enabled[tokens[2]] = tokens[0] == "enable"
        elif tokens[:2] == ["unconfigure", "ports"] and tokens[-1] == "description-string":
            pattern = f"configure ports {tokens[2]} description-string "
            self.running = "\n".join(line for line in self.running.splitlines() if not line.startswith(pattern))
            return ""
        elif not (tokens[:2] in (["configure", "vlan"], ["configure", "ports"])): return "Error: unsupported simulated command"
        self.running += "\n" + command
        return ""
