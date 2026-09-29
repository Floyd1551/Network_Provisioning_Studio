# Network Provisioning Studio 1.0 RC1

**Windows installer:** run `NetworkProvisioningStudio-1.0.0rc1-Setup-x64.exe` for a per-user installation with an app icon, Start menu entry, optional desktop shortcut and uninstall support. No Python installation or administrator rights required. Saved devices and backups survive uninstall.

**Portable Windows release:** extract the release ZIP and run `NetworkProvisioningStudio.exe`. No Python installation is needed for the packaged app. See [installation, upgrades and release limitations](docs/RELEASE.md). This release candidate is ready for local review and lab qualification; physical-device validation remains pending and automatic recovery is deferred.

A Windows desktop MVP using Python, PySide6, pySerial and SQLite. The GUI edits a vendor-neutral configuration model; platform-specific drivers create native CLI; a serial transport exchanges commands with the switch. Stateful demos exercise each supported platform without hardware. See [supported platforms and limitations](docs/SUPPORTED_PLATFORMS.md).

Version 0.3 adds a **Routers / firewalls** workspace with SSH connections, static IPv4 interface addressing, static routes, platform-specific traffic rules, FortiOS policy source NAT, RouterOS masquerade, reusable provisioning drafts, native CLI review, backups and readback verification. The existing switch workspace remains available. The installed executable retains its original `switch-configurator.exe` name.

Version 0.4 adds a **Provisioning wizard** in both workspaces. It guides you through scenario selection, settings and a combined draft summary. Twelve scenarios cover branch routing, outbound/service access, routed LANs, static routes, source NAT, access VLANs, guest/camera/server ports, uplinks and unused ports. Unsupported scenarios are disabled. Finish stages changes; the existing review/apply workflow still performs fresh discovery, backups and verification. See [wizard scenarios and examples](docs/PROVISIONING_WIZARD.md).

The current development build also includes **Saved devices**: searchable inventory by site/role/model/firmware, optional Windows Credential Manager storage, and connection loading for switch SSH/serial and router SSH. Loading a profile does not connect or deploy. Use **Capture connected device lab evidence** to refresh and save discovery observations. Captures retain configuration secrets and explicitly distinguish demos from live discovery; neither certifies provisioning. See [hardware validation](docs/HARDWARE_VALIDATION.md) and the [requested phase status](docs/IMPLEMENTATION_STATUS.md).

**Coverage is feature-specific, not universal.** Cisco IOS/IOS-XE, Fortinet FortiOS, Juniper Junos/SRX, Aruba AOS-CX and MikroTik RouterOS have managed CLI provisioning features. The **Firewall APIs** workspace adds bounded access-rule provisioning for Palo Alto PAN-OS, Check Point Management and SonicWall SonicOS. Their SSH adapters remain discovery-only. All adapters are experimental and hardware-untested. See the [router/firewall matrix](docs/ROUTER_FIREWALL.md) and [API workflow and restrictions](docs/FIREWALL_APIS.md) before connecting hardware.

Version 0.5 added **Network services**: seven IOS/IOS-XE scenarios for DNS, NTP, DHCP, IPv6 addressing/static routes, OSPFv2 and existing VLAN interface IPv4; Junos supports DNS/NTP. Version 0.6 adds a RouterOS WireGuard interface/peer/route scenario and the three native firewall API adapters. API drafts can be saved, loaded and reviewed with explicit target and policy scope. Services use native review, backups and configuration readback. See [network services](docs/NETWORK_SERVICES.md).

## Run

From PowerShell in this directory, with Python 3.11+ installed:

```powershell
.\setup.ps1
.\run.ps1
```

If Python is not on PATH, use `./setup.ps1 -Python 'C:\path\to\python.exe'`. Setup creates a project-local `.venv`. Once installed, `.venv\Scripts\switch-configurator.exe` also launches the application. No web service or account is needed.

For the existing installation, close and reopen the app to load these source updates. If PowerShell blocks `.ps1` scripts, launch the executable directly without changing execution policy:

```powershell
& 'C:\Users\floyd\Development Projects\visual-switch-configurator\.venv\Scripts\switch-configurator.exe'
```

## Try the demo

For routing/firewall provisioning, open **Routers / firewalls**, choose a platform, leave **Demo** selected and click **Connect router / firewall**. Use the forms to stage changes, then **Review provisioning**. You can save a draft for reuse on the same platform; each new target is rediscovered and validated before application.

For a guided example, click **Provisioning wizard**, choose **Branch routing foundation**, enter a LAN address and WAN next hop, and select any supported traffic/NAT options. For switches, select ports and click **Provisioning wizard** to create an access VLAN, trunk or disabled-port draft.

1. Select **Simulated switch · demo**, choose a **Platform**, then **Connect**. Auto uses the Cisco demo; each other platform has its own two-port demonstration.
2. Click, Ctrl-click, Shift-click or drag over ports. Right-click or choose **Configure selection**.
3. Check only the fields you want to change, or load a profile. VLAN IDs remain an explicit per-network choice. Create a VLAN before referencing a new ID.
4. Stage edits, then **Review and apply**. Inspect the native commands, modeled diff and full current configuration.
5. Approve the displayed commands. The app captures a backup, deploys, reads state back and compares each requested field. See **Console / activity** and **Backups / history** for evidence.

## Connect a real switch

