import os
import sys
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal, QSize, QRectF
from PySide6.QtGui import QColor, QFont, QPen, QPainter
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QLineEdit, QPlainTextEdit, QTabWidget, QSplitter,
    QListWidget, QListWidgetItem, QAbstractItemView, QDialog, QDialogButtonBox,
    QFormLayout, QCheckBox, QMessageBox, QInputDialog, QScrollArea, QGroupBox,
    QStyledItemDelegate, QStyle)
from .model import ChangeSet, PROFILES
from .transport import DemoTransport, SerialTransport
from .service import Service
from .storage import Store
from .vendors import DRIVERS, get_driver
from . import __version__

STYLE = """
QWidget { background:#101722; color:#dde6ef; font-family:'Segoe UI'; font-size:13px; }
QMainWindow, QDialog { background:#101722; }
QLabel#brand { font-size:24px; font-weight:700; color:#f5f8fc; }
QLabel#eyebrow { color:#54d6ba; font-size:11px; font-weight:700; }
QLabel#muted { color:#8d9dae; }
QLabel#metric { font-size:19px; font-weight:600; color:#e9f3ff; padding:12px; background:#192433; border-radius:6px; }
QPushButton { background:#26354a; border:1px solid #37485e; padding:9px 14px; border-radius:5px; }
QPushButton:hover { background:#344961; border-color:#54d6ba; }
QPushButton:focus { border:1px solid #78e8d0; }
QPushButton#primary:hover { background:#7ee9d1; }
QPushButton#primary { background:#54d6ba; color:#09241f; border:none; font-weight:700; }
QPushButton:disabled { color:#627084; background:#192330; border-color:#283344; }
QLineEdit, QComboBox, QPlainTextEdit { background:#0c121c; border:1px solid #314155; border-radius:4px; padding:7px; selection-background-color:#246e63; }
QPlainTextEdit { font-family:'Consolas'; font-size:12px; }
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus { border:1px solid #54d6ba; }
QToolTip { background:#26354a; color:#f5f8fc; border:1px solid #54d6ba; padding:6px; }
QTreeWidget { background:#131e2b; alternate-background-color:#192636; border:1px solid #314155; border-radius:6px; padding:4px; }
QTreeWidget::item { padding:9px 6px; border-bottom:1px solid #233244; }
QTreeWidget::item:selected { background:#20534b; color:#ffffff; }
QHeaderView::section { background:#223044; color:#b7c8da; border:none; padding:10px 8px; font-weight:600; }
QSplitter::handle { background:#26354a; width:3px; }
QListWidget { background:#16202d; border:1px solid #354255; border-radius:8px; padding:14px; }
QListWidget::item { background:#222e3e; border:2px solid #37485c; border-radius:5px; margin:4px; padding:5px; }
QListWidget::item:selected { background:#183f3b; border:2px solid #5ce4c5; }
QTabWidget::pane { border:1px solid #2b394a; border-radius:6px; }
QTabBar::tab { background:#182331; color:#aebed0; padding:12px 16px; border-bottom:3px solid #182331; }
QTabBar::tab:hover { background:#243448; color:#f5f8fc; }
QTabBar::tab:selected { color:#79ecd2; background:#233143; border-bottom:3px solid #54d6ba; }
QGroupBox { border:1px solid #304155; border-radius:6px; margin-top:16px; padding-top:20px; font-weight:600; }
QGroupBox::title { subcontrol-origin:margin; left:12px; color:#96a8bb; }
QCheckBox { spacing:8px; }
QScrollBar:vertical { background:#121d2a; width:12px; }
QScrollBar::handle:vertical { background:#34465e; min-height:25px; }
"""


class Worker(QThread):
    success = Signal(object)
    failure = Signal(str)
    log = Signal(str)

    def __init__(self, operation, service):
        super().__init__()
        self.operation, self.service = operation, service

    def run(self):
        previous = self.service.log
        self.service.log = self.log.emit
        try: self.success.emit(self.operation())
        except Exception as error: self.failure.emit(str(error))
        finally: self.service.log = previous


