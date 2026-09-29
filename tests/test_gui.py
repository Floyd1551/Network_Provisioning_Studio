import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path

try:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog, QCheckBox, QPushButton, QMessageBox
    from switch_configurator.app import Window, STYLE, PortEditor
    from switch_configurator.storage import Store
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False


@unittest.skipUnless(QT_AVAILABLE, "PySide6 not installed")
class GuiTests(unittest.TestCase):
    def test_api_platform_scopes_and_routeros_vpn_form(self):
        from switch_configurator.provisioning.services_ui import ServiceDialog
        from switch_configurator.provisioning.drivers import DRIVERS
        from switch_configurator.provisioning.demo import Demo
        from switch_configurator.provisioning.service import ProvisioningService
        from switch_configurator.inventory import DeviceProfile
        from switch_configurator.inventory_ui import ProfileEditor
        with tempfile.TemporaryDirectory() as directory:
            window = Window(Store(directory)); window.show(); pane = window.firewall_api
            window.tabs.setCurrentWidget(pane)
            for ident in ("panos_api", "checkpoint_api"):
                pane.platform.setCurrentIndex(pane.platform.findData(ident)); pane.connect_button.click()
                deadline = time.monotonic() + 5
                while pane.busy and time.monotonic() < deadline: self.app.processEvents(); QTest.qWait(10)
                self.assertFalse(pane.busy); self.assertEqual(pane.snapshot.platform, ident)
                self.assertTrue(pane.add_button.isEnabled())
            pane.mode.setCurrentText("HTTPS API"); self.app.processEvents()
            self.assertTrue(pane.package.isVisible()); self.assertFalse(pane.vsys.isVisible())
            self.assertFalse(pane.add_button.isEnabled(), "Changing connection mode requires reconnect")
            pane.grab().save(str(Path(__file__).resolve().parents[1] / "test-artifacts" / "checkpoint-api-scope.png"))
            profile = DeviceProfile("Management", "checkpoint", "192.0.2.50", port=443, transport="HTTPS API", api_context=dict(domain="Lab domain", layer="Network", package="Lab", target="Lab gateway"))
            editor = ProfileEditor(profile, window)
            self.assertEqual(editor.value().api_context, profile.api_context)
            window.load_saved_connection(profile, {})
            self.assertEqual(pane.package.text(), "Lab"); self.assertEqual(pane.target.text(), "Lab gateway")
            service = ProvisioningService("routeros", Demo("routeros"), Store(directory)); snapshot = service.connect()
            dialog = ServiceDialog(snapshot, window)
            self.assertEqual(dialog.choice.count(), 1); self.assertEqual(dialog.choice.currentData(), "wireguard")
            self.assertIn("public_key", dialog.fields)
            dialog.show(); self.app.processEvents()
            dialog.grab().save(str(Path(__file__).resolve().parents[1] / "test-artifacts" / "wireguard-service-form.png"))
            dialog.close(); editor.close(); window.close(); self.app.processEvents()

    def test_firewall_api_demo_form_review_commit_and_readback(self):
        from PySide6.QtWidgets import QComboBox, QLineEdit
        with tempfile.TemporaryDirectory() as directory:
            window = Window(Store(directory)); window.show(); pane = window.firewall_api
            window.tabs.setCurrentWidget(pane); pane.connect_button.click()
            deadline = time.monotonic() + 5
            while pane.busy and time.monotonic() < deadline: self.app.processEvents(); QTest.qWait(10)
            self.assertIsNotNone(pane.snapshot)
            sent = list(pane.service.transport.sent)
            def stage():
                dialog = self.app.activeModalWidget()
                if not dialog or dialog.windowTitle() != "New IPv4 access rule": return
                dialog.findChild(QLineEdit, "rule_name").setText("Lab HTTPS")
                for key, value in (("from_zone", "LAN"), ("to_zone", "WAN"), ("source", "Lab clients"), ("destination", "Lab server"), ("action", "allow")):
                    dialog.findChild(QComboBox, "rule_" + key).setCurrentText(value)
                timer.stop()
                next(b for b in dialog.findChildren(QPushButton) if b.text() == "OK").click()
            timer = QTimer(); timer.timeout.connect(stage); timer.start(50); pane.add_button.click(); timer.stop()
            self.assertEqual(len(pane.rules), 1); self.assertEqual(sent, pane.service.transport.sent)
            pane.grab().save(str(Path(__file__).resolve().parents[1] / "test-artifacts" / "firewall-api-draft.png"))
            def approve():
                dialog = self.app.activeModalWidget()
                if not dialog or dialog.windowTitle() != "Review native API deployment": return
                dialog.findChild(QCheckBox).setChecked(True)
                dialog.grab().save(str(Path(__file__).resolve().parents[1] / "test-artifacts" / "firewall-api-review.png"))
                review_timer.stop()
                next(b for b in dialog.findChildren(QPushButton) if b.text() == "Apply").click()
            review_timer = QTimer(); review_timer.timeout.connect(approve); review_timer.start(50)
            pane.review_button.click(); deadline = time.monotonic() + 6
            while (pane.rules or pane.busy) and time.monotonic() < deadline: self.app.processEvents(); QTest.qWait(10)
            review_timer.stop()
            self.assertFalse(pane.busy); self.assertEqual(pane.rules, [])
            self.assertIn("readback verified", pane.status.text())
            window.close(); self.app.processEvents()

    def test_network_service_form_stages_then_review_plan_applies(self):
        from switch_configurator.provisioning.services_ui import ServiceDialog
        with tempfile.TemporaryDirectory() as directory:
            window = Window(Store(directory)); window.show(); pane = window.provisioning
            window.tabs.setCurrentWidget(pane)
            pane.platform.setCurrentIndex(pane.platform.findData("ios_router"))
            pane.connect_button.click()
            deadline = time.monotonic() + 5
            while pane.busy and time.monotonic() < deadline: self.app.processEvents(); QTest.qWait(10)
            self.assertFalse(pane.busy)
            before = list(pane.service.transport.sent)
            staged = []
            def fill():
                dialog = self.app.activeModalWidget()
                if not isinstance(dialog, ServiceDialog): return
                dialog.choice.setCurrentIndex(dialog.choice.findData("dns"))
                dialog.fields["id"].setText("resolver")
                dialog.fields["server"].setText("192.0.2.53")
                dialog.grab().save(str(Path(__file__).resolve().parents[1] / "test-artifacts" / "network-service-form.png"))
                staged.append(True); timer.stop(); dialog.stage()
            timer = QTimer(); timer.timeout.connect(fill); timer.start(50)
            pane.add_buttons["services"].click(); timer.stop()
            self.assertTrue(staged)
            self.assertEqual(before, pane.service.transport.sent)
            self.assertEqual(pane.intent.services[0]["server"], "192.0.2.53")
            self.assertIn("DNS", pane.draft.topLevelItem(0).text(2))
            plan = pane.service.preview(pane.intent); after, _ = pane.service.apply(plan)
            self.assertIn("ip name-server 192.0.2.53", after.running)
            window.close(); self.app.processEvents()

    def test_saved_devices_load_profiles_and_hide_switch_header(self):
        from switch_configurator.inventory import DeviceProfile
        from switch_configurator.inventory_ui import ProfileEditor
        with tempfile.TemporaryDirectory() as directory:
            window = Window(Store(directory)); window.show()
            profile = DeviceProfile("Home switch", "cisco_ios", "192.0.2.10", username="operator", model="3750X-48", site="Home")
            window.saved_devices.inventory.save(profile)
            window.saved_devices.refresh()
            window.tabs.setCurrentWidget(window.saved_devices)
            self.app.processEvents()
            self.assertFalse(window.switch_header.isVisible())
            self.assertEqual(window.saved_devices.tree.topLevelItemCount(), 1)
            window.saved_devices.search.setText("missing")
            self.assertEqual(window.saved_devices.tree.topLevelItemCount(), 0)
            window.saved_devices.search.clear()
            artifacts = Path(__file__).resolve().parents[1] / "test-artifacts"
            window.grab().save(str(artifacts / "saved-devices.png"))
            window.load_saved_connection(profile, {})
            self.assertEqual(window.source.currentData().host, profile.host)
            self.assertEqual(window.platform.currentData(), "cisco_ios")
            with patch.object(QMessageBox, "warning") as warning:
                window.platform.setCurrentIndex(window.platform.findData("arista_eos"))
                window.connect_device()
                warning.assert_called_once()
            self.assertIsNone(window.service)
            router = DeviceProfile("Router", "ios_router", "192.0.2.20", username="operator")
            window.load_saved_connection(router, {"password": "temporary"})
            self.assertIs(window.tabs.currentWidget(), window.provisioning)
            self.assertEqual(window.provisioning.host.text(), router.host)
            self.assertEqual(window.provisioning.password.text(), "temporary")
            editor = ProfileEditor(profile, window); editor.show(); self.app.processEvents()
            self.assertEqual(editor.value().id, profile.id)
            self.assertFalse(editor.password.isEnabled())
            editor.grab().save(str(artifacts / "saved-device-editor.png"))
            editor.close(); window.close(); self.app.processEvents()

    def test_router_wizard_stages_then_existing_review_applies(self):
        from PySide6.QtWidgets import QWizard
        from switch_configurator.provisioning.wizard import ProvisioningWizard
        app = self.app
        def wait_idle(pane):
            deadline = time.monotonic() + 5
            while pane.busy and time.monotonic() < deadline: app.processEvents(); QTest.qWait(10)
            self.assertFalse(pane.busy)
        with tempfile.TemporaryDirectory() as directory:
            window = Window(Store(directory)); window.show(); pane = window.provisioning
            window.tabs.setCurrentWidget(pane)
            pane.platform.setCurrentIndex(pane.platform.findData("fortios")); pane.connect_button.click(); wait_idle(pane)
            sent = list(pane.service.transport.sent)
            timer = QTimer(); stages = []
            artifacts = Path(__file__).resolve().parents[1] / "test-artifacts"
            def advance():
                dialog = app.activeModalWidget()
                if not isinstance(dialog, ProvisioningWizard): return
                if dialog.currentId() == 0:
                    dialog.scenario_page.choice.setCurrentIndex(dialog.scenario_page.choice.findData("branch"))
                    dialog.button(QWizard.WizardButton.NextButton).click()
                elif dialog.currentId() == 1:
                    fields = dialog.details_page.fields
                    fields["lan_address"].setText("10.20.0.1/24")
                    fields["gateway"].setText("192.0.2.1")
                    fields["access"].setCurrentIndex(fields["access"].findData("https"))
                    fields["source_nat"].setChecked(True)
                    dialog.grab().save(str(artifacts / "wizard-branch-settings.png"))
                    dialog.button(QWizard.WizardButton.NextButton).click()
                elif dialog.currentId() == 2:
                    self.assertIn("source NAT enabled", dialog.summary_page.summary.toPlainText())
                    self.assertIn('set nat "enable"', dialog.summary_page.cli.toPlainText())
                    dialog.grab().save(str(artifacts / "wizard-branch-summary.png"))
                    timer.stop(); stages.append(True); dialog.button(QWizard.WizardButton.FinishButton).click()
            timer.timeout.connect(advance); timer.start(80)
            pane.wizard_button.click(); timer.stop()
            self.assertTrue(stages)
            self.assertEqual(pane.service.transport.sent, sent, "Wizard must not transmit CLI")
            self.assertEqual(pane.intent.routes[0]["destination"], "0.0.0.0/0")
            self.assertEqual(pane.intent.policies[0]["nat"], "enable")
            plan = pane.service.preview(pane.intent)
            after, path = pane.service.apply(plan)
            self.assertEqual(after.interfaces["port2"]["address"], "10.20.0.1/24")
            self.assertTrue((path / "before.cfg").exists())
            window.close(); app.processEvents()

    def test_wizard_back_validation_and_cancel_preserve_draft(self):
        from PySide6.QtWidgets import QWizard
        from switch_configurator.provisioning.wizard import ProvisioningWizard
        from switch_configurator.provisioning.demo import Demo
        from switch_configurator.provisioning.drivers import DRIVERS
        from switch_configurator.provisioning.model import Intent
        demo = Demo("aruba_routing")
        snapshot = DRIVERS["aruba_routing"]().parse(demo.running, demo.identity)
        existing = Intent()
        wizard = ProvisioningWizard("router", snapshot, existing); wizard.show(); self.app.processEvents()
        choices = wizard.scenario_page.choice
        self.assertFalse(choices.model().item(choices.findData("service")).isEnabled())
        wizard.next(); self.app.processEvents()
        fields = wizard.details_page.fields
        self.assertFalse(fields["source_nat"].isEnabled())
        fields["lan_address"].setText("not-an-address"); fields["gateway"].setText("192.0.2.1")
        wizard.next(); self.assertEqual(wizard.currentId(), 1); self.assertTrue(wizard.details_page.error.text())
        fields["lan_address"].setText("10.20.0.1/24"); wizard.next()
        self.assertEqual(wizard.currentId(), 2)
        wizard.back(); self.assertEqual(wizard.details_page.fields["lan_address"].text(), "10.20.0.1/24")
        wizard.next(); wizard.reject()
        self.assertEqual(existing, Intent())
        self.assertEqual(demo.sent, [])
        self.app.processEvents()

    def test_switch_guest_wizard_uses_selection_and_stages_only(self):
        from PySide6.QtWidgets import QWizard
        from switch_configurator.provisioning.wizard import ProvisioningWizard
        app = self.app
        with tempfile.TemporaryDirectory() as directory:
            window = Window(Store(directory)); window.show(); window.connect_button.click()
            deadline = time.monotonic() + 5
            while window.busy and time.monotonic() < deadline: app.processEvents(); QTest.qWait(10)
            self.assertFalse(window.busy)
            window.ports.item(0).setSelected(True)
            name = window.ports.item(0).data(Qt.ItemDataRole.UserRole)
            before = window.device.running
            timer = QTimer(); staged = []
            def advance():
                dialog = app.activeModalWidget()
                if not isinstance(dialog, ProvisioningWizard): return
                if dialog.currentId() == 0:
                    combo = dialog.scenario_page.choice; combo.setCurrentIndex(combo.findData("guest")); dialog.next()
                elif dialog.currentId() == 1:
                    fields = dialog.details_page.fields
                    self.assertEqual(dialog.details_page.values()["ports"], [name])
                    fields["vlan"].setText("40"); fields["vlan_name"].setText("GUEST"); dialog.next()
                elif dialog.currentId() == 2:
                    self.assertIn("isolation", dialog.summary_page.summary.toPlainText())
                    dialog.grab().save(str(Path(__file__).resolve().parents[1] / "test-artifacts" / "wizard-guest-summary.png"))
                    timer.stop(); staged.append(True); dialog.button(QWizard.WizardButton.FinishButton).click()
            timer.timeout.connect(advance); timer.start(80)
            window.wizard_button.click(); timer.stop()
            self.assertTrue(staged)
            self.assertEqual(window.changes.vlans, {40: "GUEST"})
            self.assertEqual(window.changes.ports[name], {"mode": "access", "access_vlan": 40})
            self.assertEqual(window.service.discover().running, before)
            window.close(); app.processEvents()

    def test_router_firewall_workspace_forms_review_and_apply(self):
        from switch_configurator.provisioning.ui import EntryDialog
        from switch_configurator.provisioning.drivers import DRIVERS
        app = self.app
        errors = []
        watchdog = QTimer()
        def dismiss_errors():
            dialog = app.activeModalWidget()
            if isinstance(dialog, QMessageBox): errors.append(dialog.text()); dialog.accept()
        watchdog.timeout.connect(dismiss_errors); watchdog.start(100)
        def wait_idle(pane):
            deadline = time.monotonic() + 5
            while pane.busy and time.monotonic() < deadline: app.processEvents(); QTest.qWait(10)
            self.assertFalse(pane.busy)
        with tempfile.TemporaryDirectory() as directory:
            window = Window(Store(directory)); window.show()
            pane = window.provisioning
            window.tabs.setCurrentWidget(pane); app.processEvents()
            self.assertFalse(window.switch_header.isVisible())
            for ident, cls in DRIVERS.items():
                pane.platform.setCurrentIndex(pane.platform.findData(ident))
                QTest.mouseClick(pane.connect_button, Qt.MouseButton.LeftButton); wait_idle(pane)
                self.assertIsNotNone(pane.snapshot, ident)
                for kind, b in pane.add_buttons.items(): self.assertEqual(b.isEnabled(), kind in cls.capabilities)
            pane.platform.setCurrentIndex(pane.platform.findData("fortios"))
            pane.connect_button.click(); wait_idle(pane)
            def stage(kind, values):
                def fill():
                    dialog = app.activeModalWidget()
                    if isinstance(dialog, EntryDialog):
                        for k, value in values.items():
                            field = dialog.fields[k]
                            if hasattr(field, "setCurrentText"): field.setCurrentText(value)
                            else: field.setText(value)
                        dialog.accept()
                QTimer.singleShot(50, fill)
                pane.add_buttons[kind].click()
            stage("interfaces", {"name": "port2", "address": "10.20.0.1/24"})
            stage("routes", {"id": "100", "destination": "203.0.113.0/24", "gateway": "192.0.2.1", "interface": "port1"})
            stage("policies", {"id": "200", "source": "10.20.0.0/24", "destination": "203.0.113.0/24", "in_interface": "port2", "out_interface": "port1", "protocol": "tcp", "port": "443", "action": "allow", "nat": "enable"})
            self.assertEqual(len(pane.intent.policies), 1)
            artifacts = Path(__file__).resolve().parents[1] / "test-artifacts"
            artifacts.mkdir(exist_ok=True)
            window.grab().save(str(artifacts / "provisioning.png"))
            reviewed = []
            timer = QTimer()
            def approve():
                dialog = app.activeModalWidget()
                if isinstance(dialog, QDialog) and dialog.windowTitle() == "Review router / firewall provisioning":
                    apply = next(b for b in dialog.findChildren(QPushButton) if "Apply" in b.text())
                    self.assertFalse(apply.isEnabled())
                    dialog.findChild(QCheckBox).setChecked(True)
                    dialog.grab().save(str(artifacts / "provisioning-review.png"))
                    reviewed.append(True); timer.stop(); apply.click()
            timer.timeout.connect(approve); timer.start(50)
            pane.review_button.click()
            deadline = time.monotonic() + 8
            while (not reviewed or pane.busy or pane.intent.interfaces) and time.monotonic() < deadline:
                app.processEvents(); QTest.qWait(10)
            timer.stop(); wait_idle(pane)
            self.assertTrue(reviewed)
            self.assertFalse(pane.intent.interfaces)
            self.assertEqual(pane.snapshot.interfaces["port2"]["address"], "10.20.0.1/24")
            self.assertEqual(pane.snapshot.facts["firewall policy"]["200"]["nat"], ["enable"])
            self.assertEqual(errors, [])
            window.close(); app.processEvents()
        watchdog.stop()

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        # The offscreen Windows plugin does not discover system fonts automatically.
        font_dir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for filename in ("segoeui.ttf", "segoeuib.ttf", "consola.ttf"):
            path = font_dir / filename
            if path.exists(): QFontDatabase.addApplicationFont(str(path))

    def test_demo_selection_editor_preview_apply(self):
        app = QApplication.instance() or QApplication([])
        app.setStyle("Fusion")
        app.setStyleSheet(STYLE)
        unexpected_errors = []
        watchdog = QTimer()
        def dismiss_errors():
            dialog = app.activeModalWidget()
            if isinstance(dialog, QMessageBox):
                unexpected_errors.append(dialog.text())
                dialog.accept()
        watchdog.timeout.connect(dismiss_errors)
        watchdog.start(100)
        with tempfile.TemporaryDirectory() as directory:
            window = Window(Store(directory))
            window.show()
            app.processEvents()
            QTest.mouseClick(window.connect_button, Qt.MouseButton.LeftButton)
            deadline = time.monotonic() + 10
            while window.busy and time.monotonic() < deadline: QTest.qWait(20)
            self.assertFalse(window.busy)
            self.assertIsNotNone(window.device)
            self.assertEqual(window.ports.count(), 28)
            rect1 = window.ports.visualItemRect(window.ports.item(0))
            rect2 = window.ports.visualItemRect(window.ports.item(1))
            QTest.mouseClick(window.ports.viewport(), Qt.MouseButton.LeftButton, pos=rect1.center())
            QTest.mouseClick(window.ports.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, rect2.center())
            self.assertEqual(len(window.ports.selectedItems()), 2)
            names = [item.data(Qt.ItemDataRole.UserRole) for item in window.ports.selectedItems()]

            def edit():
                dialog = app.activeModalWidget()
                if isinstance(dialog, PortEditor):
                    dialog.fields["description"][0].setChecked(True)
                    dialog.fields["description"][1].setText("Validated demo port")
                    dialog.validate_accept()
            QTimer.singleShot(100, edit)
            QTest.mouseClick(window.configure_button, Qt.MouseButton.LeftButton)
            self.assertEqual(len(window.changes.ports), 2)
            self.assertTrue(window.preview_button.isEnabled())
            artifact_dir = Path(__file__).resolve().parents[1] / "test-artifacts"
            artifact_dir.mkdir(exist_ok=True)
            app.processEvents()
            self.assertTrue(window.grab().save(str(artifact_dir / "workspace.png")))

            review_seen = []
            timer = QTimer()
            def review():
                dialog = app.activeModalWidget()
                if isinstance(dialog, QDialog) and dialog.windowTitle() == "Review deployment":
                    review_seen.append(True)
                    dialog.grab().save(str(artifact_dir / "review.png"))
                    dialog.findChild(QCheckBox).setChecked(True)
                    for button in dialog.findChildren(QPushButton):
                        if button.text() == "Apply and verify":
                            timer.stop()
                            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
                            return
            timer.timeout.connect(review)
            timer.start(50)
            QTest.mouseClick(window.preview_button, Qt.MouseButton.LeftButton)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                QTest.qWait(20)
                if review_seen and not window.busy and not window.changes.ports: break
            timer.stop()
            self.assertTrue(review_seen)
            self.assertFalse(window.busy)
            self.assertFalse(window.changes.ports)
            for name in names: self.assertEqual(window.device.ports[name].config["description"], "Validated demo port")
            self.assertIn("verified", window.store.history()[0][2])
            self.assertEqual(unexpected_errors, [])
            window.close()
            app.processEvents()
        watchdog.stop()

    def test_raw_terminal_sends_input_and_releases_port(self):
        from switch_configurator.terminal import TerminalDialog
        class Console:
            def __init__(self):
                self.closed = False
                self.writes = []
                self.in_waiting = 0
            def __enter__(self): return self
            def __exit__(self, *args): self.closed = True
            def write(self, value): self.writes.append(value)
            def read(self, count):
                time.sleep(0.01)
                return b""
        console = Console()
        with patch("serial.Serial", return_value=console):
            dialog = TerminalDialog("FAKE", 9600)
            dialog.show()
            dialog.input.setText("enable")
            dialog.send()
            deadline = time.monotonic() + 3
            while b"enable\r" not in console.writes and time.monotonic() < deadline: QTest.qWait(20)
            dialog.close()
            self.assertFalse(dialog.worker.isRunning())
            self.assertTrue(console.closed)
            self.assertIn(b"enable\r", console.writes)

    def test_added_platforms_connect_and_disable_unsupported_fields(self):
        from switch_configurator.samples import SAMPLES
        from switch_configurator.model import ChangeSet
        app = self.app
        app.setStyleSheet(STYLE)
        errors = []
        timer = QTimer()
        def dismiss_errors():
            dialog = app.activeModalWidget()
            if isinstance(dialog, QMessageBox):
                errors.append(dialog.text())
                dialog.accept()
        timer.timeout.connect(dismiss_errors)
        timer.start(50)
        with tempfile.TemporaryDirectory() as directory:
            window = Window(Store(directory))
            window.show()
            for ident in SAMPLES:
                with self.subTest(platform=ident):
                    window.platform.setCurrentIndex(window.platform.findData(ident))
                    QTest.mouseClick(window.connect_button, Qt.MouseButton.LeftButton)
                    deadline = time.monotonic() + 5
                    while window.busy and time.monotonic() < deadline: QTest.qWait(20)
                    self.assertFalse(window.busy)
                    self.assertIsNotNone(window.device, errors)
                    self.assertEqual(window.device.driver_id, ident)
                    window.ports.item(0).setSelected(True)
                    editor = PortEditor([next(iter(window.device.ports))], window.device, window.store, window)
                    self.assertFalse(editor.fields["voice_vlan"][0].isEnabled())
                    editor.profile.setCurrentText("IP Phone + Workstation")
                    editor.load_profile()
                    self.assertNotIn("poe", editor.patch())
                    self.assertIn("unavailable", editor.error.text())
                    editor.close()
            artifact_dir = Path(__file__).resolve().parents[1] / "test-artifacts"
            artifact_dir.mkdir(exist_ok=True)
            app.processEvents()
            window.grab().save(str(artifact_dir / "multivendor.png"))
            self.assertFalse(errors, errors)
            window.close()
        timer.stop()


if __name__ == "__main__": unittest.main()
