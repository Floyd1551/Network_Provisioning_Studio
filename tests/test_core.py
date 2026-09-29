import tempfile
import unittest
from pathlib import Path
from switch_configurator.driver import ERROR, commands, parse_device, parse_port, verify
from switch_configurator.model import ChangeSet, vlan_set
from switch_configurator.service import Service
from switch_configurator.storage import Store
from switch_configurator.transport import DemoTransport


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.transport = DemoTransport()
        self.store = Store(self.temp.name)
        self.service = Service(self.transport, self.store)
        self.device = self.service.connect()
        self.name = next(iter(self.device.ports))

    def test_discover_and_verify_multiport(self):
        self.assertEqual(len(self.device.ports), 28)
        changes = ChangeSet({name: dict(mode="access", access_vlan=40, voice_vlan=20, description="Test desk",
                    enabled=False, poe="never", portfast="enabled", bpduguard="enabled", speed="100", duplex="full")
                    for name in list(self.device.ports)[:3]}, {40: "TEST"})
        preview = self.service.preview(changes)
        after, path, warnings = self.service.apply(preview)
        self.assertEqual(verify(changes, after), [])
        self.assertTrue((Path(path) / "before.cfg").exists())
        self.assertTrue((Path(path) / "after.cfg").exists())
        self.assertIn("verified", self.store.history()[0][2])
        self.assertEqual(after.ports[self.name].config["description"], "Test desk")

    def test_stale_preview_does_not_write(self):
        preview = self.service.preview(ChangeSet({self.name: {"description": "New"}}))
        self.transport.ports[self.name].config["description"] = "Concurrent change"
        with self.assertRaisesRegex(RuntimeError, "changed since preview"): self.service.apply(preview)
        self.assertFalse(self.store.history())

    def test_injection_and_invalid_values(self):
        for patch in ({"description": "ok\nshutdown"}, {"description": "hello?"}, {"mode": "trunk\nend"},
                      {"allowed_vlans": "1-4095"}, {"access_vlan": 1002}, {"voice_vlan": 5000}, {"access_vlan": 777}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                commands(ChangeSet({self.name: patch}), self.device)

    def test_changes_only_touch_explicit_fields(self):
        generated = commands(ChangeSet({self.name: {"description": "Only this"}}), self.device)
        self.assertEqual(generated, ["configure terminal", "interface " + self.name, "description Only this", "exit", "end"])

    def test_error_stops_and_preserves_partial_state(self):
        original = self.transport.command
        sent = []
        def failing(command):
            sent.append(command)
            if command == "power inline never": return "% Invalid input detected at '^' marker."
            return original(command)
        self.transport.command = failing
        preview = self.service.preview(ChangeSet({self.name: {"description": "Applied first", "poe": "never", "enabled": True}}))
        with self.assertRaisesRegex(RuntimeError, "changes may be partial"): self.service.apply(preview)
        self.assertNotIn("no shutdown", sent)
        self.assertEqual(self.transport.ports[self.name].config["description"], "Applied first")
        history = self.store.history()[0]
        self.assertIn("failed", history[2])
        self.assertTrue((Path(history[3]) / "after.cfg").exists())

    def test_silent_nonapplication_is_not_success(self):
        original = self.transport.command
        self.transport.command = lambda command: "" if command == "description Ignored" else original(command)
        preview = self.service.preview(ChangeSet({self.name: {"description": "Ignored"}}))
        with self.assertRaisesRegex(RuntimeError, "Verification failed"): self.service.apply(preview)

    def test_backup_failure_prevents_transmission(self):
        preview = self.service.preview(ChangeSet({self.name: {"description": "Not applied"}}))
        def fail(*args): raise OSError("Disk full")
        self.store.begin = fail
        with self.assertRaises(OSError): self.service.apply(preview)
        self.assertNotEqual(self.transport.ports[self.name].config["description"], "Not applied")

    def test_missing_end_and_non_ios_blocked(self):
        evidence = dict(self.device.evidence)
        evidence["show running-config"] = evidence["show running-config"].removesuffix("end")
        with self.assertRaises(ValueError): parse_device(evidence)
        evidence = dict(self.device.evidence)
        evidence["show version"] = "Cisco NX-OS"
        with self.assertRaises(ValueError): parse_device(evidence)

    def test_channel_group_and_routed_blocked(self):
        for line in ("channel-group 1 mode active", "no switchport", "source template AP"):
            self.device.ports[self.name] = parse_port(self.name, [line])
            with self.assertRaises(ValueError): commands(ChangeSet({self.name: {"enabled": False}}), self.device)

    def test_allowed_vlan_modifiers_and_semantic_comparison(self):
        port = parse_port(self.name, ["switchport trunk allowed vlan 10-12", "switchport trunk allowed vlan add 20", "switchport trunk allowed vlan remove 11"])
        self.assertEqual(vlan_set(port.config["allowed_vlans"]), {10, 12, 20})
        self.device.ports[self.name] = port
        self.assertEqual(verify(ChangeSet({self.name: {"allowed_vlans": "10,12,20"}}), self.device), [])

    def test_custom_profile_roundtrip(self):
        self.store.save_profile("Lab desk", {"mode": "access", "enabled": True})
        self.assertEqual(self.store.profiles()["Lab desk"]["mode"], "access")

    def test_unusual_cli_diagnostics_are_not_silently_accepted(self):
        self.assertTrue(ERROR.search("% Cannot create VLAN on this device"))
        self.assertTrue(ERROR.search("% VLAN creation is prohibited in client mode"))
        self.assertFalse(ERROR.search("%LINK-3-UPDOWN: Interface GigabitEthernet1/0/1, changed state to up"))
        self.assertFalse(ERROR.search("%Warning: portfast should only be enabled on ports connected to a single host."))
        self.assertFalse(ERROR.search("%Portfast has been configured on GigabitEthernet1/0/1"))
        self.assertFalse(ERROR.search(" description Legacy endpoint not supported"))

    def test_portfast_trunk_requires_explicit_disable(self):
        self.device.ports[self.name].config["portfast"] = "enabled"
        with self.assertRaises(ValueError): commands(ChangeSet({self.name: {"mode": "trunk"}}), self.device)

    def test_clear_description_voice_and_default_flags(self):
        changes = ChangeSet({self.name: dict(description="", voice_vlan=0, portfast="default", bpduguard="default")})
        result, _, _ = self.service.apply(self.service.preview(changes))
        self.assertEqual(verify(changes, result), [])


if __name__ == "__main__": unittest.main()