class PortDelegate(QStyledItemDelegate):
    """Paint each interface as a small jack with a link LED and native identifier."""
    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect).adjusted(3, 3, -3, -3)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.setBrush(QColor("#183f3b" if selected else "#202c3b"))
        painter.setPen(QPen(QColor("#5ce4c5" if selected else "#3b4c61"), 2 if selected else 1))
        painter.drawRoundedRect(rect, 6, 6)
        lines = index.data().split("\n")
        color = index.data(Qt.ItemDataRole.ForegroundRole).color()
        painter.setPen(QColor("#e7eef7"))
        font = QFont("Segoe UI", 9)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(rect.left() + 9, rect.top() + 4, rect.width() - 16, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, lines[0])
        jack = QRectF(rect.left() + 10, rect.top() + 30, 40, 31)
        painter.setBrush(QColor("#0a1019"))
        painter.setPen(QPen(QColor("#657283"), 2))
        painter.drawRoundedRect(jack, 2, 2)
        painter.setPen(QPen(QColor("#c7a75d"), 2))
        for pin in range(8):
            x = jack.left() + 6 + pin * 4
            painter.drawLine(int(x), int(jack.top() + 3), int(x), int(jack.top() + 11))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QRectF(rect.left() + 60, rect.top() + 34, 6, 6))
        painter.setPen(color)
        font.setBold(False)
        font.setPointSize(8)
        painter.setFont(font)
        painter.drawText(QRectF(rect.left() + 60, rect.top() + 45, rect.width() - 64, 16), Qt.AlignmentFlag.AlignLeft, lines[2])
        painter.setPen(QColor("#9fb0c3"))
        painter.drawText(rect.adjusted(10, 68, -6, -3), Qt.AlignmentFlag.AlignLeft, lines[3] if len(lines) > 3 else "")
        painter.restore()


