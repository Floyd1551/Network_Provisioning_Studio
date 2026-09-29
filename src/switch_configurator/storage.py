import json
from pathlib import Path
import sqlite3
from datetime import datetime, timezone
import uuid
from contextlib import contextmanager


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS profiles (name TEXT PRIMARY KEY, patch TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS history (id TEXT PRIMARY KEY, date TEXT, device TEXT, status TEXT, path TEXT)")

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.root / "history.sqlite3")
        try:
            with connection: yield connection
        finally:
            connection.close()

    def profiles(self):
        with self.db() as db: return {name: json.loads(patch) for name, patch in db.execute("SELECT name,patch FROM profiles")}

    def save_profile(self, name, patch):
        with self.db() as db: db.execute("INSERT OR REPLACE INTO profiles VALUES (?,?)", (name, json.dumps(patch)))

    def begin(self, device, changes, commands):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        ident = stamp + "-" + uuid.uuid4().hex[:8]
        path = self.root / "backups" / ident
        path.mkdir(parents=True)
        (path / "before.cfg").write_text(device.running, encoding="utf-8")
        (path / "commands.txt").write_text("\n".join(commands), encoding="utf-8")
        (path / "intent.json").write_text(json.dumps({"driver": device.driver_id, "platform": device.platform, "ports": changes.ports, "vlans": changes.vlans}, indent=2), encoding="utf-8")
        with self.db() as db: db.execute("INSERT INTO history VALUES (?,?,?,?,?)", (ident, stamp, device.hostname, "applying", str(path)))
        return path

    def finish(self, path, status, transcript, after=None):
        (path / "transcript.txt").write_text(transcript, encoding="utf-8")
        if after is not None: (path / "after.cfg").write_text(after.running, encoding="utf-8")
        with self.db() as db: db.execute("UPDATE history SET status=? WHERE id=?", (status, path.name))

    def history(self):
        with self.db() as db: return db.execute("SELECT date,device,status,path FROM history ORDER BY date DESC LIMIT 100").fetchall()
