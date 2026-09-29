# Router and firewall provisioning — 1.0 RC1

This release expands the application into Network Provisioning Studio. It is an initial provisioning implementation, not a claim to manage most network devices or every feature of the listed brands. All adapters use synthetic fixtures and demos; no real equipment or live SSH server was used for qualification.

The [scenario wizard](PROVISIONING_WIZARD.md) now provides guided combinations of the capabilities below. It does not expand the underlying platform support or deploy without the existing command-review step.

## Current capability matrix

| Platform | Discover/export | Interface IPv4 | New static routes | Traffic rules | Source NAT |
| --- | --- | --- | --- | --- | --- |
| Cisco IOS / IOS-XE | Yes | Existing standalone routed physical interfaces | IPv4, directly reachable next hop | New inbound extended ACLs; stateless | No |
| Fortinet FortiOS 7.x | Yes | Static physical interfaces | IPv4, directly reachable next hop | New explicit IPv4 firewall policies, address and service objects | Optional outgoing-interface NAT on an allow policy |
| Juniper Junos / SRX | Yes | Existing ge/xe/et physical interfaces, unit 0 | IPv4, main routing table | SRX policies between existing security zones | No |
| Aruba AOS-CX | Yes | Existing routed physical ports | IPv4, main routing table | No | No |
| MikroTik RouterOS 7.x | Yes | Add to an unaddressed, standalone interface | IPv4, main routing table | New forward-chain IPv4 filters | New source masquerade entries |
| Palo Alto PAN-OS | Yes | No | No | No | No |
| Check Point Gaia | Yes | No | No | No | No |
| SonicWall SonicOS | Yes, generic SSH CLI; unqualified | No | No | No | No |

Palo Alto, Check Point and SonicWall entries in this SSH workspace are explicitly labeled **discovery only**. Version 0.6 adds a separate **Firewall APIs** workspace with native, bounded access-rule provisioning for these platforms. See [API transactions and restrictions](FIREWALL_APIS.md); the SSH adapters do not send those changes.

The switch drivers in [SUPPORTED_PLATFORMS.md](SUPPORTED_PLATFORMS.md) continue to handle Layer 2 switching independently. An Aruba routing selection does not add firewall capabilities; a Cisco ACL does not become a stateful firewall.

## Workflow

1. Open **Routers / firewalls**. Choose the exact OS family.
2. Try **Demo**, or select **SSH** and enter host, port, username, password and an enable secret where required. SSH uses strict host-key checking against the user's `~/.ssh/known_hosts` plus an optional additional known-hosts file. Unknown or changed keys are rejected. Verify the key through a trusted channel and enroll it before connecting; the app does not auto-trust it.
3. Connect to read identity and configuration. The selected OS must match. Unsupported interface configurations remain unavailable for editing.
4. Use **Set interface IPv4**, **Add static route**, **Add traffic rule** or **Add source NAT** where enabled. Changes appear as readable summaries. Nothing is deployed while staging.
5. Save/load platform-specific JSON drafts if useful. Drafts contain network intent, not SSH credentials. Draft reuse never bypasses discovery, validation or review. Entries can be removed individually.
6. Review the native commands, requested intent, current configuration, policy-order warnings and persistence behavior. Application requires the review checkbox and Apply button.
7. Apply rechecks the snapshot, writes a before backup and command plan, journals each command, reads configuration again and verifies modeled fields. Success means **configuration readback verified**, not end-to-end connectivity or effective policy behavior.

Backups and history share `%LOCALAPPDATA%\VisualSwitchConfigurator` with the switch workspace. They contain plaintext device configuration and may contain device secrets. SSH sign-in credentials are not intentionally written to drafts or history. Netmiko may adjust terminal paging during session preparation; on FortiOS it may temporarily change and subsequently restore console output mode.

## Intent and deployment limits

Version 0.5 adds a separate `services` draft section. Its [network service scenarios](NETWORK_SERVICES.md) include bounded IPv6 and existing-SVI support on IOS plus DNS/NTP on Junos. The IPv4 interface/route/policy forms and matrix above retain their existing scope. The following IPv4-only limits describe those original forms, not the new service scenarios.

