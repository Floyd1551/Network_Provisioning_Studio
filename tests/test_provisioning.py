import copy
import json
import tempfile
import unittest
from unittest.mock import patch
from switch_configurator.provisioning.drivers import DRIVERS, IOSRouter, FortiOS, RouterOS
from switch_configurator.provisioning.demo import Demo, SAMPLES
from switch_configurator.provisioning.model import Intent
from switch_configurator.provisioning.service import ProvisioningService
from switch_configurator.provisioning.transport import SSHTransport
from switch_configurator.storage import Store


def intent_for(snapshot, policy=True):
    wan, lan = list(snapshot.interfaces)[:2]
    return Intent(interfaces=[dict(name=lan, address="10.20.0.1/24")],
                  routes=[dict(id="100", destination="203.0.113.0/24", gateway="192.0.2.1", interface=wan)],
                  policies=[dict(id="200", source="10.20.0.0/24", destination="203.0.113.0/24", in_interface=lan, out_interface=wan, protocol="tcp", port="443", action="allow")] if policy else [])


class ProvisioningTests(unittest.TestCase):
    def test_native_driver_roundtrips_and_backups(self):
        for ident in ("ios_router", "fortios", "routeros", "junos_routing", "aruba_routing"):
            with self.subTest(platform=ident), tempfile.TemporaryDirectory() as directory:
                transport = Demo(ident)
                service = ProvisioningService(ident, transport, Store(directory))
                before = service.connect()
                intent = intent_for(before, ident != "aruba_routing")
                if ident == "routeros": intent.nat = [dict(id="300", source="10.20.0.0/24", out_interface="ether1")]
                plan = service.preview(intent)
                after, path = service.apply(plan)
                self.assertEqual(after.interfaces[list(before.interfaces)[1]]["address"], "10.20.0.1/24")
                self.assertEqual(service.driver.verify(plan, after), [])
                self.assertEqual((path / "before.cfg").read_text(), before.running)
                self.assertEqual(json.loads((path / "intent.json").read_text())["intent"], intent.to_dict())
                self.assertTrue((path / "after.cfg").exists())

    def test_all_eight_platforms_discover_and_readonly_cannot_apply(self):
        for ident in DRIVERS:
            with self.subTest(platform=ident), tempfile.TemporaryDirectory() as directory:
                service = ProvisioningService(ident, Demo(ident), Store(directory))
                snapshot = service.connect()
                self.assertEqual(snapshot.platform, ident)
                if getattr(service.driver, "read_only", False):
                    with self.assertRaisesRegex(ValueError, "Discovery only"): service.preview(Intent())

    def test_native_commands_match_independent_expectations(self):
        expected = {
            "ios_router": "ip route 203.0.113.0 255.255.255.0 GigabitEthernet0/0 192.0.2.1",
            "fortios": 'set srcintf "port2"',
            "routeros": "/ip route add dst-address=203.0.113.0/24 gateway=192.0.2.1%ether1 distance=1 routing-table=main disabled=no comment=VSC_100",
            "junos_routing": "set security policies from-zone trust to-zone untrust policy VSC_200 then permit",
            "aruba_routing": "ip route 203.0.113.0/24 192.0.2.1",
        }
        for ident, command in expected.items():
            demo, driver = Demo(ident), DRIVERS[ident]()
            snapshot = driver.parse(demo.running, demo.identity, demo.command("/interface print detail without-paging") if ident == "routeros" else "")
            self.assertIn(command, driver.plan(intent_for(snapshot, ident != "aruba_routing"), snapshot).commands)

    def test_stale_or_tampered_plan_sends_no_changes(self):
        for tamper in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                demo = Demo("ios_router"); service = ProvisioningService("ios_router", demo, Store(directory))
                snap = service.connect(); plan = service.preview(intent_for(snap))
                if tamper: plan.commands.insert(0, "reload")
                else: demo.running = demo.running.replace("LAB-ROUTER", "CHANGED")
                with self.assertRaises((RuntimeError, ValueError)): service.apply(plan)
                self.assertNotIn("configure terminal", demo.sent)

    def test_silent_nonapplication_never_reports_verified(self):
        for ident in ("ios_router", "fortios", "routeros", "junos_routing", "aruba_routing"):
            with self.subTest(platform=ident), tempfile.TemporaryDirectory() as directory:
                demo = Demo(ident); service = ProvisioningService(ident, demo, Store(directory))
                snap = service.connect(); plan = service.preview(intent_for(snap, ident != "aruba_routing"))
                original = demo.command
                def command(cmd):
                    if "10.20.0.1" in cmd: return ""
                    return original(cmd)
                demo.command = command
                with self.assertRaisesRegex(RuntimeError, "verification failed"): service.apply(plan)
                self.assertEqual(service.store.history()[0][2], "failed / possibly partial")

    def test_validate_injection_prefixes_ports_and_overlap(self):
        driver = IOSRouter(); demo = Demo(driver.id); snap = driver.parse(demo.running, demo.identity)
        for field, value in (("id", "a;reload"), ("port", "65536"), ("source", "10.1.2.3/24"), ("destination", "::/0"), ("protocol", "tcp\nreload")):
            intent = intent_for(snap); intent.policies[0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): driver.plan(intent, snap)
        intent = intent_for(snap); intent.interfaces[0]["address"] = "192.0.2.20/24"
        with self.assertRaisesRegex(ValueError, "Overlapping"): driver.plan(intent, snap)
        intent = intent_for(snap); intent.routes[0]["gateway"] = "198.51.100.1"
        with self.assertRaisesRegex(ValueError, "next hop"): driver.plan(intent, snap)

    def test_duplicate_route_prefix_and_wrong_platform_nat_are_rejected(self):
        driver = IOSRouter(); identity, running = SAMPLES[driver.id]; snap = driver.parse(running, identity)
        intent = intent_for(snap)
        intent.routes.append(intent.routes[0] | {"id": "101"})
        with self.assertRaisesRegex(ValueError, "one new route"): driver.plan(intent, snap)
        intent = intent_for(snap); intent.policies[0]["nat"] = "enable"
        with self.assertRaisesRegex(ValueError, "only on FortiOS"): driver.plan(intent, snap)

    def test_fortios_policy_nat_and_disabled_sdwan_defaults(self):
        driver = FortiOS(); identity, running = SAMPLES[driver.id]
        running += "config system sdwan\n set status disable\nend\n"
        snap = driver.parse(running, identity)
        self.assertTrue(snap.interfaces["port1"]["editable"])
        intent = intent_for(snap); intent.policies[0]["nat"] = "enable"
        self.assertIn('set nat "enable"', driver.plan(intent, snap).commands)
        running = running.replace("set status disable", "set status enable")
        snap = driver.parse(running, identity)
        with self.assertRaisesRegex(ValueError, "routed interfaces"): driver.plan(intent, snap)

    def test_existing_acl_binding_and_forti_object_collisions_rejected(self):
        driver = IOSRouter(); identity, running = SAMPLES[driver.id]
        running = running.replace("interface GigabitEthernet0/1\n", "interface GigabitEthernet0/1\n ip access-group EXISTING in\n")
        snap = driver.parse(running, identity)
        with self.assertRaisesRegex(ValueError, "ACL already exists"): driver.plan(intent_for(snap), snap)
        driver = FortiOS(); identity, running = SAMPLES[driver.id]
        running += 'config firewall address\n edit "VSC_200_src"\n set subnet 10.0.0.0 255.0.0.0\n next\nend\n'
        snap = driver.parse(running, identity)
        with self.assertRaisesRegex(ValueError, "already exists"): driver.plan(intent_for(snap), snap)

    def test_fortios_rejects_vdom_ha_and_special_modes(self):
        driver = FortiOS(); identity, running = SAMPLES[driver.id]
        for changed in (identity.replace("disable", "enable"), identity.replace("standalone", "a-p"), identity.replace("NAT", "Transparent")):
            with self.assertRaises(ValueError): driver.parse(running, changed)
        for extra in ("set central-nat enable", "set ngfw-mode policy-based", "set cfg-save manual", "set type fortimanager"):
            with self.assertRaises(ValueError): driver.parse(running + "\n" + extra, identity)

    def test_routeros_bridge_members_not_editable_and_defaults_normalized(self):
        driver = RouterOS(); demo = Demo(driver.id)
        extra = demo.command("/interface print detail without-paging")
        snap = driver.parse(demo.running + "/interface bridge port add bridge=bridge1 interface=ether2\n", demo.identity, extra)
        self.assertFalse(snap.interfaces["ether2"]["editable"])
        self.assertEqual(snap.facts["/ip address"]["WAN"]["disabled"], "no")

    def test_junos_candidate_is_not_discarded_or_committed(self):
        with tempfile.TemporaryDirectory() as directory:
            demo = Demo("junos_routing"); service = ProvisioningService("junos_routing", demo, Store(directory))
            snap = service.connect(); plan = service.preview(intent_for(snap))
            original = demo.command
            demo.command = lambda cmd: "+ someone else's edit" if cmd == "show | compare" else original(cmd)
            with self.assertRaisesRegex(RuntimeError, "Existing Junos candidate"): service.apply(plan)
            self.assertNotIn("commit", demo.sent); self.assertNotIn("rollback 0", demo.sent)

    def test_junos_commit_acknowledgement_required(self):
        for reject in ("commit check", "commit"):
            with tempfile.TemporaryDirectory() as directory:
                demo = Demo("junos_routing"); service = ProvisioningService("junos_routing", demo, Store(directory))
                snap = service.connect(); plan = service.preview(intent_for(snap))
                original = demo.command
                demo.command = lambda cmd: "" if cmd == reject else original(cmd)
                with self.assertRaises(RuntimeError): service.apply(plan)
                self.assertIn("rollback 0", demo.sent)

    def test_backup_failure_prevents_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            demo = Demo("ios_router"); service = ProvisioningService("ios_router", demo, Store(directory))
            plan = service.preview(intent_for(service.connect()))
            with patch("pathlib.Path.write_text", side_effect=OSError("disk full")), self.assertRaises(OSError): service.apply(plan)
            self.assertNotIn("configure terminal", demo.sent)

    def test_ssh_requires_known_host_keys_and_never_saves_password(self):
        transport = SSHTransport("192.0.2.2", "admin", "password", "cisco_ios", secret="enable-secret")
        self.assertTrue(transport.options["ssh_strict"])
        self.assertTrue(transport.options["system_host_keys"])
        with patch("netmiko.ConnectHandler") as connector:
            connector.return_value.find_prompt.return_value = "router#"
            transport.connect()
            connector.assert_called_once()
            self.assertEqual(transport.options["password"], "")
            self.assertEqual(transport.options["secret"], "")
            transport.command("show version")
            self.assertEqual(connector.return_value.send_command.call_args.kwargs["read_timeout"], 90)

    def test_junos_disconnect_cannot_auto_answer_discard_prompt(self):
        transport = SSHTransport("192.0.2.2", "admin", "password", "juniper_junos")
        with patch("netmiko.ConnectHandler") as connector:
            connection = connector.return_value
            connection.find_prompt.return_value = "admin@srx>"
            transport.connect()
            old_cleanup = connection.cleanup
            connection.disconnect.side_effect = lambda: connection.cleanup()
            transport.close()
            old_cleanup.assert_not_called()


if __name__ == "__main__": unittest.main()
