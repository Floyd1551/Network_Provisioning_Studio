"""Independent IOS-shaped fixtures, separate from the simulated command generator."""
import unittest
from switch_configurator.driver import parse_device, commands
from switch_configurator.model import ChangeSet


OUTPUTS = {
    "show version": "Cisco IOS Software, C2960X Software (C2960X-UNIVERSALK9-M), Version 15.2(7)E9, RELEASE SOFTWARE (fc1)\ncisco WS-C2960X-48FPD-L (APM86XXX) processor (revision E0) with 524288K bytes of memory.",
    "show running-config": """Building configuration...
Current configuration : 5432 bytes
!
version 15.2
hostname ACCESS-02
!
interface GigabitEthernet1/0/1
 description Reception phone
 switchport access vlan 10
 switchport mode access
 switchport voice vlan 20
 spanning-tree portfast
 spanning-tree bpduguard enable
!
interface GigabitEthernet1/0/2
 shutdown
!
interface TenGigabitEthernet1/0/1
 description Core
 switchport trunk native vlan 99
 switchport trunk allowed vlan 10,20,99
 switchport mode trunk
!
end
""",
    "show interfaces status": """Port      Name               Status       Vlan       Duplex  Speed Type
Gi1/0/1   Reception phone    connected    10         a-full a-1000 10/100/1000BaseTX
Gi1/0/2                      disabled     1            auto   auto 10/100/1000BaseTX
Te1/0/1   Core               connected    trunk        full    10G SFP-10GBase-SR
""",
    "show vlan brief": """VLAN Name                             Status    Ports
---- -------------------------------- --------- -------------------------------
1    default                          active    Gi1/0/2
10   STAFF                            active    Gi1/0/1
20   VOICE                            active    Gi1/0/1
99   MANAGEMENT                       active
1002 fddi-default                     act/unsup
""",
    "show power inline": """Interface Admin  Oper       Power   Device              Class Max
Gi1/0/1   auto   on         6.3     IP Phone 8841       4     30.0
Gi1/0/2   auto   off        0.0     n/a                 n/a   30.0
""",
    "show cdp neighbors detail": "Device ID: CORE-01\nInterface: TenGigabitEthernet1/0/1, Port ID (outgoing port): TenGigabitEthernet2/0/1",
    "show switch": "% Invalid input detected at '^' marker.",
}


class IOSFixtureTests(unittest.TestCase):
    def test_legacy_model_and_blank_description_status(self):
        device = parse_device(OUTPUTS)
        self.assertEqual(device.model, "WS-C2960X-48FPD-L")
        self.assertEqual(device.version, "15.2(7)E9")
        self.assertEqual(device.ports["GigabitEthernet1/0/2"].status, "disabled")
        self.assertEqual(device.ports["GigabitEthernet1/0/1"].watts, "6.3")
        self.assertEqual(device.ports["TenGigabitEthernet1/0/1"].neighbor, "CORE-01")
        self.assertTrue(device.warnings)

    def test_admin_enable_is_last_and_disable_first(self):
        device = parse_device(OUTPUTS)
        name = "GigabitEthernet1/0/1"
        for enabled in (True, False):
            result = commands(ChangeSet({name: {"enabled": enabled, "access_vlan": 20}}), device)
            if enabled: self.assertLess(result.index("switchport access vlan 20"), result.index("no shutdown"))
            else: self.assertLess(result.index("shutdown"), result.index("switchport access vlan 20"))


if __name__ == "__main__": unittest.main()