- IPv4 only. CIDRs must use canonical network prefixes; interface IPs must be valid host addresses. Overlapping interface subnets, duplicate route prefixes and unreachable directly connected next hops are rejected.
- Existing routes and policy objects are not overwritten. Generated names use the `VSC_` prefix. Existing identifiers and IOS inbound ACL bindings cause a refusal instead of replacement. Policy reordering, deletion and bulk replacement are not implemented.
- Interface address changes preserve administrative state. They do not enable a shutdown port, convert a switched port to routed mode, create VLAN subinterfaces or provision an SVI. Management can disconnect if its address or path changes.
- **IOS:** one new rule/ACL per ingress interface in a draft. ACLs are stateless and end in implicit deny. The UI's egress interface validates topology intent, but an IOS interface ACL does not match an egress interface: it matches the destination prefix. Existing inbound ACLs are not replaced. Review this before creating a rule. Cisco ASA, FTD and Meraki are not supported by this driver.
- **FortiOS:** standalone, NAT operation mode, VDOMs disabled, profile-based NGFW and automatic-save mode only. Central NAT, HA, FortiManager management, SD-WAN, zones, virtual/software switches, secondary addresses and nonzero VRFs are excluded or block editing. Numeric positive route/policy IDs are required. New rules are appended. The forms can enable source NAT using the outgoing interface's address on an allow policy. UTM/IPS/AV, TLS inspection, DNAT/VIPs and central SNAT are not provisioned.
- **Junos:** existing unit-0 routed ports only. Inherited groups, interface ranges, routing instances, aggregation and unsupported interface modes are excluded. SRX policy creation requires existing, distinct security zones and global address-book use. New address/application/policy objects are created; existing policies retain precedence. Exclusive configuration locking, clean-candidate checks, an active-configuration guard under lock, `commit check`, positive `commit` acknowledgement and readback are required. Error recovery issues `rollback 0` only for a candidate this session established as clean before editing. SSH teardown does not auto-answer Netmiko's discard prompt; device-side disconnect behavior still applies. Commit-confirmed and rollback of a completed commit are not implemented.
- **AOS-CX:** an interface must already explicitly have `routing` enabled. VRFs, LAGs, inherited policies and multiple/secondary addresses are excluded. ArubaOS-Switch, Comware and Aruba gateways are not handled by this routing driver.
- **RouterOS:** version 7 only. Bridge members, DHCP-client interfaces, disabled/multiple address configurations, VRF, bonding and VRRP configurations are excluded. Addresses can only be added to currently unaddressed interfaces. Filter and NAT rules are appended, so preceding rules and FastTrack may prevent a new rule from taking effect. No automatic stateful/default-deny baseline is installed. A source-NAT entry does not itself permit forwarding.
- PAN-OS, Gaia and SonicOS expose configuration text, not a complete normalized inventory. Their authentication, prompts and paging must be qualified on the exact device release. SonicOS uses Netmiko's generic terminal adapter; configure a nonpaged CLI session if necessary. A timeout is an error, not a successful partial capture.

## Persistence

| Driver | Persistence behavior |
| --- | --- |
| IOS / IOS-XE, AOS-CX | Running configuration; save startup configuration manually after validation |
| FortiOS | Applied and persisted automatically in supported automatic-save mode |
| Junos | Successful commit persists across reboot |
| RouterOS | Each command applies and persists immediately |
| Discovery-only adapters | No provisioning commands generated |

Sequential CLI failures can leave partial changes. Automatic recovery of committed configuration, fleet orchestration, controller-managed deployment and unattended rollout are outside this release.

## Next platform work

Native API transactions and initial network-service scenarios are now implemented in their respective workspaces. Remaining coverage includes physical qualification, additional API object/NAT operations, more routing protocols and VPN types, SVI creation and additional platform service adapters. Structured recovery remains deferred. Manufacturer names alone are insufficient to select the right API, firmware syntax or policy scope.

## References

- [Cisco IOS ACL configuration](https://www.cisco.com/c/en/us/support/docs/security/ios-firewall/23602-confaccesslists.html).
- [FortiOS CLI reference](https://docs.fortinet.com/document/fortigate/7.6.2/cli-reference/708841/cli-configuration-commands) and [firewall policies](https://docs.fortinet.com/document/fortigate/7.4.1/administration-guide/656084/firewall-policy).
- [Junos security policies](https://www.juniper.net/documentation/us/en/software/junos/security-policies/security-policies.pdf) and [configuration commits](https://www.juniper.net/documentation/us/en/software/junos/cli/topics/topic-map/junos-configuration-commit.html).
- [AOS-CX IP routing](https://www.arubanetworks.com/techdocs/AOS-CX/10.13/PDF/ip_route_8400.pdf).
- [RouterOS addressing](https://help.mikrotik.com/docs/spaces/ROS/pages/328247/IP%2BAddressing), [filters](https://help.mikrotik.com/docs/spaces/ROS/pages/48660608/Filter), and [NAT](https://help.mikrotik.com/docs/spaces/ROS/pages/3211299/NAT).
- [PAN-OS operational CLI](https://docs.paloaltonetworks.com/ngfw/pan-os-cli-quick-start/cli-command-hierarchy/pan-os-11-1-cli-ops-command-hierarchy).
- [Gaia administration](https://sc1.checkpoint.com/documents/R81/WebAdminGuides/EN/CP_R81_Gaia_AdminGuide/CP_R81_Gaia_AdminGuide.pdf).
- [SonicOS CLI](https://www.sonicwall.com/techdocs/pdf/sonicos-6-5-enterprise-command-line-reference-guide.pdf).
- [Netmiko SSH API and host-key checking](https://ktbyers.github.io/netmiko/docs/netmiko/).
