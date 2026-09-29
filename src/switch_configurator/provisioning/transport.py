import re


class SSHTransport:
    """Netmiko SSH with strict known-host checking and no credential persistence."""
    simulated = False

    def __init__(self, host, username, password, device_type, port=22, secret="", known_hosts=""):
        if not host or any(c.isspace() for c in host): raise ValueError("Enter a hostname or IP address.")
        if not username: raise ValueError("Enter an SSH username.")
        if not 1 <= int(port) <= 65535: raise ValueError("Invalid SSH port.")
        self.options = dict(host=host, username=username, password=password, secret=secret,
                            port=int(port), device_type=device_type, ssh_strict=True,
                            system_host_keys=True, conn_timeout=15, auth_timeout=20,
                            banner_timeout=20, timeout=30, keepalive=20)
        if known_hosts: self.options.update(alt_host_keys=True, alt_key_file=known_hosts)
        self.connection = None

    def connect(self):
        from netmiko import ConnectHandler
        try:
            self.connection = ConnectHandler(**self.options)
            if self.options["device_type"] in ("cisco_ios", "arista_eos", "cisco_nxos"):
                self.connection.enable()
            prompt = self.connection.find_prompt()
            if self.options["device_type"] == "extreme_exos":
                m = re.fullmatch(r"\*?\s*(?:Slot-\d+\s+)?([\w.-]+)\.\d+\s*#", prompt)
                if not m: raise RuntimeError("Unsupported EXOS prompt.")
                self.pattern = r"(?m)^\*?\s*(?:Slot-\d+\s+)?" + re.escape(m[1]) + r"\.\d+\s*#\s*$"
            elif self.options["device_type"] == "mikrotik_routeros":
                m = re.match(r"(\[[^\]\r\n]+\])", prompt)
                if not m: raise RuntimeError("Unsupported RouterOS prompt.")
                self.pattern = r"(?m)^" + re.escape(m[1]) + r"(?: /[^\r\n]*)?\s*>\s*$"
            else:
                host = re.split(r"\s|\(", prompt.rstrip("#> "))[0]
                if not host: raise RuntimeError("Unsupported SSH prompt.")
                self.pattern = r"(?m)^" + re.escape(host) + r"(?:\s*\([^\r\n)]*\))?\s*[#>]\s*$"
        except Exception:
            self.close()
            raise
        finally:
            self.options["password"] = self.options["secret"] = ""

    def command(self, command):
        if not self.connection: raise RuntimeError("SSH is disconnected.")
        if any(ord(c) < 32 for c in command): raise ValueError("Only one CLI command per request.")
        return self.connection.send_command(command, expect_string=self.pattern, read_timeout=90,
                                            strip_prompt=True, strip_command=True)

    def close(self):
        if self.connection:
            # Juniper's default Netmiko cleanup answers "yes" to an uncommitted
            # candidate prompt. Candidate ownership belongs to our driver, never
            # to connection teardown. Close SSH without sending cleanup CLI.
            if self.options["device_type"] == "juniper_junos": self.connection.cleanup = lambda: None
            self.connection.disconnect()
            self.connection = None

