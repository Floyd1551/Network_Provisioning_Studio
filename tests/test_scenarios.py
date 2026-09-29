import copy
import tempfile
import unittest
from switch_configurator.model import ChangeSet
from switch_configurator.storage import Store
from switch_configurator.service import Service
from switch_configurator.transport import DemoTransport
from switch_configurator.vendor_demo import VendorDemoTransport
from switch_configurator.vendors import DRIVERS as SWITCH_DRIVERS
from switch_configurator.provisioning.model import Intent
from switch_configurator.provisioning.drivers import DRIVERS
from switch_configurator.provisioning.demo import Demo
from switch_configurator.provisioning.service import ProvisioningService
from switch_configurator.provisioning.scenarios import (ROUTER_SCENARIOS, SWITCH_SCENARIOS,
    compile_router, compile_switch, unavailable, merge_intents)


def router_values(snapshot):
    wan, lan = list(snapshot.interfaces)[:2]
    return dict(lan=lan, wan=wan, lan_address="10.20.0.1/24", source="10.20.0.0/24",
                destination="203.0.113.0/24", gateway="192.0.2.1", base_id="1000",
                access="routing_only", source_nat=False, add_default=False,
                protocol="tcp", port="443", action="allow")


class ScenarioTests(unittest.TestCase):
    def test_every_available_router_scenario_applies_in_demo(self):
        for platform in DRIVERS:
            for scenario in ROUTER_SCENARIOS:
                with self.subTest(platform=platform, scenario=scenario.id), tempfile.TemporaryDirectory() as directory:
                    service = ProvisioningService(platform, Demo(platform), Store(directory))
                    snapshot = service.connect()
                    if unavailable(scenario, snapshot):
                        with self.assertRaises(ValueError): compile_router(scenario.id, {}, snapshot)
                        continue
                    values = router_values(snapshot)
                    existing = Intent(interfaces=[dict(name=values["lan"], address=values["lan_address"])]) if scenario.id in ("outbound", "service") else Intent()
                    intent, commands, notes = compile_router(scenario.id, values, snapshot, existing)
                    self.assertTrue(commands); self.assertTrue(notes)
                    plan = service.preview(intent)
                    after, _ = service.apply(plan)
                    self.assertEqual(service.driver.verify(plan, after), [])

    def test_every_switch_scenario_applies_on_every_switch_driver(self):
        for platform in SWITCH_DRIVERS:
            for scenario in SWITCH_SCENARIOS:
                with self.subTest(platform=platform, scenario=scenario.id), tempfile.TemporaryDirectory() as directory:
                    demo = DemoTransport() if platform == "cisco_ios" else VendorDemoTransport(platform)
                    service = Service(demo, Store(directory), driver_id=platform)
                    device = service.connect()
                    name = list(device.ports)[1] if scenario.id == "uplink" else next(iter(device.ports))
                    values = dict(ports=[name], vlan="40", vlan_name="NEW", description="Wizard port", enable=False, native="1", allowed="20")
                    changes, commands, notes = compile_switch(scenario.id, values, device)
                    self.assertTrue(commands)
                    after, _, _ = service.apply(service.preview(changes))
                    self.assertEqual(service.driver.verify(changes, after), [])
                    if scenario.id == "guest": self.assertTrue(any("isolation" in n for n in notes))

    def test_branch_access_and_nat_map_to_correct_platform_features(self):
        for platform in ("fortios", "routeros", "junos_routing", "ios_router", "aruba_routing"):
            with tempfile.TemporaryDirectory() as directory:
                service = ProvisioningService(platform, Demo(platform), Store(directory))
                snapshot = service.connect(); values = router_values(snapshot)
                values.update(destination="0.0.0.0/0", access="https", source_nat=True)
                if platform not in ("fortios", "routeros"):
                    with self.assertRaises(ValueError): compile_router("branch", values, snapshot)
                    continue
                intent, _, _ = compile_router("branch", values, snapshot)
                self.assertEqual(intent.policies[0]["port"], "443")
                self.assertEqual(intent.policies[0]["source"], "10.20.0.0/24")
                self.assertEqual(intent.routes[0]["destination"], "0.0.0.0/0")
                if platform == "fortios": self.assertEqual(intent.policies[0]["nat"], "enable")
                else: self.assertEqual(intent.nat[0]["out_interface"], values["wan"])
                service.apply(service.preview(intent))

    def test_wizard_conflicts_are_atomic_and_identical_entries_coalesce(self):
        existing = Intent(interfaces=[dict(name="port2", address="10.20.0.1/24")])
        original = copy.deepcopy(existing)
        incoming = Intent(interfaces=[dict(name="port2", address="10.30.0.1/24")])
        with self.assertRaisesRegex(ValueError, "Draft conflict"): merge_intents(existing, incoming)
        self.assertEqual(existing, original)
        self.assertEqual(len(merge_intents(existing, original).interfaces), 1)
        with tempfile.TemporaryDirectory() as directory:
            service = Service(DemoTransport(), Store(directory)); device = service.connect(); name = next(iter(device.ports))
            staged = ChangeSet({name: {"enabled": True}}, {})
            with self.assertRaisesRegex(ValueError, "Draft conflict"): compile_switch("unused", {"ports": [name]}, device, staged)
            self.assertEqual(staged.ports[name], {"enabled": True})

    def test_uplink_requires_explicit_existing_vlans(self):
        with tempfile.TemporaryDirectory() as directory:
            service = Service(DemoTransport(), Store(directory)); device = service.connect(); name = next(iter(device.ports))
            for allowed in ("all", "none", "777"):
                with self.assertRaises(ValueError): compile_switch("uplink", dict(ports=[name], native="1", allowed=allowed), device)
            changes, _, _ = compile_switch("uplink", dict(ports=[name], native="1", allowed="777"), device, ChangeSet({}, {777: "STAGED"}))
            self.assertEqual(changes.vlans[777], "STAGED")
            self.assertEqual(changes.ports[name]["portfast"], "disabled")

    def test_access_preserves_unrequested_fields_and_does_not_rename_vlan(self):
        with tempfile.TemporaryDirectory() as directory:
            service = Service(DemoTransport(), Store(directory)); device = service.connect(); name = next(iter(device.ports))
            values = dict(ports=[name], vlan="10", vlan_name="", description="", enable=False)
            changes, _, _ = compile_switch("cameras", values, device)
            self.assertEqual(changes.ports[name], {"mode": "access", "access_vlan": 10})
            self.assertEqual(changes.vlans, {})
            values["vlan_name"] = "RENAME"
            with self.assertRaisesRegex(ValueError, "already uses name"): compile_switch("guest", values, device)

    def test_invalid_network_inputs_and_unaddressed_policy_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ProvisioningService("fortios", Demo("fortios"), Store(directory)); snapshot = service.connect()
            values = router_values(snapshot)
            with self.assertRaisesRegex(ValueError, "IPv4 address"): compile_router("service", values, snapshot)
            values["wan"] = values["lan"]
            with self.assertRaisesRegex(ValueError, "different"): compile_router("branch", values, snapshot)
            values = router_values(snapshot); values["lan_address"] = "192.0.2.22/24"
            with self.assertRaisesRegex(ValueError, "Overlapping"): compile_router("branch", values, snapshot)
            values = router_values(snapshot); values["base_id"] = "1;reload"
            with self.assertRaises(ValueError): compile_router("branch", values, snapshot)

    def test_outbound_optional_route_is_not_added_silently(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ProvisioningService("fortios", Demo("fortios"), Store(directory)); snapshot = service.connect()
            values = router_values(snapshot); existing = Intent(interfaces=[dict(name=values["lan"], address=values["lan_address"])])
            intent, _, _ = compile_router("outbound", values, snapshot, existing)
            self.assertFalse(intent.routes); self.assertFalse(intent.nat)
            self.assertNotIn("nat", intent.policies[0])
            values["add_default"] = True
            intent, _, _ = compile_router("outbound", values, snapshot, existing)
            self.assertEqual(intent.routes[0]["destination"], "0.0.0.0/0")


if __name__ == "__main__": unittest.main()
