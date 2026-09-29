# Supported switch platform scope — 1.0 RC1

Support is tied to the operating system and CLI dialect, not every product carrying a manufacturer's name. All drivers are tested with synthetic fixtures and simulators only; no physical hardware has been qualified. The seven newly added drivers are marked experimental in the application.

Core editing means port description, administrative enable/disable, access/trunk intent, access VLAN, native VLAN, allowed VLANs and VLAN creation. Routed ports, aggregation members and recognized unsupported configuration are excluded from editing. Unrecognized required discovery output stops managed configuration.

| Manufacturer | Target OS / family | Editing scope | Important exclusions |
| --- | --- | --- | --- |
| Cisco | IOS / IOS-XE Catalyst | Core; voice VLAN; PoE auto/never; speed; duplex; PortFast; BPDU Guard | Other Cisco operating systems require separate drivers |
| Arista Networks | EOS | Core; PortFast; BPDU Guard | Advanced MLAG, inherited configuration and other features are not modeled |
| HPE Aruba Networking | AOS-CX | Core | ArubaOS-Switch/ProCurve, Comware and Instant On are unsupported |
| Juniper | Junos EX/QFX with ELS | Core; candidate validation and commit | Non-ELS `port-mode`, inherited groups/interface ranges, routed and aggregated ports are unsupported |
| Extreme Networks | Switch Engine / ExtremeXOS | Core mapped to tagged/untagged VLAN membership | Fabric Engine/VOSS and other Extreme OS families are unsupported |
| Dell | SmartFabric OS10, Full Switch mode | Core | SmartFabric mode, OS6, OS9 and SONiC are unsupported |
| TP-Link | JetStream General-port CLI | Core mapped to PVID and tagged/untagged membership | Other firmware dialects, legacy access/trunk modes and unmanaged switches are unsupported |
| Cisco (additional) | Standalone NX-OS Nexus | Core | ACI mode is unsupported; device-specific reserved VLANs still apply |

Voice VLAN, PoE configuration, speed and duplex controls are disabled for the added platforms. STP controls are also disabled except on Arista EOS. A role profile loads only supported fields and identifies skipped fields.

## Platform selection and discovery

Select a platform explicitly or choose Auto. Auto checks read-only identity output; TP-Link uses `show system-info`. Explicit selection still verifies the reported OS before setup commands. Discovery and command generation use a separate driver for each dialect. The COM connection is serial only; SSH and NETCONF are not implemented.

The simulated connection uses Cisco IOS when Auto is selected. Choose another platform to exercise its own stateful two-port sample. Samples are hand-authored examples, not hardware captures or complete OS emulators.

## VLAN and persistence differences

- On EXOS and JetStream, a port with one untagged VLAN and no tagged memberships appears as access; a port with tagged memberships appears as trunk. Allowed VLANs means tagged VLANs only and must exclude the native/PVID VLAN. Trunks require a finite, nonempty list, and referenced VLANs must exist or be staged for creation. More complex membership is read-only.
- AOS-CX and OS10 use additive trunk-list commands. The generated plan explicitly removes obsolete memberships before adding the requested list. OS10 requires explicit VLAN lists and limits IDs to 4093.
- Junos and EXOS use VLAN names as configuration keys. Existing VLAN renaming and duplicate names are rejected.
- Junos obtains an exclusive candidate lock, refuses a pre-existing dirty candidate, checks the active configuration under the lock, and requires positive `commit check` and `commit` acknowledgements. A successful commit persists across reboot. It does not use commit-confirmed or automatically undo a completed commit.
- Other drivers affect running configuration only. Save startup configuration manually after validation if persistence is desired.
- Mode and membership changes may affect related fields even when those fields were not separately checked. Inspect the exact native CLI in the review dialog before applying.

## Qualification limits

Tests cover the supported sample dialects and safety paths, not all firmware variants or effective inherited defaults. Physical placement is inferred from names. Optional inventory/neighbor commands can be unavailable and are reported. Full model-specific chassis maps, global settings, VLAN deletion, advanced routing, MLAG/stack management and automatic committed rollback are outside this release.

Before using a particular model operationally, validate discovery, generated commands and readback against that model and firmware on a lab switch. Keep a separate console recovery path. Backups are plaintext under `%LOCALAPPDATA%\VisualSwitchConfigurator`.

## Command references

- [Arista EOS CLI](https://www.arista.com/en/um-eos/eos-command-line-interface-cli) and [spanning tree](https://www.arista.com/en/um-eos/eos-spanning-tree-protocol).
- [Aruba AOS-CX 6100 fundamentals](https://www.arubanetworks.com/techdocs/AOS-CX/10.06/PDF/6100/Fundamentals%206100.pdf).
- [Junos display-set](https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/command/show-pipe-display-set.html), [configuration modes](https://www.juniper.net/documentation/us/en/software/junos/cli/topics/topic-map/modifying-configuration.html) and [commit workflow](https://www.juniper.net/documentation/us/en/software/junos/cli/topics/topic-map/junos-configuration-commit.html).
- [Extreme Switch Engine command reference](https://documentation.extremenetworks.com/switchengine_commands_32.7.1/downloads/SwitchEngine_Command_Reference_32.7.1.pdf).
- [Dell SmartFabric OS10 user guide](https://dl.dell.com/manuals/common/SmartFabricOS-10-5-0-UG-en-us.pdf).
- [TP-Link switching CLI differences](https://www.tp-link.com/us/configuration-guides/q_a_ethernet_switching/) and [system commands](https://www.tp-link.com/us/configuration-guides/managing_system/).
- [Cisco NX-OS Layer 2 interfaces](https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/104x/configuration/interfaces/cisco-nexus-9000-series-nx-os-interfaces-configuration-guide-release-104x/m_configuring_layer_2_interfaces_9x.html).

These references guided the implementation; they do not certify compatibility with every documented release or feature.
