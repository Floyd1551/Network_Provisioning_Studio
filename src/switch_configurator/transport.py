"""Synchronous transports. The GUI runs these exclusively on a worker thread."""
import re
import time
from typing import Protocol
from .driver import config_blocks, parse_port, field_command
from .model import Port


class Transport(Protocol):
    simulated: bool
    def connect(self): ...
    def command(self, command: str) -> str: ...
    def close(self): ...


class SerialTransport:
    simulated = False

    def __init__(self, port, baud=9600, timeout=20):
        self.port, self.baud, self.timeout = port, baud, timeout
        self.serial = None
        self.hostname = None
        self.prompt_style = "hash"
        self.allow_paging = False

    def connect(self):
        import serial
        self.serial = serial.Serial(self.port, self.baud, timeout=0.1, write_timeout=3,
                                    bytesize=8, parity="N", stopbits=1, xonxoff=False, rtscts=False)
        try:
            self.serial.write(b"\r")
            output = self._read_prompt(initial=True)
            prompt = output.splitlines()[-1].strip()
            junos = re.fullmatch(r"([\w.-]+@[\w.-]+)>", prompt)
            extreme = re.fullmatch(r"\*?\s*(?:Slot-\d+\s+)?([\w.-]+)\.\d+\s+#", prompt)
            ordinary = re.fullmatch(r"([\w.-]+)#", prompt)
            if junos: self.hostname, self.prompt_style = junos[1], "junos"
            elif extreme: self.hostname, self.prompt_style = extreme[1], "exos"
            elif ordinary: self.hostname, self.prompt_style = ordinary[1], "hash"
            else:
                raise RuntimeError("Log in first. Leave the switch at privileged EXEC (hostname#), Junos operational (user@host>), or EXOS (switch.1 #), then reconnect.")
        except Exception:
            self.close()
            raise

    def _read_prompt(self, initial=False):
        deadline = time.monotonic() + self.timeout
        output = ""
        while time.monotonic() < deadline:
            chunk = self.serial.read(max(1, self.serial.in_waiting)).decode("utf-8", errors="replace")
            output += chunk.replace("\r", "")
            output = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", output)
            if len(output) > 8_000_000: raise RuntimeError("Console response exceeds 8 MB.")
            if initial and re.search(r"(?:[Pp]assword:|[Uu]sername:|[Ll]ogin:|[\w.@-]+>)\s*$", output):
                return output
            if initial:
                pattern = r"(?:[\w.-]+(?:\((?:config|conf)[^)\n]*\))?#|\*?\s*(?:Slot-\d+\s+)?[\w.-]+\.\d+\s+#)"
            else:
                host = re.escape(self.hostname)
                if self.prompt_style == "junos": pattern = host + r"[>#]"
                elif self.prompt_style == "exos": pattern = r"\*?\s*(?:Slot-\d+\s+)?" + host + r"\.\d+\s+#"
                else: pattern = host + r"(?:\((?:config|conf)[^)\n]*\))?#"
            if re.search(r"(?:^|\n)" + pattern + r"[ \t]*$", output):
                return output
            pager = r"--\s*[Mm][Oo][Rr][Ee]\s*--|---\(more[^)]*\)---|Press <SPACE> to continue"
            if re.search(pager, output):
                if not self.allow_paging: raise RuntimeError("Paging detected; response is incomplete. Reconnect after disabling paging.")
                output = re.sub(pager, "", output)
                self.serial.write(b" ")
        raise TimeoutError("Console prompt timed out. Device state is uncertain; inspect the console and refresh before editing.")

    def command(self, command):
        if not self.serial or not self.serial.is_open: raise RuntimeError("Serial connection is closed.")
        if any(ord(c) < 32 for c in command): raise ValueError("Send one CLI command at a time.")
        # Drain unsolicited console messages before transmitting. Never discard a pending command response.
        self.serial.reset_input_buffer()
        self.serial.write(command.encode("ascii") + b"\r")
        output = self._read_prompt()
        lines = output.splitlines()
        if lines and lines[0].strip() == command: lines.pop(0)
        if lines and lines[-1].strip().endswith(("#", ">")): lines.pop()
        # Junos emits edit context immediately before the configuration prompt.
        if self.prompt_style == "junos":
            lines = [line for line in lines if not re.fullmatch(r"\[edit[^\]]*\]|\{(?:master|backup)(?::\d+)?\}", line.strip())]
        return "\n".join(lines).strip()

    def probe(self, command):
        if command not in ("show version", "show system-info"): raise ValueError("Unsupported identity probe.")
        self.allow_paging = True
        try: return self.command(command)
        finally: self.allow_paging = False

    def close(self):
        if self.serial: self.serial.close()


