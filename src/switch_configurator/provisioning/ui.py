import json
from pathlib import Path
from PySide6.QtCore import QThread, Signal, QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QPushButton, QComboBox, QLineEdit, QPlainTextEdit, QTabWidget, QDialog,
    QDialogButtonBox, QMessageBox, QFileDialog, QCheckBox, QInputDialog, QTreeWidget, QTreeWidgetItem)
from .drivers import DRIVERS
from .model import Intent
from .service import ProvisioningService
from .demo import Demo
from .transport import SSHTransport


class Job(QThread):
    done = Signal(object)
    failed = Signal(str)
    output = Signal(str)
    def __init__(self, service, operation):
        super().__init__()
        self.service, self.operation = service, operation
    def run(self):
        old = self.service.log
        self.service.log = self.output.emit
        try: self.done.emit(self.operation())
        except Exception as e: self.failed.emit(str(e))
        finally: self.service.log = old


class EntryDialog(QDialog):
    def __init__(self, kind, snapshot, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Stage " + kind)
        self.resize(620, 440)
        layout = QVBoxLayout(self)
        notes = {
            "interfaces": "Set a static IPv4 address on an existing routed interface. This can disconnect management. Interface state is preserved.",
            "routes": "Add an IPv4 static route. Existing prefixes are not replaced. The next hop must be directly reachable through the selected interface.",
            "policies": "Add an explicit traffic rule. Existing policies are not replaced. Rule precedence and stateful/stateless behavior depend on the platform; inspect the review warnings.",
            "nat": "Add a RouterOS source masquerade rule. This does not add a permit rule. Existing NAT rules retain their order.",
        }
        hint = QLabel(notes[kind]); hint.setWordWrap(True); layout.addWidget(hint)
        form = QFormLayout(); layout.addLayout(form)
        self.fields = {}
        schemas = {
            "interfaces": [("name", "Interface"), ("address", "IPv4 address / prefix")],
            "routes": [("id", "New identifier (numeric on FortiOS)"), ("destination", "Destination network / prefix"), ("gateway", "Next-hop IPv4 address"), ("interface", "Outgoing interface")],
            "policies": [("id", "New identifier (numeric on FortiOS)"), ("source", "Source network / prefix"), ("destination", "Destination network / prefix"), ("in_interface", "Ingress interface"), ("out_interface", "Egress interface"), ("protocol", "Protocol"), ("port", "Destination port (blank = any)"), ("action", "Action")],
            "nat": [("id", "New identifier"), ("source", "Source network / prefix"), ("out_interface", "Egress interface")],
        }
        choices = [name for name, item in snapshot.interfaces.items() if item["editable"]]
        if kind == "policies" and snapshot.platform == "fortios":
            schemas[kind].append(("nat", "Source NAT to outgoing interface"))
        for key, title in schemas[kind]:
            if key in ("name", "interface", "in_interface", "out_interface"):
                widget = QComboBox(); widget.addItems(choices)
            elif key in ("protocol", "action", "nat"):
                widget = QComboBox(); widget.addItems({"protocol": ["tcp", "udp", "icmp", "ip"], "action": ["deny", "allow"], "nat": ["disable", "enable"]}[key])
            else:
                widget = QLineEdit()
                widget.setPlaceholderText({"address": "10.20.0.1/24", "source": "10.20.0.0/24", "destination": "203.0.113.0/24", "gateway": "192.0.2.1", "id": "100", "port": "443"}.get(key, ""))
            self.fields[key] = widget
            form.addRow(title, widget)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
    def values(self):
        return {k: (w.currentText() if isinstance(w, QComboBox) else w.text().strip()) for k, w in self.fields.items()}


class ProvisioningPane(QWidget):
    history_changed = Signal()
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store, self.service, self.snapshot, self.job = store, None, None, None
        self.intent = Intent()
        layout = QVBoxLayout(self)
        title = QLabel("Router & firewall provisioning"); title.setObjectName("brand"); layout.addWidget(title)
        self.platform = QComboBox()
        for ident, driver in DRIVERS.items(): self.platform.addItem(driver.label, ident)
        self.mode = QComboBox(); self.mode.addItems(["Demo", "SSH"])
        row = QHBoxLayout(); row.addWidget(self.platform, 2); row.addWidget(self.mode)
        self.connect_button = QPushButton("Connect router / firewall")
        self.connect_button.clicked.connect(self.connect_device); row.addWidget(self.connect_button)
        self.refresh_button = QPushButton("Refresh discovery"); self.refresh_button.clicked.connect(self.refresh); row.addWidget(self.refresh_button)
        layout.addLayout(row)
        self.credentials = QWidget(); form = QFormLayout(self.credentials)
        hostrow = QHBoxLayout()
        self.host = QLineEdit(); self.host.setPlaceholderText("Hostname or IP")
        self.port = QLineEdit("22"); self.port.setMaximumWidth(80)
        self.username = QLineEdit(); self.username.setPlaceholderText("SSH username")
        for w in (self.host, self.port, self.username): hostrow.addWidget(w)
        form.addRow("SSH target", hostrow)
        secretrow = QHBoxLayout()
        self.password = QLineEdit(); self.password.setEchoMode(QLineEdit.EchoMode.Password); self.password.setPlaceholderText("Password (not saved)")
        self.secret = QLineEdit(); self.secret.setEchoMode(QLineEdit.EchoMode.Password); self.secret.setPlaceholderText("Enable secret, if required")
        secretrow.addWidget(self.password); secretrow.addWidget(self.secret); form.addRow("Credentials", secretrow)
        self.known_hosts = QLineEdit(); self.known_hosts.setPlaceholderText("Optional known_hosts file; otherwise ~/.ssh/known_hosts")
        form.addRow("Trusted host keys", self.known_hosts)
        hint = QLabel("SSH rejects unknown or changed host keys. Verify and record the device key in known_hosts before connecting. Credentials are not stored in drafts or history.")
        hint.setWordWrap(True); form.addRow(hint)
        layout.addWidget(self.credentials)
        self.mode.currentIndexChanged.connect(self.update_controls)
        self.platform.currentIndexChanged.connect(self.platform_changed)
        self.status = QLabel("Choose a platform and connect. All new drivers are experimental and hardware-untested.")
        self.status.setWordWrap(True); layout.addWidget(self.status)
        tabs = QTabWidget(); layout.addWidget(tabs, 1)
        editor = QWidget(); work = QVBoxLayout(editor)
        self.capability_label = QLabel(); self.capability_label.setWordWrap(True); work.addWidget(self.capability_label)
        wizard_row = QHBoxLayout()
        self.wizard_button = QPushButton("Provisioning wizard…"); self.wizard_button.setObjectName("primary")
        self.wizard_button.clicked.connect(self.open_wizard); wizard_row.addWidget(self.wizard_button)
        wizard_hint = QLabel("Start with a scenario, then review the complete draft before deployment.")
        wizard_hint.setWordWrap(True); wizard_row.addWidget(wizard_hint, 1); work.addLayout(wizard_row)
        actionrow = QHBoxLayout(); self.add_buttons = {}
        for kind, title in (("interfaces", "Set interface IPv4…"), ("routes", "Add static route…"), ("policies", "Add traffic rule…"), ("nat", "Add source NAT…"), ("services", "Network services…")):
            b = QPushButton(title); b.clicked.connect(lambda checked=False, k=kind: self.add_entry(k)); self.add_buttons[kind] = b; actionrow.addWidget(b)
        work.addLayout(actionrow)
        self.draft = QTreeWidget()
        self.draft.setHeaderLabels(["Change", "Target", "Requested settings"])
        self.draft.setRootIsDecorated(False)
        self.draft.setColumnWidth(0, 160); self.draft.setColumnWidth(1, 180)
        self.draft.setStyleSheet("QTreeWidget { background:#0c121c; border:1px solid #314155; padding:8px; } QTreeWidget::item { padding:10px; }")
        work.addWidget(self.draft)
        draftrow = QHBoxLayout()
        self.load_button = QPushButton("Load draft…"); self.load_button.clicked.connect(self.load_draft)
        self.save_button = QPushButton("Save draft…"); self.save_button.clicked.connect(self.save_draft)
        self.clear_button = QPushButton("Clear draft"); self.clear_button.clicked.connect(self.clear_draft)
        self.remove_button = QPushButton("Remove entry…"); self.remove_button.clicked.connect(self.remove_entry)
        self.review_button = QPushButton("Review provisioning…"); self.review_button.setObjectName("primary"); self.review_button.clicked.connect(self.preview)
        for b in (self.load_button, self.save_button, self.remove_button, self.clear_button, self.review_button): draftrow.addWidget(b)
        work.addLayout(draftrow); tabs.addTab(editor, "Provisioning draft")
        self.discovery = QPlainTextEdit(); self.discovery.setReadOnly(True); tabs.addTab(self.discovery, "Discovered configuration")
        self.activity = QPlainTextEdit(); self.activity.setReadOnly(True); self.activity.document().setMaximumBlockCount(15000); tabs.addTab(self.activity, "Provisioning activity")
        self.backup_button = QPushButton("Export discovered configuration…"); self.backup_button.clicked.connect(self.export_snapshot); layout.addWidget(self.backup_button)
        self.update_controls()

    @property
    def busy(self): return self.job is not None

    def update_controls(self):
        driver = DRIVERS[self.platform.currentData()]()
        connected = self.snapshot is not None and not self.busy and self.service is not None and self.service.transport.simulated == (self.mode.currentText() == "Demo")
        self.credentials.setVisible(self.mode.currentText() == "SSH")
        for w in (self.platform, self.mode, self.credentials, self.connect_button): w.setEnabled(not self.busy)
        self.refresh_button.setEnabled(self.service is not None and not self.busy)
        self.backup_button.setEnabled(connected)
        self.wizard_button.setEnabled(connected and bool(driver.capabilities))
        for kind, b in self.add_buttons.items(): b.setEnabled(connected and kind in driver.capabilities)
        for b in (self.load_button, self.clear_button, self.save_button, self.remove_button): b.setEnabled(not self.busy)
        self.review_button.setEnabled(connected and bool(driver.capabilities) and any(self.intent.to_dict().values()))
        names = {"interfaces": "Interface IPv4", "routes": "Static routes", "policies": "Traffic rules", "nat": "Source NAT", "services": "Network services"}
        capabilities = " • ".join(names[k] for k in driver.capabilities) or "Discovery and configuration export only; policy deployment is not implemented"
        if driver.id == "fortios": capabilities += " • Optional source NAT on allow policies"
        self.capability_label.setText("Available: " + capabilities + "\n" + driver.persistence)
        self.draft.clear()
        for kind, rows in self.intent.to_dict().items():
            for row in rows:
                if kind == "interfaces": details = "Set address to " + row["address"] + " (preserve interface state)"
                elif kind == "routes": details = row["destination"] + " via " + row["gateway"] + " on " + row["interface"]
                elif kind == "policies":
                    details = f"{row['action'].upper()} {row['protocol'].upper()} {row['port'] or 'any port'} • {row['source']} ({row['in_interface']}) → {row['destination']} ({row['out_interface']})"
                    if row.get("nat") == "enable": details += " • Source NAT enabled"
                elif kind == "services": details = row["type"].upper() + " • " + " • ".join(k + ": " + v for k, v in row.items() if k not in ("type", "id"))
                else: details = "Masquerade " + row["source"] + " through " + row["out_interface"]
                item = QTreeWidgetItem([names[kind], row.get("name", row.get("id")), details])
                item.setToolTip(2, details); self.draft.addTopLevelItem(item)

    def platform_changed(self):
        if self.service: self.service.transport.close()
        self.service, self.snapshot, self.intent = None, None, Intent()
        self.discovery.clear()
        self.status.setText("Platform changed. Connect to discover this device.")
        self.update_controls()

    def run(self, operation, callback):
        if self.busy: return
        self.job = Job(self.service, operation)
        self.job.output.connect(self.activity.appendPlainText)
        self.job.done.connect(callback); self.job.failed.connect(self.failure)
        self.job.finished.connect(self.finished)
        self.update_controls(); self.job.start()

    def finished(self):
        self.job.deleteLater(); self.job = None; self.update_controls(); self.history_changed.emit()

    def failure(self, message):
        self.snapshot = None
        self.status.setText("Operation failed. Reconnect or refresh before provisioning.")
        self.activity.appendPlainText("ERROR: " + message)
        QMessageBox.critical(self, "Provisioning failed", message)

    def connect_device(self):
        if self.service: self.service.transport.close()
        self.snapshot = None
        ident = self.platform.currentData()
        try:
            transport = Demo(ident) if self.mode.currentText() == "Demo" else SSHTransport(self.host.text().strip(), self.username.text().strip(), self.password.text(), DRIVERS[ident].ssh_type, int(self.port.text()), self.secret.text(), self.known_hosts.text().strip())
            self.password.clear(); self.secret.clear()
            self.service = ProvisioningService(ident, transport, self.store)
            self.status.setText("Connecting and reading configuration…")
            self.run(self.service.connect, self.discovered)
        except Exception as e: self.failure(str(e))

    def discovered(self, snapshot):
        self.snapshot = snapshot
        self.discovery.setPlainText(json.dumps(snapshot.interfaces, indent=2) + "\n\n" + snapshot.running)
        self.status.setText(("DEMO" if self.service.transport.simulated else "LIVE SSH") + " • " + snapshot.hostname + " • " + str(len(snapshot.interfaces)) + " interfaces • Experimental driver")

    def refresh(self):
        if self.service: self.run(self.service.discover, self.discovered)

    def add_entry(self, kind):
        if not self.snapshot: return
        if kind == "services":
            from .services_ui import ServiceDialog
            dialog = ServiceDialog(self.snapshot, self)
        else: dialog = EntryDialog(kind, self.snapshot, self)
        if dialog.exec() != QDialog.DialogCode.Accepted: return
        import copy
        intent = copy.deepcopy(self.intent)
        getattr(intent, kind).append(dialog.values())
        try: self.service.driver.plan(intent, self.snapshot)
        except ValueError as e:
            QMessageBox.warning(self, "Invalid draft", str(e)); return
        self.intent = intent; self.update_controls()

    def open_wizard(self):
        if self.busy or not self.snapshot: return
        from .wizard import ProvisioningWizard
        wizard = ProvisioningWizard("router", self.snapshot, self.intent, parent=self)
        if wizard.exec() == QDialog.DialogCode.Accepted and wizard.result is not None:
            self.intent = wizard.result
            self.status.setText("Scenario added to draft. Review provisioning to read fresh state and approve native commands.")
            self.update_controls()

    def clear_draft(self): self.intent = Intent(); self.update_controls()

    def remove_entry(self):
        entries = [(kind, i, f"{kind} • {row.get('name', row.get('id'))} • {row}") for kind, rows in self.intent.to_dict().items() for i, row in enumerate(rows)]
        if not entries: return
        choice, ok = QInputDialog.getItem(self, "Remove staged entry", "Entry", [e[2] for e in entries], 0, False)
        if ok:
            kind, index, _ = next(e for e in entries if e[2] == choice)
            getattr(self.intent, kind).pop(index)
            self.update_controls()

    def save_draft(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save provisioning draft", "provisioning.json", "JSON (*.json)")
        if path:
            try: Path(path).write_text(json.dumps({"schema": 1, "platform": self.platform.currentData(), "intent": self.intent.to_dict()}, indent=2), encoding="utf-8")
            except OSError as e: QMessageBox.warning(self, "Save failed", str(e))

    def load_draft(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load provisioning draft", "", "JSON (*.json)")
        if not path: return
        try:
            if Path(path).stat().st_size > 1_000_000: raise ValueError("Draft file exceeds 1 MB.")
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if set(data) != {"schema", "platform", "intent"} or data["schema"] != 1 or data["platform"] != self.platform.currentData(): raise ValueError("Select the matching platform before loading this draft.")
            intent = Intent.from_dict(data["intent"])
            if self.snapshot: self.service.driver.plan(intent, self.snapshot)
            self.intent = intent; self.update_controls()
        except (ValueError, OSError, TypeError) as e: QMessageBox.warning(self, "Invalid draft", str(e))

    def export_snapshot(self):
        if not self.snapshot: return
        path, _ = QFileDialog.getSaveFileName(self, "Export configuration (may contain secrets)", "device.cfg", "Configuration (*.cfg)")
        if path:
            try: Path(path).write_text(self.snapshot.running, encoding="utf-8")
            except OSError as e: QMessageBox.warning(self, "Export failed", str(e))

    def preview(self): self.run(lambda: self.service.preview(self.intent), self.review)

    def review(self, plan):
        if self.busy: QTimer.singleShot(50, lambda: self.review(plan)); return
        dialog = QDialog(self); dialog.setWindowTitle("Review router / firewall provisioning"); dialog.resize(1000, 780)
        layout = QVBoxLayout(dialog)
        title = QLabel(("DEMO" if self.service.transport.simulated else "LIVE SSH") + " • " + plan.snapshot.hostname + " • " + self.service.driver.label); title.setWordWrap(True); layout.addWidget(title)
        warnings = QLabel("\n".join(plan.warnings) + "\n" + plan.persistence); warnings.setWordWrap(True); layout.addWidget(warnings)
        tabs = QTabWidget(); layout.addWidget(tabs)
        for title, text in (("Native commands", "\n".join(plan.commands)), ("Requested settings", json.dumps(plan.intent.to_dict(), indent=2)), ("Before configuration", plan.snapshot.running)):
            view = QPlainTextEdit(text); view.setReadOnly(True); tabs.addTab(view, title)
        accept = QCheckBox("I reviewed rule order, implicit/default behavior, management access and persistence.")
        layout.addWidget(accept)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
        apply = buttons.button(QDialogButtonBox.StandardButton.Apply); apply.setEnabled(False); accept.toggled.connect(apply.setEnabled)
        apply.clicked.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted: self.run(lambda: self.service.apply(plan), self.applied)

    def applied(self, result):
        snapshot, path = result
        self.intent = Intent(); self.discovered(snapshot)
        self.status.setText("Configuration readback verified. Traffic/connectivity not tested. Backup: " + str(path))

    def shutdown(self):
        if self.service: self.service.transport.close()