- Install the USB-console adapter driver; close other programs using the COM port.
- Select the discovered COM port and baud rate (9600 by default; 8N1, no flow control).
- If necessary, use **Raw console** to log in and enter enable mode. Input is hidden by default for credentials. This is an unrestricted manual terminal, with Enter, Ctrl+C, Ctrl+Z and paging-space controls. It is a simple streaming console, not a full VT emulator.
- Leave the device at its privileged `hostname#` prompt, Junos operational `user@hostname>` prompt, or EXOS command prompt. Close the raw console, select the platform (or Auto), then **Connect**. The app verifies the OS identity before disabling paging and reading configuration/status. An unknown OS is never treated as Cisco.
- Command support varies by OS family and release. This build has been tested with synthetic fixtures, simulation and scripted serial responses, **not physical switches**. The new drivers are experimental; qualify the exact model and firmware in a lab before operational deployment.

## Implemented scope

- COM discovery; serial connection; model/version identification; raw inventory and stack-member evidence.
- Running-config, VLAN, physical-interface and link-state parsing; optional PoE and CDP neighbor discovery.
- Inferred port layout, VLAN/state sorting, search, inspector, multi-selection, right-click editing and pending-change markers.
- Every platform: description, administrative state, access/trunk intent, access/native/allowed VLANs and VLAN creation, subject to the platform restrictions below.
- Cisco IOS/IOS-XE also retains voice VLAN, PoE auto/never, speed, duplex, PortFast and BPDU Guard. Arista EOS also supports PortFast and BPDU Guard. Unsupported fields are disabled; loading a profile reports skipped fields.
- VLAN renaming where supported (excluded on Junos and EXOS); built-in role profiles and custom SQLite profiles.
- CLI preview/copy, modeled field diff, current snapshot, before/after backups, command journal, verification and local history.
- Managed read-only command panel plus an exclusive raw serial terminal for login and manual work.

The GUI excludes routed ports, EtherChannel members and template-derived interfaces from bulk editing. Optional command failures are surfaced. Physical placement is inferred from interface names, not a calibrated chassis image. Inventory/stack data is retained as raw evidence, not a full modular chassis model.

## Deployment guarantees and limits

- Only selected intent is sent; changing mode or VLAN membership can require related native/access/tagged membership commands. Review the full CLI. Input is validated before CLI generation; interface identifiers must come from discovery.
- Preview refreshes state. Apply re-reads configuration and stops if it differs from the reviewed snapshot. Avoid concurrent administrators. Junos additionally locks the candidate exclusively and checks active configuration again under that lock.
- Backups and intent must be written before configuration commands begin. Commands/responses are journaled as they execute. CLI errors stop further configuration; after-state collection is attempted.
- Verification compares requested fields against a fresh parsed configuration and reports selected ports in error/inactive states. It does not prove end-to-end connectivity or that a disconnected port will establish a link. Unsupported or incomplete required discovery fails closed.
- Most platforms apply commands sequentially; failures can leave partial changes. Full original configuration is retained for operator-led recovery. Junos uses a candidate, requires a clean candidate, and runs `commit check` then `commit`; cleanup discards only this session's uncommitted edits. There is no automatic rollback of committed changes.
- Parser defaults represent common IOS defaults, not every platform's effective behavior. Global inherited STP settings, advanced PoE options, templates and unusual interface syntax need further platform-specific qualification.
- **Junos changes are committed and persist across reboot.** Other drivers change running configuration only; saving startup configuration is a manual operator action via raw console. The review dialog explains this distinction. No reload is performed.
- Raw console deliberately bypasses managed deployment safeguards. Opening it disconnects managed access and clears staged changes; reconnect to discover state afterward. Raw output is not persisted, but may contain credentials echoed by the device.
- Backups and history live under `%LOCALAPPDATA%\VisualSwitchConfigurator`. Configuration may contain secrets. Files are plaintext and inherit the local user's directory permissions.

## Architecture

```text
app.py          Qt views, selection, field editor, review dialog, async workers
model.py        Device/port/changeset model, profiles, validation
driver.py       Cisco IOS parsing, CLI generation, verification
vendors/        OS registry, native parsers, capabilities and command generation
samples.py      Synthetic native CLI fixtures (not captured hardware output)
vendor_demo.py  Stateful demonstrations for the additional platforms
service.py      Discover → preview → backup → apply → verify orchestration
transport.py    Transport protocol, pySerial implementation, stateful simulator
terminal.py     Exclusive raw serial console
storage.py      SQLite profiles/history and filesystem backup journal
provisioning/   Router/firewall models, native drivers, SSH, demos and Qt workspace
```

Network I/O runs in worker threads. Only one managed operation owns the transport at a time. Vendor logic has no dependency on Qt or serial I/O, so future vendor/SSH/NETCONF implementations can use the same UI model.

## Verification

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tests cover discovery, multi-port apply/readback, command injection, VLAN validation, stale previews, disk failures, partial deployments, silently ignored commands, profiles, parser behavior, pagination and fragmented serial prompts. Additional tests exercise every new driver, native command syntax, additive VLAN removal, unsupported OS rejection, Junos candidate ownership and positive commit-check acknowledgement. Qt offscreen tests exercise platform selection, disabled controls and the review/apply workflow, and render UI images. These tests do not constitute hardware qualification.

## Next milestones

Hardware fixture captures across supported OS families and releases; managed policy deployment for PAN-OS, Check Point and SonicOS; IPv6, dynamic routing, VPN, DHCP, DNS/NTP and advanced firewall inspection; accurate chassis/module templates; durable rollback; SSH in the Layer 2 switch workspace; a signed Windows installer. These remain outside this release. Router/firewall SSH, standalone routed IPv4 addressing and static routes are implemented within the documented per-platform limits.

Command reference used for STP behavior: [Cisco PortFast and BPDU Guard](https://www.cisco.com/c/en/us/support/docs/lan-switching/spanning-tree-protocol/10586-65.html), [Cisco IOS-XE layer 2 commands](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-9/command_reference/b_179_9300_cr/layer_2_3_commands.html).
