"""Offline smoke check for the actual packaged runtime. Never opens a device."""
import json
import tempfile
import traceback
from pathlib import Path
from . import __version__


def run(report: Path):
    results = {"version": __version__, "simulated_only": True, "checks": []}
    try:
        from PySide6.QtWidgets import QApplication
        from .app import Window, STYLE
        from .storage import Store
        from .service import Service
        from .transport import DemoTransport
        from .vendor_demo import VendorDemoTransport
        from .vendors import DRIVERS
        from .provisioning.drivers import DRIVERS as ROUTERS
        from .provisioning.demo import Demo
        from .provisioning.service import ProvisioningService
        from .firewall_api.demo import SonicDemo, PANDemo, CheckPointDemo
        from .firewall_api.sonicos import SonicOS
        from .firewall_api.panos import PANOS
        from .firewall_api.checkpoint import CheckPoint
        from .firewall_api.service import APIService
        import serial.tools.list_ports
        import netmiko
        # Import the real connection stack without making network connections.
        from .provisioning.transport import SSHTransport
        results["checks"].append("Qt, serial and SSH runtime imports")
        app = QApplication.instance() or QApplication([])
        app.setStyle("Fusion"); app.setStyleSheet(STYLE)
        with tempfile.TemporaryDirectory(prefix="network-studio-smoke-") as directory:
            store = Store(directory)
            for ident in DRIVERS:
                transport = DemoTransport() if ident == "cisco_ios" else VendorDemoTransport(ident)
                service = Service(transport, store, driver_id=ident)
                assert service.connect().ports, ident
                transport.close()
                results["checks"].append("Switch discovery: " + ident)
            for ident in ROUTERS:
                service = ProvisioningService(ident, Demo(ident), store)
                assert service.connect().hostname, ident
                service.transport.close()
                results["checks"].append("Router discovery: " + ident)
            rule = dict(name="Release smoke", source="Lab clients", destination="Lab server", service="HTTPS", from_zone="LAN", to_zone="WAN", action="allow")
            adapters = [(SonicOS(SonicDemo(), "demo", "demo"), rule),
                        (PANOS(PANDemo(), "demo", "demo"), dict(rule, from_zone="trust", to_zone="untrust")),
                        (CheckPoint(CheckPointDemo(), "demo", "demo", "Network", "Lab", "Lab gateway"), {k: v for k, v in rule.items() if k not in ("from_zone", "to_zone")})]
            for adapter, item in adapters:
                service = APIService(adapter, store); service.connect()
                service.apply(service.preview([item])); service.close()
                results["checks"].append("API deploy and readback: " + adapter.id)
            window = Window(store); window.show(); app.processEvents()
            assert not window.windowIcon().isNull(), "Application icon is missing"
            assert not window.windowIcon().pixmap(32, 32).isNull(), "Application icon cannot render"
            results["checks"].append("Application icon loads and renders")
            for index in range(window.tabs.count()):
                window.tabs.setCurrentIndex(index); app.processEvents()
                assert not window.grab().isNull()
            window.close(); app.processEvents()
            results["checks"].append("All seven GUI pages render")
        results["passed"] = True
    except Exception:
        results["passed"] = False
        results["error"] = traceback.format_exc()
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 0 if results["passed"] else 1
