# Requested phase status

The feature set is frozen for **1.0.0rc1**. A portable Windows package, dependency manifest, offline executable smoke check and initial interface polish have been added. See [release acceptance and deployment](RELEASE.md). Physical qualification and phase 5 are not implied by the release candidate version.

This status distinguishes implemented software from physical device qualification.

| Phase | Status |
| --- | --- |
| 1 — Vendor provisioning | Initial native access-rule provisioning implemented for PAN-OS, Check Point Management and SonicOS, with platform-specific transactions and simulated API tests. Existing-object and policy-scope limits apply; see FIREWALL_APIS.md. Hardware qualification remains pending. |
| 2 — Hardware validation | Read-only evidence capture implemented. All physical validation pending; Cisco 3750X-48 at home is the intended first lab device, firmware unknown. |
| 3 — Saved inventory and secure credentials | Implemented: searchable site/role metadata, Windows Credential Manager, switch/router SSH, switch serial and firewall HTTPS profiles. PAN-OS vsys and Check Point domain/layer/package/gateway scope can be saved. |
| 4 — Provisioning scenarios | Existing 12 guided scenarios implemented; see PROVISIONING_WIZARD.md. |
| 5 — Recovery | Deferred at the user's request. |
| 6 — Network services | Initial coverage: IOS/IOS-XE DNS, NTP, DHCP pools, IPv6 addresses/static routes, existing SVI IPv4 and new single-interface OSPFv2; Junos DNS/NTP; RouterOS WireGuard interface/peer/route. Native review, backups and readback implemented. SVI creation, IPsec/OpenVPN, broader routing protocols and service coverage on other platforms remain future work. |

Saved SSH credentials are associated with a profile. Changing its platform, host, port, username or transport without replacement credentials removes its stored credentials. Stale loaded switch endpoints must be reloaded before connecting. Passwords are not stored in the inventory database; device configuration backups may contain device secrets.
