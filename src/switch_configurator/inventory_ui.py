from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (QWidget, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit,
    QComboBox, QCheckBox, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QMessageBox, QDialogButtonBox)
from .inventory import Inventory, DeviceProfile
from .provisioning.drivers import DRIVERS
from .vendors import DRIVERS as SWITCH_DRIVERS


class ProfileEditor(QDialog):
    def __init__(self, profile=None, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.setWindowTitle("Saved device"); self.resize(660, 640)
        layout = QVBoxLayout(self); form = QFormLayout(); layout.addLayout(form)
        self.fields = {}
        for key, title in (("name", "Display name"), ("site", "Site"), ("role", "Role"), ("platform", "Platform"), ("transport", "Connection"), ("host", "Hostname / IP / COM port"), ("port", "TCP port"), ("username", "Username"), ("model", "Model"), ("firmware", "Firmware"), ("trust_file", "Known-hosts / CA file")):
            if key == "platform":
                w = QComboBox()
                for ident, cls in DRIVERS.items(): w.addItem(cls.label, ident)
                for ident, cls in SWITCH_DRIVERS.items(): w.addItem("Switch: " + cls.label, ident)
                if profile: w.setCurrentIndex(w.findData(profile.platform))
            elif key == "transport":
                w = QComboBox(); w.addItems(["SSH", "Serial", "HTTPS API"])
                if profile: w.setCurrentText(profile.transport)
            else:
                w = QLineEdit(str(getattr(profile, key)) if profile else ("22" if key == "port" else ""))
            self.fields[key] = w; form.addRow(title, w)
        self.fields["transport"].currentTextChanged.connect(self.connection_changed)
        self.remember = QCheckBox("Store/replace credentials in Windows Credential Manager")
        layout.addWidget(self.remember)
        self.password = QLineEdit(); self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.secret = QLineEdit(); self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Password / API key", self.password); form.addRow("Enable secret (optional)", self.secret)
        self.password.setEnabled(False); self.secret.setEnabled(False)
        self.remember.toggled.connect(self.password.setEnabled); self.remember.toggled.connect(self.secret.setEnabled)
        self.scope = QWidget(); self.scope_form = QFormLayout(self.scope); self.scope_fields = {}
        for key, title in (("vsys", "PAN-OS virtual system"), ("domain", "Check Point domain"), ("layer", "Access layer"), ("package", "Policy package"), ("target", "Installation gateway")):
            field = QLineEdit(profile.api_context.get(key, "vsys1" if key == "vsys" else "") if profile else ("vsys1" if key == "vsys" else ""))
            self.scope_fields[key] = field; self.scope_form.addRow(title, field)
        layout.addWidget(self.scope)
        self.fields["platform"].currentIndexChanged.connect(self.update_scope)
        self.fields["transport"].currentIndexChanged.connect(self.update_scope)
        self.update_scope()
        self.error = QLabel(); self.error.setWordWrap(True); layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.validate_accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)

    def value(self):
        data = {}
        for key, widget in self.fields.items():
            data[key] = (widget.currentData() if key == "platform" else widget.currentText()) if isinstance(widget, QComboBox) else widget.text().strip()
        data["port"] = int(data["port"])
        context = {k: w.text().strip() for k, w in self.scope_fields.items() if (k == "vsys") == (data["platform"] == "panos")}
        if data["transport"] != "HTTPS API" or data["platform"] not in ("panos", "checkpoint"): context = {}
        return DeviceProfile(**data, id=self.profile.id if self.profile else "", api_context=context)

    def update_scope(self):
        platform = self.fields["platform"].currentData()
        self.scope.setVisible(self.fields["transport"].currentText() == "HTTPS API" and platform in ("panos", "checkpoint"))
        for key, field in self.scope_fields.items():
            visible = (key == "vsys") == (platform == "panos")
            field.setVisible(visible); self.scope_form.labelForField(field).setVisible(visible)

    def connection_changed(self, connection):
        port = self.fields["port"]
        if connection == "HTTPS API" and port.text() == "22": port.setText("443")
        elif connection == "SSH" and port.text() == "443": port.setText("22")

    def validate_accept(self):
        try:
            self.value().validate()
            if self.remember.isChecked() and not self.password.text(): raise ValueError("Enter a credential, or leave secure storage unchecked to preserve the existing one.")
            self.accept()
        except ValueError as error: self.error.setText(str(error))


class InventoryPane(QWidget):
    connect_requested = Signal(object, object)
    capture_requested = Signal()
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.inventory = Inventory(store)
        layout = QVBoxLayout(self)
        hint = QLabel("Saved devices by site and role. Passwords and API keys are stored only in Windows Credential Manager when requested.")
        hint.setWordWrap(True); layout.addWidget(hint)
        self.search = QLineEdit(); self.search.setPlaceholderText("Search name, site, platform, model or firmware"); self.search.textChanged.connect(self.refresh); layout.addWidget(self.search)
        self.tree = QTreeWidget(); self.tree.setHeaderLabels(["Device", "Site", "Role", "Platform", "Endpoint", "Model", "Firmware"]); self.tree.setRootIsDecorated(False); layout.addWidget(self.tree)
        row = QHBoxLayout()
        for title, callback in (("Add device…", self.add), ("Edit…", self.edit), ("Load connection", self.load), ("Forget credentials", self.forget), ("Remove device", self.remove)):
            b = QPushButton(title); b.clicked.connect(callback); row.addWidget(b)
        layout.addLayout(row); self.refresh()
        hint = QLabel("Hardware qualification is pending. A discovery capture records observations; it does not certify provisioning. Captures may contain configuration secrets.")
        hint.setWordWrap(True); layout.addWidget(hint)
        capture_button = QPushButton("Capture connected device lab evidence…")
        capture_button.clicked.connect(self.capture_requested.emit); layout.addWidget(capture_button)

    def refresh(self):
        self.tree.clear(); needle = self.search.text().lower()
        for p in self.inventory.all():
            values = [p.name, p.site, p.role, p.platform, f"{p.host}:{p.port}", p.model, p.firmware]
            if needle and needle not in " ".join(values).lower(): continue
            item = QTreeWidgetItem(values); item.setData(0, Qt.ItemDataRole.UserRole, p); self.tree.addTopLevelItem(item)

    def selected(self):
        item = self.tree.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item else None

    def add(self): self.edit_profile(None)
    def edit(self):
        if self.selected(): self.edit_profile(self.selected())
    def edit_profile(self, profile):
        dialog = ProfileEditor(profile, self)
        if dialog.exec() != QDialog.DialogCode.Accepted: return
        try:
            self.inventory.save(dialog.value(), dialog.password.text() if dialog.remember.isChecked() else None, dialog.secret.text())
            self.refresh()
        except Exception as error: QMessageBox.warning(self, "Save failed", str(error))
    def load(self):
        profile = self.selected()
        if not profile: return
        try: self.connect_requested.emit(profile, self.inventory.credentials(profile.id) or {})
        except Exception as error: QMessageBox.warning(self, "Credential store unavailable", str(error))
    def forget(self):
        profile = self.selected()
        if not profile: return
        try: self.inventory.forget_credentials(profile.id)
        except Exception as error: QMessageBox.warning(self, "Credential removal failed", str(error))
    def remove(self):
        profile = self.selected()
        if not profile: return
        if QMessageBox.question(self, "Remove saved device", f"Remove {profile.name} and its saved credentials? Device configuration and backup history are unaffected.") != QMessageBox.StandardButton.Yes: return
        try: self.inventory.remove(profile.id); self.refresh()
        except Exception as error: QMessageBox.warning(self, "Removal failed", str(error))
