# Provisioning wizard — 0.4

The wizard is available after connection in **Switch workspace** and **Routers / firewalls**. It has three steps: choose a scenario, enter settings, and review the combined draft. **Add to draft does not send configuration commands.** Use the workspace's existing Review and apply / Review provisioning action to capture fresh device state and approve the native commands.

## Router and firewall scenarios

| Scenario | Staged changes | Availability |
| --- | --- | --- |
| Branch routing foundation | LAN IPv4 address and a route through an existing WAN; optional HTTPS/all-IPv4 rule and source NAT | All five provisioning drivers for routing; traffic/NAT options depend on driver |
| Outbound network access | Explicit service allow rule from an addressed LAN toward an addressed WAN; optional source NAT and default route | IOS, FortiOS, Junos SRX, RouterOS, subject to their policy limits |
| Application / service access | One explicit allow or deny rule for source/destination networks and a protocol/port | Drivers supporting traffic rules |
| Add a routed LAN | IPv4 address on an existing standalone routed interface | All five provisioning drivers; RouterOS requires an unaddressed interface |
| Reach another network | New static route through a directly connected next hop | All five provisioning drivers |
| Source NAT / masquerade | A source-network masquerade rule on an addressed outgoing interface | RouterOS; FortiOS NAT is an option in branch/outbound policy scenarios |

The branch wizard defaults to **Routing only**. Its route destination defaults to `0.0.0.0/0`; it can be changed. Optional branch traffic rules target any IPv4 destination, independently of that route prefix, and the UI labels this explicitly. Source NAT is opt-in. Outbound access defaults to TCP/443; a single HTTPS rule does not provide DNS or all services required by an application. All-IP access must be explicitly selected.

LAN and WAN must be distinct, discovered and editable interfaces. Traffic scenarios require discovered or already staged addresses on both interfaces. The source network is suggested from the selected LAN; branch source prefixes are derived from its new address. Existing draft interface addresses are considered. Next-hop, overlap, object-collision and platform validation are delegated to the same drivers used by manual forms.

Starting identifiers are numeric for portability. A combined scenario uses N for a route, N+1 for its traffic rule, and N+2 for a separate RouterOS NAT entry. Existing object collisions are rejected; the wizard never overwrites an existing policy or silently picks a different order. Change the starting ID or resolve the conflicting entry when needed.

**Scope:** the branch scenario prepares one device's routing configuration. It does not deploy a complete multi-device branch, DHCP, DNS, VPN, dynamic routing, SSIDs or controller settings. Junos security rules still require an SRX and existing zones. IOS rules remain stateless ACLs with implicit deny, not a stateful firewall. Existing platform limitations in [ROUTER_FIREWALL.md](ROUTER_FIREWALL.md) apply.

## Switch scenarios

| Scenario | Staged changes |
| --- | --- |
| Workstation access ports | Create/reuse an access VLAN and assign selected ports |
| Guest VLAN — switch ports | Create/reuse a guest access VLAN and assign selected ports |
| Camera / IoT VLAN | Create/reuse an access VLAN for camera/IoT ports |
| Server access ports | Create/reuse an untagged access VLAN for server ports |
| Switch uplink / trunk | Explicit native VLAN and finite allowed/tagged VLAN list |
| Disable unused ports | Administrative shutdown on selected ports |

These work across the existing switch drivers. Selected workspace ports are prechecked in the wizard; other editable ports may be checked as well. Routed/aggregated/unsupported ports are unavailable.

Access scenarios share the same Layer 2 primitives, with scenario-specific follow-up guidance. They preserve administrative state unless **Enable selected ports** is checked. Blank descriptions preserve current descriptions. STP, voice VLAN, PoE, speed and duplex are preserved. Existing VLANs are reused without renaming; new VLANs require a name.

Uplinks require explicit VLAN lists and already existing/staged VLANs. PortFast and BPDU Guard are disabled where the driver supports those settings. EXOS and JetStream use tagged memberships for the allowed list, so the native VLAN must be excluded there. Peer tagging and native VLANs must be checked separately.

**A guest VLAN is not a guest isolation policy.** Configure firewall isolation, wireless SSIDs, routing and DHCP separately. Camera/IoT access restrictions likewise require firewall policy. The unused-port scenario changes administrative state only, not PoE or VLAN membership.

## Draft behavior

- Existing draft entries are included in the final summary and CLI preview.
- Identical entries coalesce. Conflicting interface fields, VLAN names, IDs or duplicate route prefixes stop staging with an explanation.
- Errors leave the original draft unchanged. Cancel does not add changes, even after visiting the summary page.
- Back preserves settings within the same scenario. Switching scenarios resets the details form for that scenario.
- Unsupported scenarios are disabled. Discovery-only platforms cannot use managed provisioning.
- Router/firewall drafts generated by the wizard can be saved and reloaded with the existing draft controls. The saved file contains intent, not the wizard's UI state or credentials.
- Final deployment performs fresh discovery and revalidates the complete intent. Wizard validation never replaces deployment-time checks.

## Try a branch demo

1. Open **Routers / firewalls**, select **Fortinet FortiOS**, leave **Demo** selected, and connect.
2. Open **Provisioning wizard → Branch routing foundation**.
3. Choose LAN `port2`, address `10.20.0.1/24`, WAN `port1`, route `0.0.0.0/0`, and next hop `192.0.2.1`.
4. Optionally choose **Allow HTTPS (TCP 443)** and enable source NAT. Leave the starting identifier at `1000` in a fresh demo.
5. Continue to the summary and click **Add to draft**. Review provisioning in the workspace to apply to the simulator.

For a switch demo, connect to the simulated Cisco switch, select a port, open the wizard, choose **Guest VLAN — switch ports**, and enter VLAN `40` named `GUEST`. The summary explains that firewall isolation remains separate.

Tests exercise each available router scenario and every switch scenario across the simulated drivers, plus GUI navigation, invalid inputs, cancellation, conflicts and the staging-only boundary. Physical hardware qualification remains outstanding.
