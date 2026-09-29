import copy
import json
import uuid
from datetime import datetime, timezone
from .drivers import DRIVERS


class ProvisioningService:
    def __init__(self, driver_id, transport, store, log=lambda text: None):
        self.driver = DRIVERS[driver_id]()
        self.transport, self.store, self.log = transport, store, log

    def execute(self, command):
        self.log("> " + command)
        output = self.transport.command(command)
        self.log(output or "(prompt returned)")
        if self.driver.error(output): raise RuntimeError(f"Device rejected {command}: {output}")
        return output

    def connect(self):
        try:
            self.transport.connect()
            identity = self.execute(self.driver.identity_command)
            if not self.driver.matches(identity): raise ValueError("The device OS does not match the selected platform.")
            for command in self.driver.setup: self.execute(command)
            return self.discover()
        except Exception:
            self.transport.close()
            raise

    def discover(self):
        identity = self.execute(self.driver.identity_command)
        running = self.execute(self.driver.running_command)
        extra = self.execute("/interface print detail without-paging") if self.driver.id == "routeros" else ""
        snapshot = self.driver.parse(running, identity, extra)
        snapshot.evidence = {self.driver.identity_command: identity, self.driver.running_command: running}
        if extra: snapshot.evidence["/interface print detail without-paging"] = extra
        return snapshot

    def preview(self, intent): return self.driver.plan(copy.deepcopy(intent), self.discover())

    def apply(self, plan):
        if getattr(self.driver, "read_only", False): raise ValueError("This platform supports discovery only.")
        regenerated = self.driver.plan(plan.intent, plan.snapshot)
        if regenerated.commands != plan.commands or regenerated.expected != plan.expected:
            raise ValueError("The reviewed plan was modified. Generate a new preview.")
        current = self.discover()
        if self.driver.normalize(current.running) != self.driver.normalize(plan.snapshot.running):
            raise RuntimeError("Configuration changed since review; nothing was applied.")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        ident = stamp + "-" + uuid.uuid4().hex[:8]
        path = self.store.root / "backups" / ident
        path.mkdir(parents=True)
        (path / "before.cfg").write_text(current.running, encoding="utf-8")
        (path / "intent.json").write_text(json.dumps({"platform": self.driver.id, "intent": plan.intent.to_dict()}, indent=2), encoding="utf-8")
        (path / "commands.txt").write_text("\n".join(plan.commands), encoding="utf-8")
        with self.store.db() as db:
            db.execute("INSERT INTO history VALUES (?,?,?,?,?)", (ident, stamp, current.hostname, "applying", str(path)))
        old_log, transcript, after = self.log, [], None
        def journal(text):
            # Write before continuing; disk failure must stop transmission.
            with (path / "transcript.txt").open("a", encoding="utf-8") as file: file.write(text + "\n")
            transcript.append(text)
            old_log(text)
        self.log = journal
        try:
            if hasattr(self.driver, "deploy"): self.driver.deploy(self, plan)
            else:
                for command in plan.commands: self.execute(command)
            after = self.discover()
            errors = self.driver.verify(plan, after)
            if errors: raise RuntimeError("Readback verification failed: " + "; ".join(errors))
            self.store.finish(path, "configuration verified", "\n".join(transcript), after)
            return after, path
        except Exception as error:
            try:
                if hasattr(self.driver, "recover"): self.driver.recover(self)
                else:
                    for command in self.driver.end: self.execute(command)
                after = self.discover()
            except Exception as recovery: transcript.append("Recovery/readback failed: " + str(recovery))
            self.store.finish(path, "failed / possibly partial", "\n".join(transcript) + "\nERROR: " + str(error), after)
            raise RuntimeError(f"Provisioning failed; changes may be partial. {error}\nBackup: {path}") from error
        finally: self.log = old_log
