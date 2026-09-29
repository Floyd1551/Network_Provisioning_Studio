"""Three-step scenario wizard. Finish adds intent to a draft; it never deploys."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWizard, QWizardPage, QVBoxLayout, QFormLayout, QLabel,
    QComboBox, QLineEdit, QCheckBox, QListWidget, QListWidgetItem, QPlainTextEdit,
    QTabWidget, QScrollArea, QWidget)
from .scenarios import (ROUTER_SCENARIOS, SWITCH_SCENARIOS, unavailable,
                        compile_router, compile_switch)
from .drivers import DRIVERS


def wrapped(text=""):
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


class ScenarioPage(QWizardPage):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setTitle("1. Choose a provisioning scenario")
        self.setSubTitle("The wizard stages changes for the connected device. You review native commands before applying them.")
        layout = QVBoxLayout(self)
        platform = owner.snapshot.platform if owner.kind == "switch" else DRIVERS[owner.snapshot.platform].label
        layout.addWidget(wrapped("Target: " + owner.snapshot.hostname + " • " + platform))
        self.choice = QComboBox()
        scenarios = ROUTER_SCENARIOS if owner.kind == "router" else SWITCH_SCENARIOS
        self.scenarios = {s.id: s for s in scenarios}
        self.reasons = {}
        for s in scenarios:
            reason = unavailable(s, owner.snapshot) if owner.kind == "router" else ""
            self.reasons[s.id] = reason
            self.choice.addItem(s.title + (" — unavailable" if reason else ""), s.id)
            item = self.choice.model().item(self.choice.count() - 1)
            if reason: item.setEnabled(False); item.setToolTip(reason)
        layout.addWidget(self.choice)
        self.description = wrapped(); layout.addWidget(self.description)
        self.scope = wrapped(); layout.addWidget(self.scope)
        layout.addStretch()
        self.choice.currentIndexChanged.connect(self.changed)
        first = next((i for i in range(self.choice.count()) if not self.reasons[self.choice.itemData(i)]), 0)
        self.choice.setCurrentIndex(first)
        self.changed()

    @property
    def scenario(self): return self.scenarios[self.choice.currentData()]

    def changed(self):
        scenario = self.scenario
        self.description.setText(scenario.description)
        self.scope.setText("\n".join(scenario.follow_up) + ("\n" + self.reasons[scenario.id] if self.reasons[scenario.id] else ""))
        self.completeChanged.emit()

    def isComplete(self): return not self.reasons[self.scenario.id]


class DetailsPage(QWizardPage):
    def __init__(self, owner):
        super().__init__()
        self.owner, self.built_for, self.fields = owner, None, {}
        self.setTitle("2. Enter network settings")
        self.setSubTitle("Only discovered, editable interfaces are offered. Existing draft entries are preserved.")
        layout = QVBoxLayout(self)
        self.scope = wrapped(); layout.addWidget(self.scope)
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True); layout.addWidget(self.scroll)
        self.error = wrapped(); self.error.setStyleSheet("color:#ffbc75;"); layout.addWidget(self.error)

    def initializePage(self):
        scenario = self.owner.scenario_page.scenario
        if self.built_for == scenario.id: return
        self.built_for = scenario.id
        self.fields = {}
        self.error.clear()
        panel = QWidget(); self.form = QFormLayout(panel)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        old = self.scroll.takeWidget()
        if old: old.deleteLater()
        self.scroll.setWidget(panel)
        self.scope.setText(scenario.description)
        titles = {
            "lan": "LAN / ingress interface", "lan_address": "LAN IPv4 address / prefix", "wan": "WAN / egress interface",
            "source": "Source network / prefix", "destination": "Destination network / prefix", "gateway": "Next-hop IPv4 address",
            "base_id": "Starting identifier", "access": "Outbound traffic", "source_nat": "Source NAT",
            "add_default": "Default route", "protocol": "Protocol", "port": "Destination port", "action": "Action",
            "ports": "Switch ports", "vlan": "Access VLAN ID", "vlan_name": "VLAN name (new VLANs)",
            "description": "Port description (optional)", "enable": "Administrative state", "native": "Native VLAN ID", "allowed": "Allowed / tagged VLANs",
        }
        if scenario.id == "branch":
            titles["destination"] = "Route destination / prefix"
            titles["access"] = "Traffic to any destination"
        if self.owner.kind == "router":
            interfaces = [n for n, p in self.owner.snapshot.interfaces.items() if p["editable"]]
            wan = next((n for n in interfaces if self.owner.snapshot.interfaces[n].get("address")), interfaces[0] if interfaces else "")
            lan = next((n for n in interfaces if n != wan and not self.owner.snapshot.interfaces[n].get("address")), next((n for n in interfaces if n != wan), wan))
        for key in scenario.fields:
            if key in ("lan", "wan"):
                w = QComboBox(); w.addItems(interfaces); w.setCurrentText(lan if key == "lan" else wan)
            elif key == "ports":
                w = QListWidget(); w.setMinimumHeight(180)
                for name, port in self.owner.snapshot.ports.items():
                    item = QListWidgetItem(name + (" — read-only" if not port.manageable else ""))
                    item.setData(Qt.ItemDataRole.UserRole, name)
                    if port.manageable:
                        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                        item.setCheckState(Qt.CheckState.Checked if name in self.owner.selected_ports else Qt.CheckState.Unchecked)
                    else: item.setFlags(Qt.ItemFlag.NoItemFlags)
                    w.addItem(item)
            elif key in ("source_nat", "add_default", "enable"):
                text = {"source_nat": "Translate the source to the outgoing interface address", "add_default": "Add a default route (0.0.0.0/0) through this WAN", "enable": "Enable selected ports (otherwise preserve current state)"}[key]
                w = QCheckBox(text)
                if key == "source_nat" and self.owner.snapshot.platform not in ("fortios", "routeros"):
                    w.setEnabled(False); w.setToolTip("Source NAT is not supported by this platform's provisioning driver.")
            elif key in ("access", "protocol", "action"):
                w = QComboBox()
                options = {"access": [("Routing only", "routing_only"), ("Allow HTTPS (TCP 443)", "https"), ("Allow all IPv4 traffic", "all")],
                           "protocol": [("TCP", "tcp"), ("UDP", "udp"), ("ICMP", "icmp"), ("All IPv4 protocols", "ip")],
                           "action": [("Allow", "allow"), ("Deny", "deny")]}
                for title, value in options[key]: w.addItem(title, value)
                if key == "access" and "policies" not in DRIVERS[self.owner.snapshot.platform].capabilities:
                    for i in (1, 2): w.model().item(i).setEnabled(False)
            else:
                w = QLineEdit()
                w.setPlaceholderText({"lan_address": "10.20.0.1/24", "source": "10.20.0.0/24", "destination": "203.0.113.0/24", "gateway": "192.0.2.1", "base_id": "1000", "vlan": "40", "vlan_name": "GUEST", "native": "1", "allowed": "10,20,40", "description": "Blank keeps existing descriptions", "port": "Blank means any destination port"}.get(key, ""))
                if key == "base_id": w.setText("1000")
                if key == "base_id": w.setToolTip("Choose unused IDs. A combined scenario uses this number for its route, the next number for its traffic rule, and the following number for RouterOS NAT.")
                if key == "destination" and scenario.id in ("branch", "outbound"): w.setText("0.0.0.0/0")
                if key == "port": w.setText("443")
            self.fields[key] = w
            self.form.addRow(titles[key], w)
        if "lan" in self.fields:
            self.fields["lan"].currentTextChanged.connect(self.suggest_lan)
            self.suggest_lan()
        if "protocol" in self.fields:
            self.fields["protocol"].currentIndexChanged.connect(self.options_changed)
        if "access" in self.fields:
            self.fields["access"].currentIndexChanged.connect(self.options_changed)
        if "add_default" in self.fields: self.fields["add_default"].toggled.connect(self.options_changed)
        if self.owner.kind == "switch" and scenario.id == "uplink" and self.owner.snapshot.driver_id in ("extreme_exos", "tplink_jetstream"):
            self.scope.setText(scenario.description + " On this platform the allowed list contains tagged VLANs only; exclude the native VLAN.")
        if "vlan" in self.fields: self.fields["vlan"].textChanged.connect(self.suggest_vlan)
        self.options_changed()

    def suggest_lan(self, *args):
        name = self.fields["lan"].currentText()
        staged = {r["name"]: r["address"] for r in self.owner.existing.interfaces}
        cidr = staged.get(name, self.owner.snapshot.interfaces.get(name, {}).get("address"))
        if "lan_address" in self.fields: self.fields["lan_address"].setText(cidr or "")
        if "source" in self.fields:
            from ipaddress import IPv4Interface
            self.fields["source"].setText(str(IPv4Interface(cidr).network) if cidr else "")

    def suggest_vlan(self, *args):
        text = self.fields["vlan"].text()
        if text.isdigit():
            names = self.owner.snapshot.vlans | self.owner.existing.vlans
            if int(text) in names: self.fields["vlan_name"].setText(names[int(text)])

    def options_changed(self, *args):
        if "protocol" in self.fields:
            ports = self.fields["protocol"].currentData() in ("tcp", "udp")
            self.fields["port"].setEnabled(ports)
            if not ports: self.fields["port"].clear()
        if "access" in self.fields:
            nat = self.fields["access"].currentData() != "routing_only" and self.owner.snapshot.platform in ("fortios", "routeros")
            self.fields["source_nat"].setEnabled(nat)
            if not nat: self.fields["source_nat"].setChecked(False)
        if "add_default" in self.fields:
            self.fields["gateway"].setEnabled(self.fields["add_default"].isChecked())

    def values(self):
        result = {}
        for key, widget in self.fields.items():
            if isinstance(widget, QCheckBox): result[key] = widget.isChecked()
            elif isinstance(widget, QComboBox): result[key] = widget.currentData() if key in ("access", "protocol", "action") else widget.currentText()
            elif isinstance(widget, QListWidget): result[key] = [widget.item(i).data(Qt.ItemDataRole.UserRole) for i in range(widget.count()) if widget.item(i).checkState() == Qt.CheckState.Checked]
            else: result[key] = widget.text().strip()
        return result

    def validatePage(self):
        try:
            compiler = compile_router if self.owner.kind == "router" else compile_switch
            self.owner.result, self.owner.commands, self.owner.notes = compiler(self.owner.scenario_page.scenario.id, self.values(), self.owner.snapshot, self.owner.existing)
            self.error.clear()
            return True
        except (ValueError, TypeError) as e:
            self.owner.result = None
            self.error.setText(str(e))
            return False


def summarize(kind, result):
    lines = []
    if kind == "switch":
        for number, name in result.vlans.items(): lines.append(f"Create VLAN {number}: {name}")
        for name, fields in result.ports.items(): lines.append(name + ": " + "; ".join(f"{k.replace('_', ' ')} = {v}" for k, v in fields.items()))
    else:
        for row in result.interfaces: lines.append(f"Address {row['name']}: {row['address']}")
        for row in result.routes: lines.append(f"Route {row['destination']} via {row['gateway']} on {row['interface']}")
        for row in result.policies:
            line = f"{row['action'].upper()} {row['protocol'].upper()} {row['port'] or 'any port'}: {row['source']} ({row['in_interface']}) → {row['destination']} ({row['out_interface']})"
            if row.get("nat") == "enable": line += " • source NAT enabled"
            lines.append(line)
        for row in result.nat: lines.append(f"Masquerade {row['source']} through {row['out_interface']}")
    return "\n".join(lines)


class SummaryPage(QWizardPage):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setTitle("3. Review the combined draft")
        self.setSubTitle("Existing staged entries are included. Add to draft does not send configuration commands.")
        layout = QVBoxLayout(self)
        tabs = QTabWidget(); layout.addWidget(tabs)
        self.summary = QPlainTextEdit(); self.summary.setReadOnly(True); tabs.addTab(self.summary, "Changes and follow-up")
        self.cli = QPlainTextEdit(); self.cli.setReadOnly(True); tabs.addTab(self.cli, "Native commands")
    def initializePage(self):
        self.summary.setPlainText(summarize(self.owner.kind, self.owner.result) + "\n\nFollow-up and platform notes\n\n" + "\n".join(self.owner.notes))
        self.cli.setPlainText("\n".join(self.owner.commands))


class ProvisioningWizard(QWizard):
    def __init__(self, kind, snapshot, existing, selected_ports=(), parent=None):
        super().__init__(parent)
        self.kind, self.snapshot, self.existing = kind, snapshot, existing
        self.selected_ports = set(selected_ports)
        self.result, self.commands, self.notes = None, [], []
        self.setWindowTitle("Provisioning scenario wizard")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.resize(900, 740)
        self.setMinimumSize(760, 620)
        self.setButtonText(QWizard.WizardButton.FinishButton, "Add to draft")
        self.scenario_page = ScenarioPage(self)
        self.details_page = DetailsPage(self)
        self.summary_page = SummaryPage(self)
        for page in (self.scenario_page, self.details_page, self.summary_page): self.addPage(page)
