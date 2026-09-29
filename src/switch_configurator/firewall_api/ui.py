import json
from pathlib import Path
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QComboBox, QLineEdit, QPushButton, QPlainTextEdit, QMessageBox, QDialog, QDialogButtonBox,
    QCheckBox, QFileDialog, QInputDialog)
from ..provisioning.ui import Job
from .http import HTTPS
from .sonicos import SonicOS
from .panos import PANOS
from .checkpoint import CheckPoint
from .demo import SonicDemo, PANDemo, CheckPointDemo
from .service import APIService


class APIPane(QWidget):
    history_changed = Signal()
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store, self.service, self.snapshot, self.job = store, None, None, None
        self.connection_key = None
        self.rules = []
        layout = QVBoxLayout(self)
        hint = QLabel("Native firewall APIs • Experimental, hardware-untested. Access rules reference existing objects. HTTPS validates certificates; import your trusted CA when needed.")
        hint.setWordWrap(True); layout.addWidget(hint)
        row = QHBoxLayout(); layout.addLayout(row)
        self.platform = QComboBox()
        for adapter in (SonicOS, PANOS, CheckPoint): self.platform.addItem(adapter.label, adapter.id)
        row.addWidget(self.platform)
        self.mode = QComboBox(); self.mode.addItems(["Demo", "HTTPS API"]); row.addWidget(self.mode)
        self.connect_button = QPushButton("Connect / discover"); self.connect_button.clicked.connect(self.connect_device); row.addWidget(self.connect_button)
        self.credentials = QWidget(); form = QFormLayout(self.credentials); self.credential_form = form; layout.addWidget(self.credentials)
        for key, title, default in (("host", "Host", ""), ("port", "HTTPS port", "443"), ("username", "API administrator", ""), ("password", "Password / PAN-OS API key", ""), ("ca", "Trusted CA PEM file (optional)", ""), ("vsys", "PAN-OS virtual system", "vsys1")):
            field = QLineEdit(default); setattr(self, key, field); form.addRow(title, field)
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        for key, title in (("domain", "Check Point domain (optional)"), ("layer", "Access layer"), ("package", "Policy package"), ("target", "Installation gateway")):
            field = QLineEdit(); setattr(self, key, field); form.addRow(title, field)
        self.mode.currentIndexChanged.connect(self.update_controls)
        self.platform.currentIndexChanged.connect(self.update_controls)
        self.status = QLabel("Connect before staging access rules."); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.draft = QPlainTextEdit(); self.draft.setReadOnly(True); layout.addWidget(self.draft, 1)
        row = QHBoxLayout(); layout.addLayout(row)
        self.add_button = QPushButton("Add access rule…"); self.add_button.clicked.connect(self.add_rule); row.addWidget(self.add_button)
        self.clear_button = QPushButton("Clear draft"); self.clear_button.clicked.connect(self.clear); row.addWidget(self.clear_button)
        self.export_button = QPushButton("Export API snapshot…"); self.export_button.clicked.connect(self.export); row.addWidget(self.export_button)
        self.review_button = QPushButton("Review API deployment…"); self.review_button.clicked.connect(self.preview); row.addWidget(self.review_button)
        draftrow = QHBoxLayout(); layout.addLayout(draftrow)
        self.draft_buttons = []
        for title, callback in (("Save API draft…", self.save_draft), ("Load API draft…", self.load_draft), ("Remove staged rule…", self.remove_rule)):
            button = QPushButton(title); button.clicked.connect(callback); draftrow.addWidget(button); self.draft_buttons.append(button)
        self.activity = QPlainTextEdit(); self.activity.setReadOnly(True); self.activity.setMaximumHeight(170); layout.addWidget(self.activity)
        for field in (self.host, self.port, self.username, self.ca, self.vsys, self.domain, self.layer, self.package, self.target): field.textChanged.connect(self.update_controls)
        self.update_controls()

    def settings_key(self):
        return (self.platform.currentData(), self.mode.currentText(), *(field.text() for field in (self.host, self.port, self.username, self.ca, self.vsys, self.domain, self.layer, self.package, self.target)))

    @property
    def busy(self): return self.job is not None

    def update_controls(self):
        self.credentials.setVisible(self.mode.currentText() == "HTTPS API")
        for widget in (self.credentials, self.connect_button, self.platform, self.mode, self.clear_button): widget.setEnabled(not self.busy)
        connected = self.snapshot is not None and not self.busy and self.snapshot.platform == self.platform.currentData() and self.connection_key == self.settings_key()
        self.vsys.setVisible(self.platform.currentData() == PANOS.id)
        self.credential_form.labelForField(self.vsys).setVisible(self.platform.currentData() == PANOS.id)
        for field in (self.domain, self.layer, self.package, self.target):
            field.setVisible(self.platform.currentData() == CheckPoint.id)
            self.credential_form.labelForField(field).setVisible(self.platform.currentData() == CheckPoint.id)
        for widget in (self.add_button, self.export_button): widget.setEnabled(connected)
        for widget in self.draft_buttons: widget.setEnabled(connected)
        self.review_button.setEnabled(connected and bool(self.rules))
        self.draft.setPlainText("\n\n".join(row["name"] + " • " + row["action"].upper() + "\n" + row["source"] + " → " + row["destination"] + " • " + row["service"] + ("\n" + row["from_zone"] + " → " + row["to_zone"] if "from_zone" in row else "") for row in self.rules) if self.rules else "No staged API rules. Adding a rule does not deploy it.")

    def run(self, operation, callback):
        if self.busy: return
        self.job = Job(self.service, operation)
        self.job.output.connect(self.activity.appendPlainText)
        self.job.done.connect(callback); self.job.failed.connect(self.failure); self.job.finished.connect(self.finished)
        self.update_controls(); self.job.start()

    def finished(self):
        self.job.deleteLater(); self.job = None; self.update_controls(); self.history_changed.emit()

    def failure(self, message):
        self.snapshot = None; self.status.setText("API operation failed. Inspect the device before retrying.")
        self.activity.appendPlainText(message); QMessageBox.critical(self, "API operation failed", message)

    def connect_device(self):
        if self.rules and QMessageBox.question(self, "Reconnect", "Discard the staged API rules and reconnect?") != QMessageBox.StandardButton.Yes: return
        try:
            previous = self.service
            self.snapshot = None; self.rules = []
            demo = self.mode.currentText() == "Demo"
            pan = self.platform.currentData() == PANOS.id
            checkpoint = self.platform.currentData() == CheckPoint.id
            transport = (CheckPointDemo() if checkpoint else PANDemo() if pan else SonicDemo()) if demo else HTTPS(self.host.text().strip(), int(self.port.text()), self.ca.text().strip())
            username, password = ("demo", "demo") if demo else (self.username.text().strip(), self.password.text())
            if checkpoint:
                adapter = CheckPoint(transport, username, password, "Network" if demo else self.layer.text().strip(), "Lab" if demo else self.package.text().strip(), "Lab gateway" if demo else self.target.text().strip(), "" if demo else self.domain.text().strip())
            else: adapter = PANOS(transport, username, password, "vsys1" if demo else self.vsys.text().strip()) if pan else SonicOS(transport, username, password)
            self.password.clear(); self.service = APIService(adapter, self.store)
            self.connection_key = self.settings_key()
            def connect():
                if previous: previous.close()
                return self.service.connect()
            self.run(connect, self.discovered)
        except Exception as error: self.failure(str(error)); self.update_controls()

    def discovered(self, snapshot):
        self.snapshot = snapshot
        self.status.setText(("SIMULATED" if self.service.transport.simulated else "LIVE HTTPS") + " • " + snapshot.hostname + " • Native access-rule provisioning; hardware qualification pending")

    def clear(self): self.rules = []; self.update_controls()

    def remove_rule(self):
        if not self.rules: return
        choice, ok = QInputDialog.getItem(self, "Remove staged rule", "Rule", [r["name"] for r in self.rules], 0, False)
        if ok: self.rules = [r for r in self.rules if r["name"] != choice]; self.update_controls()

    def draft_context(self):
        return {"platform": self.snapshot.platform, "scope": self.snapshot.data.get("context", {"vsys": self.snapshot.data.get("vsys", "")})}

    def save_draft(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save API draft", "firewall-draft.json", "JSON (*.json)")
        if path:
            try: Path(path).write_text(json.dumps({"schema": 1, **self.draft_context(), "rules": self.rules}, indent=2), encoding="utf-8")
            except OSError as error: QMessageBox.warning(self, "Save failed", str(error))

    def load_draft(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load API draft", "", "JSON (*.json)")
        if not path: return
        try:
            if Path(path).stat().st_size > 1_000_000: raise ValueError("Draft exceeds 1 MB.")
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(data, dict) or set(data) != {"schema", "platform", "scope", "rules"} or data["schema"] != 1 or any(data[k] != v for k, v in self.draft_context().items()): raise ValueError("Draft platform/policy scope does not match this connection.")
            self.service.adapter.plan(data["rules"], self.snapshot)
            self.rules = data["rules"]; self.update_controls()
        except (ValueError, OSError, TypeError) as error: QMessageBox.warning(self, "Invalid API draft", str(error))

    def add_rule(self):
        dialog = QDialog(self); dialog.setWindowTitle("New IPv4 access rule"); dialog.resize(620, 450)
        layout = QVBoxLayout(dialog); form = QFormLayout(); layout.addLayout(form); fields = {}
        schema = [("name", "New rule name", None)]
        if getattr(self.service.adapter, "zoned", True): schema += [("from_zone", "Source zone", self.snapshot.choices["zones"]), ("to_zone", "Destination zone", self.snapshot.choices["zones"])]
        schema += [("source", "Source address object", self.snapshot.choices["addresses"]), ("destination", "Destination address object", self.snapshot.choices["addresses"]), ("service", "Service object", self.snapshot.choices["services"]), ("action", "Action", ["deny", "allow"])]
        for key, title, choices in schema:
            field = QLineEdit() if choices is None else QComboBox()
            field.setObjectName("rule_" + key)
            if choices is not None: field.addItems(choices)
            fields[key] = field; form.addRow(title, field)
        note = QLabel("Rule is added at the end. Earlier rules may prevent it from taking effect. Existing objects are referenced; no NAT or management access is created."); note.setWordWrap(True); layout.addWidget(note)
        error = QLabel(); error.setWordWrap(True); layout.addWidget(error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel); layout.addWidget(buttons)
        def stage():
            row = {k: w.text().strip() if isinstance(w, QLineEdit) else w.currentText() for k, w in fields.items()}
            try: self.service.adapter.plan(self.rules + [row], self.snapshot)
            except ValueError as problem: error.setText(str(problem)); return
            self.rules.append(row); dialog.accept()
        buttons.accepted.connect(stage); buttons.rejected.connect(dialog.reject); dialog.exec(); self.update_controls()

    def preview(self): self.run(lambda: self.service.preview(self.rules), self.review)

    def review(self, plan):
        dialog = QDialog(self); dialog.setWindowTitle("Review native API deployment"); dialog.resize(900, 650)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit(); text.setReadOnly(True)
        text.setPlainText("Target: " + plan.snapshot.hostname + "\nPlatform: " + plan.snapshot.platform + "\n\n" + "\n".join(plan.warnings) + "\n\n" + json.dumps(plan.operations, indent=2)); layout.addWidget(text)
        confirm = QCheckBox("I reviewed the target, rule order and native payloads, and approve deployment."); layout.addWidget(confirm)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel); layout.addWidget(buttons)
        apply = buttons.button(QDialogButtonBox.StandardButton.Apply); apply.setEnabled(False); confirm.toggled.connect(apply.setEnabled)
        apply.clicked.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # The preview Job still owns the worker slot until its finished signal.
            from PySide6.QtCore import QTimer
            def deploy():
                if self.busy: QTimer.singleShot(20, deploy); return
                self.run(lambda: self.service.apply(plan), self.applied)
            QTimer.singleShot(0, deploy)

    def applied(self, result):
        snapshot, path = result; self.rules = []; self.discovered(snapshot)
        self.status.setText("API configuration readback verified. Traffic behavior remains untested. Backup: " + str(path))

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export API scopes (may contain secrets)", "firewall-api.json", "JSON (*.json)")
        if path:
            try: Path(path).write_text(self.snapshot.running, encoding="utf-8")
            except OSError as error: QMessageBox.warning(self, "Export failed", str(error))
