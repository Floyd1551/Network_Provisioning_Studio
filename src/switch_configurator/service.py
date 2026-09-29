import difflib
import re
from dataclasses import dataclass
from .vendors import get_driver, identify

@dataclass
class Preview:
    device: object
    changes: object
    commands: list[str]
    diff: str


class Service:
    def __init__(self, transport, store, log=lambda text: None, driver_id="auto"):
        self.transport, self.store, self.log = transport, store, log
        self.driver = None if driver_id == "auto" else get_driver(driver_id)

    def execute(self, command, required=True):
        self.log("> " + command)
        output = self.transport.command(command)
        self.log(output or "(prompt returned)")
        if required and (self.driver or get_driver("cisco_ios")).is_error(output): raise RuntimeError(f"Device rejected {command}:\n{output}")
        return output

    def connect(self):
        self.transport.connect()
        try:
            # Only read-only identity probes precede platform-specific session setup.
            probes = (self.driver.version_command,) if self.driver else ("show version", "show system-info")
            for command in probes:
                self.log("> " + command)
                output = getattr(self.transport, "probe", self.transport.command)(command)
                self.log(output)
                if self.driver:
                    if not self.driver.matches(output): raise ValueError(f"Device identity does not match selected {self.driver.label}.")
                    break
                detected = identify(output)
                if detected:
                    self.driver = detected
                    break
            if self.driver is None: raise ValueError("Unknown or unsupported switch OS. Select the correct platform or use raw console; no configuration was sent.")
            self.log("Platform: " + self.driver.label)
            if self.driver.id == "juniper_junos" and hasattr(self.transport, "timeout"):
                self.transport.timeout = max(self.transport.timeout, 90)
            for command in self.driver.setup: self.execute(command)
            return self.discover()
        except Exception:
            self.transport.close()
            raise

    def discover(self):
        if self.driver is None: raise RuntimeError("Connect and identify a platform first.")
        outputs = {cmd: self.execute(cmd) for cmd in self.driver.required}
        for cmd in self.driver.optional: outputs[cmd] = self.execute(cmd, required=False)
        return self.driver.parse(outputs)

    def preview(self, changes):
        import copy
        changes = copy.deepcopy(changes)
        device = self.discover()
        generated = self.driver.commands(changes, device)
        before, after = [], []
        for name, patch in changes.ports.items():
            for key, value in patch.items():
                before.append(f"{name}: {key} = {device.ports[name].config[key]}\n")
                after.append(f"{name}: {key} = {value}\n")
        for number, name in changes.vlans.items():
            before.append(f"VLAN {number}: {device.vlans.get(number, '(absent)')}\n")
            after.append(f"VLAN {number}: {name}\n")
        diff = "".join(difflib.unified_diff(before, after, fromfile="Current configuration model", tofile="Requested configuration model"))
        return Preview(device, changes, generated, diff or "No modeled value changes. Commands will still be sent.")

    def apply(self, preview):
        # Full running-config comparison protects the reviewed snapshot from concurrent edits.
        if self.driver is None or self.driver.id != preview.device.driver_id: raise RuntimeError("Preview belongs to another platform; review again.")
        if self.driver.commands(preview.changes, preview.device) != preview.commands: raise RuntimeError("Preview was modified; review again.")
        current = self.execute(self.driver.running_command)
        if self.driver.normalize_config(current) != self.driver.normalize_config(preview.device.running):
            raise RuntimeError("Configuration changed since preview. Nothing applied; generate a new preview.")
        path = self.store.begin(preview.device, preview.changes, preview.commands)
        transcript = []
        notices = []
        original_log = self.log
        def capture(text):
            transcript.append(text)
            if re.search(r"(?im)^%?Warning:", text): notices.append("Device CLI advisory; see transcript")
            # Preserve evidence command-by-command, even if this process is interrupted.
            with (path / "transcript.txt").open("a", encoding="utf-8") as file: file.write(text + "\n")
            original_log(text)
        self.log = capture
        after = None
        try:
            self.driver.deploy(self, preview)
            after = self.discover()
            mismatches = self.driver.verify(preview.changes, after)
            if mismatches: raise RuntimeError("Verification failed:\n" + "\n".join(mismatches))
            bad_ports = [n for n in preview.changes.ports if after.ports[n].status in ("err-disabled", "suspended", "inactive")]
            bad_ports.extend(notices)
            status = "verified with warnings" if bad_ports else "verified"
            self.store.finish(path, status, "\n".join(transcript), after)
            return after, str(path), bad_ports
        except Exception as error:
            capture("FAILED / PARTIAL: " + str(error))
            try:
                self.driver.recover(self)
                after = self.discover()
            except Exception as recovery: capture("After-state capture failed: " + str(recovery))
            self.store.finish(path, "failed / possibly partial", "\n".join(transcript), after)
            raise RuntimeError(f"Deployment failed; changes may be partial.\n{error}\nEvidence: {path}\nRefresh before making further changes.") from error
        finally:
            self.log = original_log
