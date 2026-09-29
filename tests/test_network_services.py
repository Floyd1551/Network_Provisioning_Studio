import copy
import tempfile
import unittest
from switch_configurator.storage import Store
from switch_configurator.provisioning.model import Intent
from switch_configurator.provisioning.demo import Demo
from switch_configurator.provisioning.drivers import ios_blocks
from switch_configurator.provisioning.service import ProvisioningService


def services():
    return [
        dict(id="dns1", type="dns", server="192.0.2.53"),
        dict(id="ntp1", type="ntp", server="192.0.2.123"),
        dict(id="v6", type="ipv6", interface="GigabitEthernet0/0", address="2001:db8:1::2/64"),
        dict(id="route6", type="route6", interface="GigabitEthernet0/0", destination="2001:db8:2::/64", gateway="2001:db8:1::1"),
        dict(id="dhcp1", type="dhcp", interface="GigabitEthernet0/1", start="10.20.0.100", end="10.20.0.199", server="192.0.2.53"),
        dict(id="ospf1", type="ospf", interface="GigabitEthernet0/0", process="10", router_id="192.0.2.2", area="0.0.0.0"),
    ]


class NetworkServiceTests(unittest.TestCase):
    def wireguard(self):
        import base64
        return dict(id="branch", type="wireguard", address="10.99.0.1/30", remote_network="10.50.0.0/24", public_key=base64.b64encode(bytes(range(32))).decode(), endpoint="192.0.2.20", listen_port="51820", endpoint_port="51820")

    def test_wireguard_adds_interface_peer_and_route_without_private_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ProvisioningService("routeros", Demo("routeros"), Store(directory)); service.connect()
            row = self.wireguard(); plan = service.preview(Intent(services=[row]))
            self.assertEqual(len(plan.commands), 4)
            self.assertIn("gateway=VSC_branch", plan.commands[-1])
            self.assertNotIn("private-key", "\n".join(plan.commands))
            after, _ = service.apply(plan)
            self.assertFalse(service.driver.verify(plan, after))
            with self.assertRaises(ValueError): service.preview(Intent(services=[row]))

    def test_wireguard_rejects_bad_keys_overlaps_endpoint_recursion_and_other_platforms(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ProvisioningService("routeros", Demo("routeros"), Store(directory)); service.connect()
            for change in ({"public_key": "not-a-key"}, {"remote_network": "192.0.2.0/24"}, {"endpoint": "10.50.0.2"}, {"listen_port": "0"}, {"remote_network": "0.0.0.0/0"}):
                with self.assertRaises(ValueError): service.preview(Intent(services=[dict(self.wireguard(), **change)]))
            with self.assertRaisesRegex(ValueError, "route to this remote"):
                service.preview(Intent(services=[self.wireguard()], routes=[dict(id="remote", destination="10.50.0.0/24", gateway="192.0.2.1", interface="ether1")]))
            ios = self.service(directory)
            with self.assertRaisesRegex(ValueError, "only on RouterOS"): ios.preview(Intent(services=[self.wireguard()]))

    def test_existing_svi_can_be_addressed_then_serve_dhcp_without_enabling_port(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory, "interface Vlan20\n no ip address\n shutdown\n")
            svi = dict(id="lan20", type="svi", interface="Vlan20", address="10.20.0.1/24")
            dhcp = dict(services()[4], interface="Vlan20")
            plan = service.preview(Intent(services=[dhcp, svi]))
            self.assertLess(plan.commands.index("interface Vlan20"), plan.commands.index("ip dhcp pool VSC_dhcp1"))
            self.assertNotIn("no shutdown", plan.commands)
            after, _ = service.apply(plan)
            self.assertEqual(after.interfaces["Vlan20"]["address"], "10.20.0.1/24")
            self.assertIn("shutdown", after.interfaces["Vlan20"]["lines"])
            with self.assertRaisesRegex(ValueError, "unaddressed"):
                service.preview(Intent(services=[svi]))

    def test_junos_services_use_exclusive_commit_and_reject_other_types(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ProvisioningService("junos_routing", Demo("junos_routing"), Store(directory)); service.connect()
            plan = service.preview(Intent(services=services()[:2]))
            self.assertEqual(plan.commands[0], "configure exclusive")
            self.assertEqual(plan.commands[-3:], ["commit check", "commit", "exit"])
            self.assertIn("set system name-server 192.0.2.53", plan.commands)
            after, _ = service.apply(plan)
            self.assertFalse(service.driver.verify(plan, after))
            with self.assertRaisesRegex(ValueError, "already configured"):
                service.preview(Intent(services=services()[:1]))
            with self.assertRaisesRegex(ValueError, "only DNS and NTP"):
                service.preview(Intent(services=services()[2:3]))

    def service(self, directory, extra="ipv6 unicast-routing\n"):
        transport = Demo("ios_router")
        transport.running = transport.running.replace("ipv6 unicast-routing\n", "")
        transport.running = transport.running.replace("end\n", extra + "end\n")
        transport.blocks = ios_blocks(transport.running)
        service = ProvisioningService("ios_router", transport, Store(directory))
        service.connect()
        return service

    def test_combined_services_apply_with_backup_and_readback(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory)
            intent = Intent(interfaces=[dict(name="GigabitEthernet0/1", address="10.20.0.1/24")], services=services())
            plan = service.preview(intent)
            self.assertIn("ip dhcp excluded-address 10.20.0.1 10.20.0.99", plan.commands)
            self.assertIn("ip dhcp excluded-address 10.20.0.200 10.20.0.254", plan.commands)
            self.assertIn("network 192.0.2.2 0.0.0.0 area 0", plan.commands)
            self.assertIn("passive-interface default", plan.commands)
            after, path = service.apply(plan)
            self.assertTrue((path / "before.cfg").exists())
            self.assertTrue((path / "after.cfg").exists())
            self.assertFalse(service.driver.verify(plan, after))
            self.assertIn("configuration verified", service.store.history()[0])

    def test_existing_services_and_wrong_platform_are_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            for extra, entry in [("ntp authenticate\n", services()[1]), ("ip name-server 192.0.2.53 192.0.2.54\n", services()[0]), ("router ospf 20\n", services()[-1])]:
                service = self.service(directory, extra)
                with self.assertRaises(ValueError): service.preview(Intent(services=[entry]))
            service = ProvisioningService("fortios", Demo("fortios"), Store(directory)); service.connect()
            with self.assertRaisesRegex(ValueError, "services"): service.preview(Intent(services=[services()[0]]))

    def test_ipv6_forwarding_overlap_and_route_reachability_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory, "")
            with self.assertRaisesRegex(ValueError, "forwarding"): service.preview(Intent(services=[services()[2]]))
            service = self.service(directory)
            first, route = copy.deepcopy(services()[2:4])
            route["gateway"] = "2001:db8:9::1"
            with self.assertRaisesRegex(ValueError, "directly connected"): service.preview(Intent(services=[first, route]))
            second = dict(first, id="other", interface="GigabitEthernet0/1", address="2001:db8:1::3/64")
            with self.assertRaisesRegex(ValueError, "Overlapping"): service.preview(Intent(services=[first, second]))

    def test_dhcp_rejects_gateway_inside_pool_and_existing_allocation(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory)
            row = dict(services()[4], interface="GigabitEthernet0/0", start="192.0.2.1", end="192.0.2.99")
            with self.assertRaisesRegex(ValueError, "exclude the gateway"): service.preview(Intent(services=[row]))
            row.update(start="192.0.2.100", end="192.0.2.199")
            service = self.service(directory, "ip dhcp pool OLD\n network 192.0.2.0 255.255.255.0\n")
            with self.assertRaisesRegex(ValueError, "Existing DHCP"): service.preview(Intent(services=[row]))

    def test_unapplied_command_is_not_verified_and_plan_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory)
            plan = service.preview(Intent(services=[services()[0]]))
            self.assertTrue(service.driver.verify(plan, service.discover()))
            plan.commands.insert(1, "ntp server 192.0.2.9")
            with self.assertRaisesRegex(ValueError, "modified"): service.apply(plan)

    def test_schema_injection_and_legacy_drafts(self):
        old = Intent.from_dict({"routes": [dict(id="r", destination="0.0.0.0/0", gateway="192.0.2.1", interface="Gi0/0")]})
        self.assertEqual(old.services, [])
        for row in [dict(services()[0], server="192.0.2.53\nend"), dict(services()[-1], process="1;end"), dict(services()[2], address="fe80::1/64")]:
            with self.assertRaises(ValueError): Intent(services=[row]).validate()

    def test_merged_dns_and_uppercase_ipv6_readback(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory)
            plan = service.preview(Intent(services=services()[:4]))
            after, _ = service.apply(plan)
            running = after.running.replace("ip name-server 192.0.2.53", "ip name-server 192.0.2.53 192.0.2.54").replace("2001:db8:", "2001:DB8:")
            observed = service.driver.parse(running, service.transport.identity)
            self.assertFalse(service.driver.verify(plan, observed))