class DemoTransport:
    simulated = True

    def __init__(self):
        self.ports = {}
        self.vlans = {1: "default", 10: "STAFF", 20: "VOICE", 30: "SECURITY", 99: "MANAGEMENT"}
        self.context = None
        for number in range(1, 29):
            name = ("GigabitEthernet1/0/" + str(number)) if number <= 24 else ("TenGigabitEthernet1/1/" + str(number - 24))
            p = Port(name)
            p.config.update(mode="access", access_vlan=10, description=f"Desk {number:02}")
            if number <= 4: p.config.update(voice_vlan=20, description=f"Phone + desk {number:02}")
            if 9 <= number <= 12: p.config.update(access_vlan=30, description=f"Camera {number - 8}")
            if number > 24: p.config.update(mode="trunk", description="Distribution uplink", native_vlan=99)
            if number in (18, 19, 20): p.config.update(enabled=False, description="Reserved")
            self.ports[name] = p

    def connect(self): pass
    def close(self): pass

    def running(self):
        lines = ["version 17.9", "hostname LAB-ACCESS-01", "!"]
        for number, name in sorted(self.vlans.items()): lines += [f"vlan {number}", f" name {name}", "!"]
        for name, port in self.ports.items():
            lines.append("interface " + name)
            for key, value in port.config.items():
                if key in ("portfast", "bpduguard") and value == "default": continue
                lines.append(" " + field_command(key, value))
            lines.append("!")
        return "\n".join(lines + ["end"])

    def command(self, command):
        if command == "show running-config": return self.running()
        if command == "show version": return "Cisco IOS XE Software, Version 17.9.4\nModel Number : C9300-24P\nSimulated device — no hardware attached"
        if command == "show vlan brief": return "\n".join(f"{n} {v} active" for n, v in sorted(self.vlans.items()))
        if command == "show interfaces status":
            result = ["Port Name Status Vlan Duplex Speed Type"]
            for i, (name, port) in enumerate(self.ports.items()):
                c = port.config
                state = "disabled" if not c["enabled"] else ("err-disabled" if i == 14 else "notconnect" if i % 5 == 4 else "connected")
                result.append(f"{name} {c['description'] or ' '} {state} {'trunk' if c['mode'] == 'trunk' else c['access_vlan']} a-full a-1000 10/100/1000BaseTX")
            return "\n".join(result)
        if command == "show power inline":
            return "\n".join(f"{name} {'off' if p.config['poe'] == 'never' else 'auto'} {'on' if i < 12 and p.config['poe'] != 'never' else 'off'} {6.4 if i < 12 and p.config['poe'] != 'never' else 0.0} Ieee PD" for i, (name, p) in enumerate(self.ports.items()))
        if command == "show cdp neighbors detail": return "Device ID: DIST-01\nInterface: TenGigabitEthernet1/1/1, Port ID (outgoing port): TenGigabitEthernet1/0/1"
        if command == "show inventory": return 'NAME: "Switch 1", DESCR: "Demo Catalyst 9300"\nPID: C9300-24P, VID: V01, SN: SIMULATED'
        if command == "show switch": return "Switch# Role Mac Address Priority Version State\n*1 Active 0000.0000.0001 15 V01 Ready"
        if command in ("terminal length 0", "terminal width 511", "configure terminal"): return ""
        if command in ("end", "exit"):
            self.context = None
            return ""
        if command.startswith("interface "):
            name = command.split(maxsplit=1)[1]
            if name not in self.ports: return "% Invalid interface"
            self.context = ("port", name)
            return ""
        if command.startswith("vlan "):
            number = int(command.split()[1])
            self.vlans.setdefault(number, f"VLAN{number:04}")
            self.context = ("vlan", number)
            return ""
        if self.context and self.context[0] == "vlan" and command.startswith("name "):
            self.vlans[self.context[1]] = command[5:]
            return ""
        if self.context and self.context[0] == "port":
            name = self.context[1]
            existing = config_blocks(self.running())[name]
            if command == "no description": self.ports[name].config["description"] = ""
            elif command == "no switchport voice vlan": self.ports[name].config["voice_vlan"] = 0
            elif command == "no spanning-tree portfast": self.ports[name].config["portfast"] = "default"
            elif command == "no spanning-tree bpduguard": self.ports[name].config["bpduguard"] = "default"
            else: self.ports[name] = parse_port(name, existing + [command])
            return ""
        return "% Invalid input detected at '^' marker."
