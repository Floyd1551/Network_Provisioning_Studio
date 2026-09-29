import copy
import tempfile
import unittest
from pathlib import Path
from switch_configurator.samples import SAMPLES
from switch_configurator.vendors import DRIVERS, get_driver, identify
from switch_configurator.vendor_demo import VendorDemoTransport
from switch_configurator.model import ChangeSet
from switch_configurator.service import Service
from switch_configurator.storage import Store
from switch_configurator.vendors.extreme import port_list


class VendorTests(unittest.TestCase):
    def test_independent_synthetic_discovery_fixtures(self):
        expected = {"arista_eos": "Ethernet1", "cisco_nxos": "Ethernet1/1", "aruba_cx": "1/1/1",
                    "juniper_junos": "ge-0/0/0", "extreme_exos": "1", "dell_os10": "ethernet1/1/1",
                    "tplink_jetstream": "gigabitEthernet 1/0/1"}
        for ident, name in expected.items():
            with self.subTest(platform=ident):
                device = get_driver(ident).parse(SAMPLES[ident])
                self.assertEqual(device.driver_id, ident)
                self.assertEqual(len(device.ports), 2)
                self.assertEqual(device.ports[name].config["access_vlan"], 10)
                self.assertEqual(device.ports[name].config["description"], "Desk 1")
                self.assertEqual(device.ports[name].status, "connected")
                self.assertTrue(all(p.manageable for p in device.ports.values()))
                self.assertEqual(device.vlans[20], "VOICE")

    def test_every_driver_end_to_end_demo_access_and_trunk(self):
        for ident in SAMPLES:
            with self.subTest(platform=ident), tempfile.TemporaryDirectory() as directory:
                transport = VendorDemoTransport(ident)
                service = Service(transport, Store(directory))
                device = service.connect()
                self.assertEqual(service.driver.id, ident)
                first, second = list(device.ports)
                changes = ChangeSet({first: {"description": "New desk", "mode": "access", "access_vlan": 40, "enabled": False}}, {40: "NEW"})
                after, path, _ = service.apply(service.preview(changes))
                self.assertEqual(after.ports[first].config["access_vlan"], 40)
                self.assertFalse(after.ports[first].config["enabled"])
                self.assertTrue((Path(path) / "after.cfg").exists())
                changes = ChangeSet({second: {"mode": "trunk", "native_vlan": 1, "allowed_vlans": "20,40"}})
                after, _, _ = service.apply(service.preview(changes))
                self.assertEqual(service.driver.verify(changes, after), [])
                self.assertNotIn("10", after.ports[second].config["allowed_vlans"].split(","))

    def test_command_grammars_are_platform_specific(self):
        expected = {
            "arista_eos": "switchport access vlan 20",
            "cisco_nxos": "interface Ethernet1/1",
            "aruba_cx": "vlan access 20",
            "dell_os10": "interface ethernet 1/1/1",
            "tplink_jetstream": "switchport general allowed vlan 20 untagged",
            "extreme_exos": 'configure vlan "VOICE" add ports 1 untagged',
            "juniper_junos": "set interfaces ge-0/0/0 unit 0 family ethernet-switching vlan members [ 20 ]",
        }
        for ident, command in expected.items():
            with self.subTest(platform=ident):
                driver = get_driver(ident)
                device = driver.parse(SAMPLES[ident])
                name = next(iter(device.ports))
                generated = driver.commands(ChangeSet({name: {"mode": "access", "access_vlan": 20}}), device)
                self.assertIn(command, generated)
                if ident == "juniper_junos": self.assertEqual(generated[-3:], ["commit check", "commit", "exit"])
                if ident == "extreme_exos": self.assertNotIn("configure terminal", generated)

    def test_wrong_platform_is_rejected_before_session_setup(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = VendorDemoTransport("arista_eos")
            service = Service(transport, Store(directory), driver_id="aruba_cx")
            with self.assertRaisesRegex(ValueError, "does not match"): service.connect()
            self.assertEqual(transport.sent, ["show version"])

    def test_unknown_vendor_is_never_cisco_fallback(self):
        self.assertIsNone(identify("Dell Networking OS9"))
        self.assertIsNone(identify("HPE Comware Software Version 7"))
        self.assertIsNone(identify("Extreme Fabric Engine VOSS"))
        self.assertIsNone(identify("ArubaOS-Switch WC.16.11"))
        self.assertIsNone(identify("unrecognized command"))
        self.assertEqual(identify(SAMPLES["cisco_nxos"]["show version"]).id, "cisco_nxos")

    def test_capabilities_and_injection_are_enforced_below_gui(self):
        for ident in SAMPLES:
            driver = get_driver(ident)
            device = driver.parse(SAMPLES[ident])
            name = next(iter(device.ports))
            with self.subTest(platform=ident):
                for patch in ({"voice_vlan": 20}, {"description": 'a"; delete'}, {"description": "a\nreload"}):
                    with self.assertRaises(ValueError): driver.commands(ChangeSet({name: patch}), device)
                with self.assertRaises(ValueError): driver.commands(ChangeSet({name + "; reload": {"enabled": False}}), device)

    def test_missing_status_and_wrong_fingerprint_fail_discovery(self):
        for ident in SAMPLES:
            with self.subTest(platform=ident):
                driver = get_driver(ident)
                sample = dict(SAMPLES[ident])
                sample[driver.status_command] = "unrecognized output"
                with self.assertRaises(ValueError): driver.parse(sample)
                sample = dict(SAMPLES[ident])
                sample[driver.version_command] = "Different operating system"
                with self.assertRaises(ValueError): driver.parse(sample)

    def test_junos_existing_candidate_is_not_committed_or_discarded(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = VendorDemoTransport("juniper_junos")
            service = Service(transport, Store(directory))
            device = service.connect()
            preview = service.preview(ChangeSet({next(iter(device.ports)): {"description": "test"}}))
            original = transport.command
            def pending(command):
                if command == "show | compare": return "+ another user's change"
                return original(command)
            transport.command = pending
            with self.assertRaisesRegex(RuntimeError, "Existing Junos candidate"): service.apply(preview)
            self.assertNotIn("commit", transport.sent)
            self.assertNotIn("rollback 0", transport.sent)
            self.assertFalse(any(cmd.startswith("set interfaces") for cmd in transport.sent))

    def test_junos_commit_check_must_positively_succeed(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = VendorDemoTransport("juniper_junos")
            service = Service(transport, Store(directory))
            device = service.connect()
            preview = service.preview(ChangeSet({next(iter(device.ports)): {"description": "test"}}))
            original = transport.command
            transport.command = lambda command: "" if command == "commit check" else original(command)
            with self.assertRaisesRegex(RuntimeError, "commit check did not confirm"): service.apply(preview)
            self.assertNotIn("commit", transport.sent)
            self.assertIn("rollback 0", transport.sent)
            self.assertEqual(service.discover().ports["ge-0/0/0"].config["description"], "Desk 1")

    def test_junos_inheritance_non_els_and_routed_are_read_only(self):
        driver = get_driver("juniper_junos")
        for suffix in ("set apply-groups ALL", "set interfaces interface-range USERS member ge-0/0/0"):
            sample = dict(SAMPLES[driver.id])
            sample[driver.running_command] += "\n" + suffix
            self.assertTrue(all(not p.manageable for p in driver.parse(sample).ports.values()))
        sample = dict(SAMPLES[driver.id])
        sample[driver.running_command] = sample[driver.running_command].replace("interface-mode access", "port-mode access")
        self.assertFalse(driver.parse(sample).ports["ge-0/0/0"].manageable)

    def test_exos_and_jetstream_remove_old_membership(self):
        for ident, removal in (("extreme_exos", 'configure vlan "STAFF" delete ports 1'),
                               ("tplink_jetstream", "no switchport general allowed vlan 10")):
            driver = get_driver(ident)
            device = driver.parse(SAMPLES[ident])
            changes = ChangeSet({next(iter(device.ports)): {"mode": "access", "access_vlan": 20}})
            self.assertIn(removal, driver.commands(changes, device))

    def test_unbounded_vlan_lists_blocked_where_not_supported(self):
        for ident in ("extreme_exos", "tplink_jetstream", "dell_os10"):
            driver = get_driver(ident)
            device = driver.parse(SAMPLES[ident])
            name = list(device.ports)[1]
            with self.subTest(platform=ident), self.assertRaises(ValueError):
                driver.commands(ChangeSet({name: {"allowed_vlans": "all"}}), device)

    def test_cross_slot_ranges_do_not_target_other_ports(self):
        known = {"1:1", "1:2", "1:3", "2:1"}
        self.assertEqual(port_list("1:1-1:3", known), {"1:1", "1:2", "1:3"})
        with self.assertRaises(ValueError): port_list("1:1-2:1", known)

    def test_keyed_vlan_names_cannot_collide_in_one_batch(self):
        for ident in ("juniper_junos", "extreme_exos"):
            driver = get_driver(ident)
            with self.subTest(platform=ident), self.assertRaisesRegex(ValueError, "unique"):
                driver.commands(ChangeSet({}, {40: "NEW", 50: "NEW"}), driver.parse(SAMPLES[ident]))

    def test_aruba_removes_obsolete_additive_trunk_members(self):
        driver = get_driver("aruba_cx")
        device = driver.parse(SAMPLES[driver.id])
        commands = driver.commands(ChangeSet({"1/1/2": {"allowed_vlans": "20"}}), device)
        self.assertIn("no vlan trunk allowed 10", commands)
        self.assertIn("vlan trunk allowed 20", commands)


if __name__ == "__main__": unittest.main()
