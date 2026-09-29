"""Read-only lab evidence; discovery never implies deployment qualification."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid


def capture(store, snapshot, simulated):
    evidence = dict(snapshot.evidence)
    if not evidence or not snapshot.running.strip():
        raise ValueError("A successful discovery with configuration evidence is required.")
    ident = str(uuid.uuid4())
    report = {
        "schema": 1, "id": ident,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "simulation" if simulated else "live connection",
        "qualification": "not hardware tested" if simulated else "discovery captured; provisioning not validated",
        "platform": getattr(snapshot, "driver_id", snapshot.platform),
        "hostname": snapshot.hostname,
        "model": getattr(snapshot, "model", "not normalized; see evidence"),
        "firmware": getattr(snapshot, "version", "not normalized; see evidence"),
        "configuration_sha256": hashlib.sha256(snapshot.running.encode("utf-8")).hexdigest(),
        "evidence": evidence,
        "remaining": ["Confirm exact model, firmware and licensed features",
                      "Review a provisioning scenario on isolated lab ports",
                      "Apply and inspect recorded configuration readback",
                      "Record independent functional observations and limitations"],
    }
    directory = store.root / "lab-evidence" / ident
    directory.mkdir(parents=True)
    (directory / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (directory / "configuration.cfg").write_text(snapshot.running, encoding="utf-8")
    (directory / "README.txt").write_text(
        "LAB EVIDENCE — " + report["source"] + "\n\n" + report["qualification"] +
        "\nA successful discovery does not validate provisioning, forwarding, or reboot persistence.\n"
        "These files contain device configuration and may contain secrets. Review before sharing.\n",
        encoding="utf-8")
    return directory
