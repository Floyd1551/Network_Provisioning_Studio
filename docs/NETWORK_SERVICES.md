# Network service scenarios — 1.0 RC1

Open **Routers / firewalls**, select Cisco IOS/IOS-XE, Juniper Junos or MikroTik RouterOS, connect, then choose **Network services**. Select a scenario, enter its settings and stage it. Review provisioning reads fresh state and shows the full native command plan. No commands are sent by the settings form.

| Scenario | IOS / IOS-XE | Junos | Scope |
| --- | --- | --- | --- |
| DNS | Yes | Yes | Add an IPv4 resolver for the device; no DNS server setup |
| NTP | Yes | Yes | Add an unauthenticated IPv4 time source; complex existing authentication/source settings block planning |
| DHCP | Yes | No | Create a pool for a routed LAN/SVI; exclude addresses outside the requested lease range |
| IPv6 address | Yes | No | Add one canonical unicast address to an unaddressed IPv6 interface |
| IPv6 static route | Yes | No | New prefix through a directly connected or interface-scoped link-local next hop |
| OSPFv2 | Yes | No | New process with one adjacency interface; passive by default, exact local-address network match |
| VLAN interface IPv4 | Yes | No | Address an existing unaddressed SVI; preserve administrative state |
| VPN | No | No | RouterOS 7 supports a separate WireGuard interface/peer/route scenario |

## Preconditions and limits

- All service adapters are hardware-untested. Firmware, licenses and hardware must support the generated commands. The user's 3750X-48 has not been connected or qualified.
- IOS service interfaces must be discovered standalone routed ports or simple existing SVIs. VRFs, secondary addresses, unnumbered and policy-routed interfaces are excluded. VLAN/SVI creation and bridge configuration are not implemented here.
- IPv6 forwarding must already be enabled. The app does not enable it globally, add IPv6 firewall rules, or claim IPv6 traffic is protected by existing IPv4 ACLs. Existing IPv6 addresses are not replaced.
- DHCP uses the selected interface's static IPv4 subnet and gateway, including an address staged in the same draft. Existing pools/exclusions and interface relays block the scenario. The lease range must exclude the gateway. Other DHCP servers on the LAN are not detected.
- OSPF rejects an existing OSPFv2 configuration. Authentication, redistribution, default route origination, multiple areas, OSPFv3 and BGP are not implemented. The new process may learn routes and affect traffic paths.
- DNS server addresses are additive; DNS forwarding service is not enabled. NTP reachability/synchronization is not tested. Existing server identifiers are not silently reused or overwritten.
- IOS affects running configuration; startup saving remains manual. Junos uses the existing exclusive lock, clean-candidate checks, commit check and positive commit acknowledgement.
- Readback verifies modeled configuration, not operational service behavior. Errors may leave partial changes. Phase 5 recovery remains deferred.

## Example: SVI plus DHCP

If an existing `Vlan20` has no address, stage **Existing VLAN interface IPv4** with `10.20.0.1/24`. Then stage **DHCP server pool** for `Vlan20`, leases `10.20.0.100` through `10.20.0.199`, and your DNS server. The combined plan addresses the SVI before configuring its pool and excludes all other usable subnet addresses. A shutdown SVI remains shutdown. Ensure VLAN membership, uplinks, routing and security policy are configured separately.

## RouterOS WireGuard

Select RouterOS 7 and **Network services → WireGuard VPN peer + route**. Supply a local tunnel address, remote network, peer public key, numeric endpoint and UDP ports. The router generates the private key; the draft never supplies one. The plan creates a new interface, address, peer and route. Existing names, listen ports, conflicting routes and overlapping networks block planning. Full-tunnel default routing is excluded.

Configure the remote peer with this router's public key and the return route. UDP input and tunnel forwarding rules must be configured separately; this scenario does not bypass firewall policy or add NAT. Handshake and traffic checks are not implemented. Do not share private keys. See [MikroTik WireGuard reference](https://help.mikrotik.com/docs/spaces/ROS/pages/69664792/WireGuard).

## Reference syntax

- [Cisco DHCP server](https://www.cisco.com/c/en/us/td/docs/routers/ios/config/17-x/ip-addressing/b-ip-addressing/m_config-dhcp-server-xe.html)
- [Cisco IPv6 addressing](https://www.cisco.com/c/en/us/td/docs/routers/ios/config/17-x/ip-addressing/b-ip-addressing/m_ip6-add-basic-conn-xe.html)
- [Cisco OSPF passive interfaces](https://www.cisco.com/c/en/us/td/docs/routers/ios-xe/ip-routing/b-ip-routing/m_iri-default-passive-interface.html)
- [Cisco DNS and NTP administration](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst3850/software/release/16-6/configuration_guide/sys_mgmt/b_166_sys_mgmt_3850_cg/b_166_sys_mgmt_3850_cg_chapter_00.html)
- [Junos NTP servers](https://www.juniper.net/documentation/us/en/software/junos/time-mgmt/topics/concept/ntp-time-servers.html)