class PortEditor(QDialog):
    def __init__(self, names, device, store, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configure selected ports")
        self.resize(580, 700)
        self.store = store
        self.capabilities = device.capabilities
        layout = QVBoxLayout(self)
        title = QLabel(f"Configure {len(names)} port{'s' if len(names) != 1 else ''}")
        title.setObjectName("brand")
        layout.addWidget(title)
        hint = QLabel("Check a field to change it. Mode/VLAN edits may update related memberships; review the exact CLI.\nProfiles set behavior; choose VLAN IDs for this network explicitly.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        platform_hint = QLabel(device.platform + "\nUnavailable fields are disabled for this driver.")
        platform_hint.setWordWrap(True)
        layout.addWidget(platform_hint)
        self.profiles = PROFILES | store.profiles()
        profile_row = QHBoxLayout()
        self.profile = QComboBox()
        self.profile.addItems(["Choose a profile…"] + list(self.profiles))
        profile_row.addWidget(self.profile)
        profile_row.addWidget(button("Load profile", self.load_profile))
        layout.addLayout(profile_row)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        panel = QWidget()
        form = QFormLayout(panel)
        self.fields = {}
        choices = {
            "enabled": ["Enabled", "Disabled"], "mode": ["access", "trunk"],
            "poe": ["auto", "never"], "speed": ["auto", "10", "100", "1000"],
            "duplex": ["auto", "full", "half"], "portfast": ["default", "enabled", "disabled"],
            "bpduguard": ["default", "enabled", "disabled"],
        }
        labels = {"description": "Description", "enabled": "Administrative state", "mode": "Switchport mode",
                  "access_vlan": "Access VLAN", "voice_vlan": "Voice VLAN (0 = remove)", "native_vlan": "Native VLAN",
                  "allowed_vlans": "Allowed VLANs", "poe": "PoE", "speed": "Speed (Mbps)", "duplex": "Duplex",
                  "portfast": "PortFast", "bpduguard": "BPDU Guard"}
        first = device.ports[names[0]].config
        for key, label in labels.items():
            check = QCheckBox(label)
            editor = QComboBox() if key in choices else QLineEdit()
            if key in choices: editor.addItems(choices[key])
            self.fields[key] = (check, editor)
            self.set_value(key, first[key])
            values = {str(device.ports[name].config[key]) for name in names}
            if len(values) > 1:
                check.setText(label + " • mixed")
                editor.setToolTip("Selected ports have different values. Check this field to replace them all.")
            editor.setEnabled(False)
            check.toggled.connect(editor.setEnabled)
            if key not in device.capabilities:
                check.setEnabled(False)
                check.setText(label + " (unavailable)")
                check.setToolTip("Not implemented for this platform; no substitute command will be sent.")
            form.addRow(check, editor)
        scroll.setWidget(panel)
        layout.addWidget(scroll)
        layout.addWidget(button("Save checked fields as custom profile…", self.save_profile))
        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color:#ffb071")
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        stage = buttons.addButton("Stage changes", QDialogButtonBox.ButtonRole.AcceptRole)
        stage.clicked.connect(self.validate_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def set_value(self, key, value):
        editor = self.fields[key][1]
        text = ("Enabled" if value else "Disabled") if key == "enabled" else str(value)
        if isinstance(editor, QComboBox): editor.setCurrentText(text)
        else: editor.setText(text)

    def patch(self):
        result = {}
        for key, (check, editor) in self.fields.items():
            if not check.isChecked(): continue
            value = editor.currentText() if isinstance(editor, QComboBox) else editor.text().strip()
            if key == "enabled": value = value == "Enabled"
            elif key in ("access_vlan", "voice_vlan", "native_vlan"): value = int(value)
            result[key] = value
        return result

    def validate_accept(self):
        try:
            if not self.patch(): raise ValueError("Check at least one field to change.")
            self.accept()
        except ValueError as error: self.error.setText(str(error))

    def load_profile(self):
        patch = self.profiles.get(self.profile.currentText())
        if not patch: return
        for key, (check, editor) in self.fields.items():
            check.setChecked(key in patch and key in self.capabilities)
            if key in patch and key in self.capabilities: self.set_value(key, patch[key])
        skipped = sorted(set(patch) - self.capabilities)
        self.error.setText("Profile fields unavailable on this platform: " + ", ".join(skipped) if skipped else "")

    def save_profile(self):
        try:
            patch = self.patch()
            if not patch: raise ValueError("Select fields before saving a profile.")
            name, ok = QInputDialog.getText(self, "Custom profile", "Profile name:")
            if ok and name.strip():
                self.store.save_profile(name.strip(), patch)
                self.profiles[name.strip()] = patch
                if self.profile.findText(name.strip()) < 0: self.profile.addItem(name.strip())
        except ValueError as error: self.error.setText(str(error))


def button(text, action, primary=False):
    widget = QPushButton(text)
    widget.clicked.connect(action)
    if primary: widget.setObjectName("primary")
    return widget


class Window(QMainWindow):
    def __init__(self, store):
        super().__init__()
        self.store = store
        self.service = None
        self.device = None
        self.changes = ChangeSet()
        self.busy = False
        self.workers = []
        self.setWindowTitle(f"Network Provisioning Studio • {__version__}")
        self.resize(1440, 990)
        self.setMinimumSize(1100, 740)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(26, 22, 26, 18)
        heading = QHBoxLayout()
        heading.addWidget(label("Network Provisioning Studio", "brand"))
        heading.addStretch()
        heading.addWidget(label("v1.0  /  RELEASE CANDIDATE", "eyebrow"))
        layout.addLayout(heading)
        layout.addWidget(label("01  Connect & discover     /     02  Stage configuration     /     03  Review & apply     /     04  Verify", "muted"))
        connection = QHBoxLayout()
        self.source = QComboBox()
        self.scan_ports()
        self.baud = QComboBox()
        self.baud.addItems(["9600", "19200", "38400", "57600", "115200"])
        self.scan_button = button("Rescan", self.scan_ports)
        self.connect_button = button("Connect", self.connect_device, True)
        self.terminal_button = button("Raw console…", self.open_terminal)
        self.refresh_button = button("Refresh state", self.refresh)
        for widget in (self.source, self.baud, self.scan_button, self.connect_button, self.terminal_button, self.refresh_button): connection.addWidget(widget)
        connection.addStretch()
        self.session = label("OFFLINE", "eyebrow")
        connection.addWidget(self.session)
        self.switch_header = QWidget()
        switch_layout = QVBoxLayout(self.switch_header)
        switch_layout.setContentsMargins(0, 0, 0, 0)
        switch_layout.addLayout(connection)
        layout.addWidget(self.switch_header)
        platform_row = QHBoxLayout()
        platform_row.addWidget(QLabel("Platform"))
        self.platform = QComboBox()
        self.platform.addItem("Auto-detect (Cisco IOS demo by default)", "auto")
        for ident, cls in DRIVERS.items(): self.platform.addItem(cls.label, ident)
        platform_row.addWidget(self.platform)
        platform_row.addWidget(label("New drivers are experimental. The device OS must match the selected platform.", "muted"), 1)
        switch_layout.addLayout(platform_row)
        self.metrics = label("Connect a console or explore the simulated switch", "metric")
        switch_layout.addWidget(self.metrics)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        workspace = QWidget()
        work = QVBoxLayout(workspace)
        toolbar = QHBoxLayout()
        self.view = QComboBox()
        self.view.addItems(["Physical ports", "Group by VLAN", "Group by link state"])
        self.view.currentIndexChanged.connect(self.render_ports)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter interface, description, VLAN or neighbor")
        self.search.textChanged.connect(self.render_ports)
        toolbar.addWidget(self.view)
        toolbar.addWidget(self.search, 1)
        self.wizard_button = button("Provisioning wizard…", self.open_switch_wizard, True)
        toolbar.addWidget(self.wizard_button)
        work.addLayout(toolbar)
        self.chassis = label("FRONT PANEL  /  no device", "eyebrow")
        work.addWidget(self.chassis)
        splitter = QSplitter()
        self.ports = QListWidget()
        self.ports.setItemDelegate(PortDelegate(self.ports))
        self.ports.setViewMode(QListWidget.ViewMode.IconMode)
        self.ports.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.ports.setMovement(QListWidget.Movement.Static)
        self.ports.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.ports.setSpacing(4)
        self.ports.setWordWrap(True)
        self.ports.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.ports.customContextMenuRequested.connect(self.port_menu)
        self.ports.itemSelectionChanged.connect(self.selection_changed)
        self.ports.itemDoubleClicked.connect(lambda _: self.configure())
        splitter.addWidget(self.ports)
        detail_panel = QWidget()
        details_layout = QVBoxLayout(detail_panel)
        details_layout.addWidget(label("PORT INSPECTOR", "eyebrow"))
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("Select a port to inspect its configuration, link state and staged changes.")
        details_layout.addWidget(self.details)
        self.configure_button = button("Configure selection…", self.configure, True)
        details_layout.addWidget(self.configure_button)
        splitter.addWidget(detail_panel)
        splitter.setSizes([970, 330])
        work.addWidget(splitter, 1)
        work.addWidget(label("● Green: linked    ● Gray: disconnected    ● Amber: error    * Pending    |    Ctrl / Shift / drag to select", "muted"))
        work.addWidget(label("Port layout is inferred from interface numbering; it is not a model-specific chassis drawing.", "muted"))
        staged = QHBoxLayout()
        self.pending = QLabel("No staged changes")
        staged.addWidget(self.pending, 1)
        self.vlan_button = button("Create / rename VLAN…", self.create_vlan)
        self.clear_button = button("Discard staged", self.clear_changes)
        self.preview_button = button("Review and apply…", self.preview_changes, True)
        for widget in (self.vlan_button, self.clear_button, self.preview_button): staged.addWidget(widget)
        work.addLayout(staged)
        self.tabs.addTab(workspace, "Switch workspace")
        console = QWidget()
        console_layout = QVBoxLayout(console)
        console_layout.addWidget(label("Live commands and responses. Terminal commands bypass modeled verification; refresh after manual edits.", "muted"))
        self.transcript = QPlainTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setFont(QFont("Consolas", 10))
        self.transcript.document().setMaximumBlockCount(15000)
        console_layout.addWidget(self.transcript)
        raw_row = QHBoxLayout()
        self.raw = QLineEdit()
        self.raw.setPlaceholderText("One native CLI command (privileged session; interactive prompts unsupported)")
        self.raw.returnPressed.connect(self.raw_command)
        raw_row.addWidget(self.raw)
        self.send_button = button("Send command", self.raw_command)
        raw_row.addWidget(self.send_button)
        console_layout.addLayout(raw_row)
        self.tabs.addTab(console, "Console / activity")
        self.inventory = QPlainTextEdit()
        self.inventory.setReadOnly(True)
        self.inventory.setPlaceholderText("Connect a switch to view its discovered inventory and native device responses.")
        self.tabs.addTab(self.inventory, "Inventory / discovery")
        self.history = QPlainTextEdit()
        self.history.setReadOnly(True)
        self.tabs.addTab(self.history, "Backups / history")
        from .provisioning.ui import ProvisioningPane
        self.provisioning = ProvisioningPane(store, self)
        self.tabs.addTab(self.provisioning, "Routers / firewalls")
        from .firewall_api.ui import APIPane
        self.firewall_api = APIPane(store, self)
        self.tabs.addTab(self.firewall_api, "Firewall APIs")
        self.firewall_api.history_changed.connect(self.update_history)
        from .inventory_ui import InventoryPane
        self.saved_devices = InventoryPane(store, self)
        self.saved_devices.connect_requested.connect(self.load_saved_connection)
        self.saved_devices.capture_requested.connect(self.capture_lab_evidence)
        self.tabs.addTab(self.saved_devices, "Saved devices")
        self.tabs.currentChanged.connect(lambda _: (self.switch_header.setVisible(self.tabs.currentWidget() not in (self.provisioning, self.firewall_api, self.saved_devices)), self.status.setVisible(self.tabs.currentWidget() not in (self.provisioning, self.firewall_api, self.saved_devices))))
        self.provisioning.history_changed.connect(self.update_history)
        self.status = label("Ready. Demo mode never connects to hardware.", "muted")
        layout.addWidget(self.status)
        self.update_history()
        self.update_controls()

    def scan_ports(self):
        self.source.clear()
        self.source.addItem("Simulated switch • demo", None)
        try:
            from serial.tools.list_ports import comports
            for port in comports(): self.source.addItem(f"{port.device} — {port.description}", port.device)
        except ImportError: pass

    def run(self, text, operation, callback):
        if self.busy: return
        self.busy = True
        self.status.setText(text)
        self.update_controls()
        worker = Worker(operation, self.service)
        self.workers.append(worker)
        worker.log.connect(self.transcript.appendPlainText)
        worker.success.connect(callback)
        worker.failure.connect(self.failure)
        worker.finished.connect(lambda: self.worker_finished(worker))
        worker.start()

    def worker_finished(self, worker):
        self.workers.remove(worker)
        worker.deleteLater()
        self.busy = False
        self.update_controls()

    def failure(self, message):
        self.status.setText("Operation failed — inspect console and refresh before editing.")
        self.transcript.appendPlainText("ERROR: " + message)
        self.device = None
        self.ports.clear()
        self.metrics.setText("Device state unavailable — reconnect or refresh")
        self.update_history()
        QMessageBox.critical(self, "Operation failed", message)

    def update_controls(self):
        available = self.device is not None and not self.busy
        for widget in (self.source, self.baud, self.platform, self.scan_button, self.connect_button, self.terminal_button): widget.setEnabled(not self.busy)
        self.refresh_button.setEnabled(self.service is not None and not self.busy)
        for widget in (self.ports, self.view, self.search, self.vlan_button, self.wizard_button): widget.setEnabled(available)
        self.configure_button.setEnabled(available and bool(self.ports.selectedItems()))
        self.preview_button.setEnabled(available and bool(self.changes.ports or self.changes.vlans))
        self.clear_button.setEnabled(not self.busy and bool(self.changes.ports or self.changes.vlans))
        self.send_button.setEnabled(self.service is not None and not self.busy)
        self.raw.setEnabled(self.service is not None and not self.busy)

    def connect_device(self):
        if self.changes.ports or self.changes.vlans:
            if QMessageBox.question(self, "Change session", "Discard staged changes and connect?") != QMessageBox.StandardButton.Yes: return
        port = self.source.currentData()
        driver_id = self.platform.currentData()
        from .inventory import DeviceProfile
        if isinstance(port, DeviceProfile):
            from .provisioning.transport import SSHTransport
            if driver_id != port.platform:
                QMessageBox.warning(self, "Platform mismatch", "The selected platform must match the saved SSH device. Load its connection again.")
                return
            types = {"cisco_ios": "cisco_ios", "cisco_nxos": "cisco_nxos", "arista_eos": "arista_eos", "aruba_cx": "aruba_aoscx", "juniper_junos": "juniper_junos", "extreme_exos": "extreme_exos", "dell_os10": "dell_os10", "tplink_jetstream": "tplink_jetstream"}
            try: credentials = self.saved_devices.inventory.connection_credentials(port) or {}
            except Exception as error:
                QMessageBox.warning(self, "Credential store unavailable", str(error))
                return
            if not credentials.get("password"):
                password, ok = QInputDialog.getText(self, "SSH password", "Password for " + port.username, QLineEdit.EchoMode.Password)
                if not ok: return
                credentials["password"] = password
            try: transport = SSHTransport(port.host, port.username, credentials["password"], types[driver_id], port.port, credentials.get("secret", ""), port.trust_file)
            except (ValueError, KeyError) as error:
                QMessageBox.warning(self, "Invalid SSH connection", str(error))
                return
        elif port: transport = SerialTransport(port, int(self.baud.currentText()), timeout=60 if driver_id == "juniper_junos" else 30)
        elif driver_id in ("auto", "cisco_ios"): transport = DemoTransport()
        else:
            from .vendor_demo import VendorDemoTransport
            transport = VendorDemoTransport(driver_id)
        if self.service: self.service.transport.close()
        self.device = None
        self.changes = ChangeSet()
        self.service = Service(transport, self.store, driver_id=driver_id)
        self.run("Connecting and discovering device…", self.service.connect, self.discovered)

    def open_terminal(self):
        port = self.source.currentData()
        from .inventory import DeviceProfile
        if isinstance(port, DeviceProfile):
            QMessageBox.information(self, "Raw console", "Raw console uses a physical COM port. Select a serial port to open it.")
            return
        if not port:
            QMessageBox.information(self, "Raw console", "Select a physical COM port first. The demo supports show commands in Console / activity.")
            return
        if QMessageBox.question(self, "Open manual console", "Open an unrestricted console on " + port + "?\nThis ends the managed session and discards staged changes. Manual edits bypass deployment review and verification.") != QMessageBox.StandardButton.Yes: return
        if self.service: self.service.transport.close()
        self.service = None
        self.device = None
        self.changes = ChangeSet()
        self.ports.clear()
        self.session.setText("MANUAL CONSOLE")
        self.update_controls()
        from .terminal import TerminalDialog
        TerminalDialog(port, int(self.baud.currentText()), self).exec()
        self.session.setText("OFFLINE — RECONNECT")
        self.metrics.setText("Manual console closed. Connect to rediscover device state.")
        self.pending.setText("No staged changes")
        self.details.clear()

    def discovered(self, device):
        self.device = device
        self.session.setText("SIMULATED SESSION" if self.service.transport.simulated else "LIVE SESSION")
        up = sum(port.status == "connected" for port in device.ports.values())
        self.metrics.setText(f"{device.hostname}   /   {device.model}   /   {device.version}    •    {up}/{len(device.ports)} linked    •    {len(device.vlans)} VLANs")
        self.chassis.setText(f"{device.platform}  /  DISCOVERED PHYSICAL INTERFACES")
        self.inventory.setPlainText("\n\n".join(f"> {cmd}\n{output}" for cmd, output in device.evidence.items()))
        self.status.setText("State refreshed. " + ("; ".join(device.warnings) if device.warnings else "Select ports to begin."))
        self.render_ports()

    def refresh(self):
        if self.service: self.run("Reading device state…", self.service.discover, self.discovered)

    def load_saved_connection(self, profile, credentials):
        if self.busy or self.provisioning.busy or self.firewall_api.busy:
            QMessageBox.information(self, "Operation in progress", "Wait for the active operation before loading another device.")
            return
        from .provisioning.drivers import DRIVERS as ROUTER_DRIVERS
        if profile.transport == "HTTPS API":
            if profile.platform not in ("sonicwall", "panos", "checkpoint"):
                QMessageBox.information(self, "API connection unavailable", "This API platform is not implemented yet.")
                return
            pane = self.firewall_api
            pane.platform.setCurrentIndex(pane.platform.findData({"panos": "panos_api", "sonicwall": "sonicos_api", "checkpoint": "checkpoint_api"}[profile.platform]))
            pane.mode.setCurrentText("HTTPS API"); pane.host.setText(profile.host); pane.port.setText(str(profile.port))
            pane.username.setText(profile.username); pane.password.setText(credentials.get("password", "")); pane.ca.setText(profile.trust_file)
            pane.vsys.setText(profile.api_context.get("vsys", "vsys1"))
            for key in ("domain", "layer", "package", "target"): getattr(pane, key).setText(profile.api_context.get(key, ""))
            self.tabs.setCurrentWidget(pane)
            return
        if profile.platform in ROUTER_DRIVERS and profile.transport == "SSH":
            pane = self.provisioning
            pane.platform.setCurrentIndex(pane.platform.findData(profile.platform))
            pane.mode.setCurrentText("SSH"); pane.host.setText(profile.host); pane.port.setText(str(profile.port))
            pane.username.setText(profile.username); pane.password.setText(credentials.get("password", "")); pane.secret.setText(credentials.get("secret", "")); pane.known_hosts.setText(profile.trust_file)
            self.tabs.setCurrentWidget(pane)
        elif profile.platform in DRIVERS:
            self.platform.setCurrentIndex(self.platform.findData(profile.platform))
            if profile.transport == "Serial":
                index = self.source.findData(profile.host)
                if index < 0: self.source.addItem(profile.name + " — " + profile.host, profile.host); index = self.source.count() - 1
            else:
                self.source.addItem(profile.name + " — SSH " + profile.host, profile); index = self.source.count() - 1
            self.source.setCurrentIndex(index); self.tabs.setCurrentIndex(0)
        else: QMessageBox.warning(self, "Unsupported connection", "This platform/connection combination is not supported.")

    def capture_lab_evidence(self):
        if self.busy or self.provisioning.busy or self.firewall_api.busy: return
        choices = {}
        if self.device and self.service: choices["Switch: " + self.device.hostname] = (self.service, self.discovered, False)
        if self.provisioning.snapshot and self.provisioning.service:
            choices["Router / firewall: " + self.provisioning.snapshot.hostname] = (self.provisioning.service, self.provisioning.discovered, True)
        if not choices:
            QMessageBox.information(self, "Lab evidence", "Connect and discover a device first. Demo captures will be labeled simulated.")
            return
        choice, ok = QInputDialog.getItem(self, "Lab evidence", "Refresh and capture which connected session?", list(choices), 0, False)
        if not ok: return
        service, discovered, router = choices[choice]
        from .qualification import capture
        def operation():
            snapshot = service.discover()
            return snapshot, capture(self.store, snapshot, service.transport.simulated)
        def finished(result):
            snapshot, path = result
            discovered(snapshot)
            QMessageBox.information(self, "Evidence saved", "Discovery evidence saved to:\n" + str(path) + "\n\nProvisioning qualification remains pending. Review configuration secrets before sharing.")
        if router: self.provisioning.run(operation, finished)
        else: self.run("Refreshing lab evidence…", operation, finished)

    def render_ports(self):
        selected = {item.data(Qt.ItemDataRole.UserRole) for item in self.ports.selectedItems()}
        self.ports.clear()
        if not self.device: return
        values = list(self.device.ports.values())
        if self.view.currentIndex() == 1: values.sort(key=lambda port: (port.vlan, port.name))
        elif self.view.currentIndex() == 2: values.sort(key=lambda port: (port.status, port.name))
        needle = self.search.text().lower()
        for port in values:
            if needle and needle not in f"{port.name} {port.config['description']} {port.vlan} {port.neighbor}".lower(): continue
            short = port.name.replace("GigabitEthernet", "Gi").replace("TenGi", "Te").replace("FastEthernet", "Fa")
            pending = " *" if port.name in self.changes.ports else ""
            mode = "TRUNK" if port.vlan == "trunk" else f"VLAN {port.vlan}"
            text = f"{short}{pending}\n● {port.status}\n{mode}\n{port.config['description'][:19]}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, port.name)
            item.setSizeHint(QSize(148, 90))
            item.setForeground(QColor("#ffbc75" if port.status == "err-disabled" else "#63dfbd" if port.status == "connected" else "#9bacc0"))
            item.setToolTip(f"{port.name}\n{port.speed} • PoE {port.poe} / {port.watts} W\n{port.neighbor}" + ("\nRead-only: routed, channel-group, or template port" if not port.manageable else ""))
            self.ports.addItem(item)
            item.setSelected(port.name in selected)
        self.pending.setText(f"{len(self.changes.ports)} ports staged  •  {len(self.changes.vlans)} VLAN changes")
        self.selection_changed()

    def selection_changed(self):
        items = self.ports.selectedItems()
        if self.device and items:
            port = self.device.ports[items[0].data(Qt.ItemDataRole.UserRole)]
            lines = [f"{len(items)} port(s) selected", "", port.name, f"Link: {port.status}", f"Speed: {port.speed}",
                     f"PoE: {port.poe} / {port.watts} W", f"Neighbor: {port.neighbor}", "", "CONFIGURATION"]
            lines.extend(f"{key}: {value}" for key, value in port.config.items())
            if port.name in self.changes.ports:
                lines += ["", "PENDING"] + [f"{key} → {value}" for key, value in self.changes.ports[port.name].items()]
            self.details.setPlainText("\n".join(lines))
        else: self.details.setPlainText("Select a port to inspect its configuration and operational state.")
        self.update_controls()

    def port_menu(self, pos):
        item = self.ports.itemAt(pos)
        if item and not item.isSelected():
            self.ports.clearSelection()
            item.setSelected(True)
        if self.ports.selectedItems(): self.configure()

    def configure(self):
        if self.busy or not self.device: return
        names = [item.data(Qt.ItemDataRole.UserRole) for item in self.ports.selectedItems()]
        if not names: return
        if any(not self.device.ports[name].manageable for name in names):
            QMessageBox.warning(self, "Read-only selection", "Routed, EtherChannel, and template-derived ports require manual configuration.")
            return
        editor = PortEditor(names, self.device, self.store, self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            import copy
            candidate = copy.deepcopy(self.changes)
            for name in names: candidate.ports[name] = candidate.ports.get(name, {}) | editor.patch()
            try: get_driver(self.device.driver_id).commands(candidate, self.device)
            except ValueError as error:
                QMessageBox.warning(self, "Invalid changes", str(error))
                return
            self.changes = candidate
            self.render_ports()

    def create_vlan(self):
        number, ok = QInputDialog.getInt(self, "VLAN", "VLAN ID", 40, 1, 4094)
        if not ok: return
        name, ok = QInputDialog.getText(self, "VLAN", "VLAN name (letters, numbers, underscore, hyphen):")
        if not ok: return
        import copy
        candidate = copy.deepcopy(self.changes)
        candidate.vlans[number] = name.strip()
        try: get_driver(self.device.driver_id).commands(candidate, self.device)
        except ValueError as error:
            QMessageBox.warning(self, "Invalid VLAN", str(error))
            return
        self.changes = candidate
        self.render_ports()

    def open_switch_wizard(self):
        if self.busy or not self.device: return
        from .provisioning.wizard import ProvisioningWizard
        selected = [item.data(Qt.ItemDataRole.UserRole) for item in self.ports.selectedItems()]
        wizard = ProvisioningWizard("switch", self.device, self.changes, selected, self)
        if wizard.exec() == QDialog.DialogCode.Accepted and wizard.result is not None:
            self.changes = wizard.result
            self.render_ports()
            self.status.setText("Scenario staged. Review and apply to capture fresh state and approve commands.")

    def clear_changes(self):
        self.changes = ChangeSet()
        self.render_ports()
        self.update_controls()

    def preview_changes(self):
        self.run("Capturing current configuration and generating preview…", lambda: self.service.preview(self.changes), self.show_preview)

    def show_preview(self, preview):
        # Queue the modal review until the worker has finished, so apply can start a new worker.
        from PySide6.QtCore import QTimer
        if self.busy:
            QTimer.singleShot(50, lambda: self.show_preview(preview))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Review deployment")
        dialog.resize(880, 730)
        layout = QVBoxLayout(dialog)
        layout.addWidget(label("Review native CLI", "brand"))
        layout.addWidget(QLabel(f"Target: {preview.device.hostname} • {preview.device.platform} • {'SIMULATED' if self.service.transport.simulated else 'LIVE SERIAL'}"))
        hint = QLabel("A before-backup is required before transmission. Errors stop deployment; partial changes are possible.\n" + preview.device.persistence)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        tabs = QTabWidget()
        for title, text in (("Exact commands", "\n".join(preview.commands)), ("Modeled diff", preview.diff), ("Current configuration", preview.device.running)):
            editor = QPlainTextEdit(text)
            editor.setReadOnly(True)
            editor.setFont(QFont("Consolas", 10))
            tabs.addTab(editor, title)
        layout.addWidget(tabs)
        layout.addWidget(button("Copy commands", lambda: QApplication.clipboard().setText("\n".join(preview.commands))))
        approve = QCheckBox("I reviewed the target, selected interfaces, and commands.")
        layout.addWidget(approve)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        apply = buttons.addButton("Apply and verify", QDialogButtonBox.ButtonRole.AcceptRole)
        apply.setEnabled(False)
        approve.toggled.connect(apply.setEnabled)
        apply.clicked.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.run("Applying commands and verifying resulting state…", lambda: self.service.apply(preview), self.applied)

    def applied(self, result):
        device, path, warnings = result
        self.changes = ChangeSet()
        self.discovered(device)
        self.update_history()
        self.status.setText(f"Configuration verified. {'Warning: ' + ', '.join(warnings) if warnings else ''} Backups: {path}")

    def raw_command(self):
        if self.busy or not self.service: return
        command = self.raw.text().strip()
        if not command: return
        if not command.startswith("show "):
            QMessageBox.information(self, "Managed console", "This activity panel supports read-only show commands. Use the reviewed deployment workflow for changes, or open Raw console for a manual session.")
            return
        # Block shell escapes, control characters, and pipe extensions in this read-only console.
        if any(ord(c) < 32 or ord(c) > 126 for c in command) or any(c in command for c in "|;?"):
            QMessageBox.warning(self, "Unsupported terminal input", "Enter one show command without pipes or control characters.")
            return
        self.raw.clear()
        self.run("Reading console response…", lambda: self.service.execute(command), lambda _: self.status.setText("Console command completed."))

    def update_history(self):
        self.history.setPlainText(f"Local data: {self.store.root}\nBackups contain device configuration, which may include secrets. Protect this folder.\n\n" + "\n\n".join(f"{date}  •  {host}  •  {status}\n{path}" for date, host, status, path in self.store.history()))

    def closeEvent(self, event):
        if self.busy or self.provisioning.busy or self.firewall_api.busy:
            QMessageBox.information(self, "Operation in progress", "Wait for the active console operation to finish before closing.")
            event.ignore()
        else:
            if self.service: self.service.transport.close()
            self.provisioning.shutdown()
            if self.firewall_api.service:
                try: self.firewall_api.service.close()
                except Exception as error:
                    QMessageBox.warning(self, "Remote session cleanup", "Remote logout could not be confirmed. Inspect any pending API session on the device.\n" + str(error))
            event.accept()


def label(text, name):
    widget = QLabel(text)
    widget.setObjectName(name)
    return widget


def main():
    if "--smoke-test" in sys.argv:
        from .release_smoke import run
        index = sys.argv.index("--smoke-test")
        sys.exit(run(Path(sys.argv[index + 1])))
    app = QApplication(sys.argv)
    app.setApplicationName("Network Provisioning Studio")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    data = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "share"))) / "VisualSwitchConfigurator"
    window = Window(Store(data))
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__": main()
