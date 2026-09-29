import copy
import json
import uuid
from datetime import datetime, timezone
from .model import canonical


class APIService:
    def __init__(self, adapter, store):
        self.adapter, self.store = adapter, store
        self.transport = adapter.transport
        self.log = lambda text: None
        adapter.log = lambda text: self.log(text)

    def connect(self): return self.adapter.connect()
    def discover(self): return self.adapter.discover()
    def close(self): self.adapter.close()
    def preview(self, rules): return self.adapter.plan(rules, self.adapter.fresh_discover() if hasattr(self.adapter, "fresh_discover") else self.discover())

    def apply(self, plan):
        actual = self.adapter.plan(plan.rules, plan.snapshot)
        if actual.operations != plan.operations or actual.expected != plan.expected: raise ValueError("Reviewed API plan was modified.")
        before = self.adapter.fresh_discover() if hasattr(self.adapter, "fresh_discover") else self.discover()
        if before.hostname != plan.snapshot.hostname or before.platform != plan.snapshot.platform or canonical(before.data) != canonical(plan.snapshot.data):
            raise RuntimeError("Target or configuration changed since review; refresh and review again.")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        ident = stamp + "-api-" + uuid.uuid4().hex[:8]
        path = self.store.root / "backups" / ident; path.mkdir(parents=True)
        (path / "before.cfg").write_text(before.running, encoding="utf-8")
        (path / "plan.json").write_text(json.dumps({"platform": before.platform, "rules": plan.rules, "operations": plan.operations}, indent=2), encoding="utf-8")
        with self.store.db() as db: db.execute("INSERT INTO history VALUES (?,?,?,?,?)", (ident, stamp, before.hostname, "applying API plan", str(path)))
        old_log, transcript = self.log, []
        def journal(text):
            with (path / "transcript.txt").open("a", encoding="utf-8") as stream: stream.write(text + "\n")
            transcript.append(text); old_log(text)
        self.log = journal
        try:
            self.adapter.deploy(plan)
            after = self.discover(); self.adapter.verify(plan, after)
            self.store.finish(path, "API configuration verified", "\n".join(transcript), after)
            return after, path
        except Exception as error:
            self.store.finish(path, "API failed / inspect pending or partial changes", "\n".join(transcript) + "\n" + str(error))
            raise RuntimeError("API deployment failed. Inspect pending/partial device changes before retrying. Backup: " + str(path) + "\n" + str(error)) from error
        finally: self.log = old_log
