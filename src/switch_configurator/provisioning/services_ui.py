from PySide6.QtWidgets import QDialog, QVBoxLayout, QFormLayout, QComboBox, QLineEdit, QLabel, QDialogButtonBox, QWidget
from .network_services import SCHEMAS, validate, eligible


class ServiceDialog(QDialog):
    def __init__(self, snapshot, parent=None):
        super().__init__(parent)
        self.snapshot = snapshot
        self.setWindowTitle("Network service scenario — " + {"junos_routing": "Junos", "routeros": "RouterOS 7"}.get(snapshot.platform, "Cisco IOS / IOS-XE"))
        self.resize(690, 460)
        layout = QVBoxLayout(self)
        hint = QLabel("Stage a service for command review. Existing service configurations may block this scenario. No configuration is sent from this form.")
        hint.setWordWrap(True); layout.addWidget(hint)
        self.choice = QComboBox()
        for kind, (title, _) in SCHEMAS.items():
            if snapshot.platform == "junos_routing" and kind not in ("dns", "ntp"): continue
            if (snapshot.platform == "routeros") != (kind == "wireguard"): continue
            self.choice.addItem(title, kind)
        layout.addWidget(self.choice)
        self.form_widget = QWidget(); self.form = QFormLayout(self.form_widget); layout.addWidget(self.form_widget)
        self.fields = {}
        self.notes = QLabel(); self.notes.setWordWrap(True); layout.addWidget(self.notes)
        self.error = QLabel(); self.error.setWordWrap(True); layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Stage service")
        buttons.accepted.connect(self.stage); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        self.choice.currentIndexChanged.connect(self.rebuild); self.rebuild()

    def rebuild(self):
        while self.form.rowCount(): self.form.removeRow(0)
        self.fields = {}
        kind = self.choice.currentData()
        for key, title in (("id", "Unique draft identifier"),) + SCHEMAS[kind][1]:
            if key == "interface":
                field = QComboBox(); field.addItems([n for n, p in self.snapshot.interfaces.items() if eligible(self.snapshot, n) and (kind != "svi" or (n.startswith("Vlan") and not p.get("address")))])
            else: field = QLineEdit()
            self.fields[key] = field; self.form.addRow(title, field)
        self.notes.setText({
            "wireguard": "Creates a WireGuard interface, local address, one peer and remote-network route. The router generates its private key. Configure the remote peer's return route and this router's public key separately. Endpoint UDP input and tunnel forwarding must be permitted separately; no firewall rules or NAT are added.",
            "svi": "Sets IPv4 on an existing unaddressed SVI. Create the VLAN and VLAN interface separately. Administrative state is preserved; no routing or VLAN membership is enabled by this scenario.",
            "dns": "Adds a resolver address for the device. Does not enable a DNS server or override VRF/disabled lookup settings.",
            "ntp": "Adds an unauthenticated NTP source. Existing authentication, source or access restrictions require a dedicated plan.",
            "dhcp": "Uses the selected interface's IPv4 subnet and gateway. Excludes all hosts outside your lease range. Existing pools, exclusions or interface relays block this scenario. Ensure another DHCP server is not serving this LAN.",
            "ipv6": "Adds one address to an interface with no IPv6 address. IPv6 forwarding must already be enabled. Administrative state and firewall policy are unchanged.",
            "route6": "Adds a route through a directly connected IPv6 next hop. A link-local next hop uses the selected outgoing interface. Configure its IPv6 address first, or stage it in this draft.",
            "ospf": "Creates one OSPFv2 process and enables adjacency on exactly one interface. Other interfaces are passive. Existing OSPF blocks this scenario. No default route origination, redistribution or authentication is configured.",
        }[kind])
        self.error.clear()

    def values(self):
        return {"type": self.choice.currentData(), **{k: w.currentText() if isinstance(w, QComboBox) else w.text().strip() for k, w in self.fields.items()}}

    def stage(self):
        try: validate([self.values()])
        except ValueError as error: self.error.setText(str(error)); return
        self.accept()
