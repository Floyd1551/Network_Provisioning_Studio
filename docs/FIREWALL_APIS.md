# Native firewall APIs — 0.6

The **Firewall APIs** tab provides an initial, bounded access-rule provisioning workflow. All three adapters have synthetic API tests and demos. None has been tested against physical equipment or a vendor virtual appliance.

## Connection and review

1. Select the exact platform. **Demo** uses only an in-memory simulator.
2. For **HTTPS API**, enter the endpoint and credentials locally. Certificates are verified; supply a trusted CA PEM file when the appliance uses your private CA. Redirects, certificate bypass and automatic mutation retries are disabled.
3. Discover existing policy objects. Add rules referencing those objects. New rules are placed at the end: existing cleanup/drop rules can shadow them. No rules are deleted or reordered.
4. Save/load a draft if needed. Drafts contain policy intent and scope, not login credentials. Loading checks the connected platform and scope, then revalidates object references.
5. Review the target, warnings and native HTTP/XML/JSON payloads. Apply requires the review checkbox. The app rediscovers the target, rejects stale plans, creates scope backups and journals operations before deployment.
6. Commit/publish/install acknowledgement and rule readback must succeed. This confirms configuration fields, not forwarding or effective access policy.

Saved devices support HTTPS endpoints, CA files and scope settings. Changing connection fields disables staging until reconnect. PAN-OS uses the password/key slot in Windows Credential Manager for its API key.

## Platform scope

| Platform | Authentication | Implemented transaction | Restrictions |
| --- | --- | --- | --- |
| SonicOS 7 | API-enabled administrator, HTTP Basic over verified HTTPS | Create IPv4 access rules; inspect pending changes; commit; read back | Existing zones, IPv4 address objects and service objects only |
| PAN-OS 10–12 PA-series / PA-VM | API key plus its owning administrator name | Acquire config/commit locks; require clean candidate; stage local-vsys rules; partial administrator commit; poll job; read back | Existing local objects and layer-3 zones; Panorama and enabled HA are rejected |
| Check Point Management API | Management administrator password; optional domain | Fresh isolated session; add rules; publish and wait; install Access Control policy to explicit target and wait; read back | One flat access layer, standalone simple gateway, existing host/network and TCP/UDP objects |

**Check Point installs the entire published policy package**, including earlier published changes from other administrators. Review that package before approving installation. Threat Prevention, QoS and Desktop Security installation are disabled in this workflow. Sections, inline layers, clusters and multi-layer packages are rejected.

PAN-OS requires a dedicated API administrator and the correct administrator name for partial commits. The rules use `application=any` with the selected service object; application-based policy design and security profiles are not supplied by this form. Commit locks are released only when this adapter acquired them. Unexpected changes elsewhere in the candidate block the commit.

SonicOS must allow the selected API authentication method. The adapter does not enable the API, force another administrator out of configuration mode, or discard existing pending changes. Logout is skipped when pending state is dirty or cannot be confirmed clean, because SonicOS logout may discard pending changes.

## Limits and evidence

- API work creates access rules only. Address/service object creation, NAT, interface provisioning and VPN through these APIs are not implemented. Other workspaces retain their own capabilities.
- No 2FA login flow is implemented. Configure an appropriately restricted API account according to the platform's administration requirements.
- API backups contain the discovered scopes. PAN-OS includes its configuration XML; SonicOS and Check Point store selected policy/object scopes. These are not full appliance/server recovery images and may contain sensitive configuration.
- Failure or timeout can leave candidates, published policy or partial installation. The app reports failure and preserves evidence; it does not automatically retry writes or roll back. Phase 5 remains deferred.
- Check Point uses fresh sessions for preview/apply to see newly published changes. Publishing is scoped to the app's session. Installation uses the current published package; simultaneous administrative work still requires operational coordination.
- API requests run in background workers. Commit/install polling is bounded and requires the returned job/task identity and a successful terminal result.

## Primary references

- [SonicOS 7 OpenAPI schema](https://sonicos-api.sonicwall.com/sonicos_files/default/sonicos_openapi.yml)
- [PAN-OS configuration API](https://docs.paloaltonetworks.com/ngfw/api/pan-os-xml-api-request-types-and-actions/configuration-api)
- [PAN-OS commits and jobs](https://docs.paloaltonetworks.com/ngfw/api/pan-os-xml-api-request-types-and-actions/commit)
- [PAN-OS API authentication](https://docs.paloaltonetworks.com/ngfw/api/api-authentication-and-security)
- [Check Point official Management SDK](https://github.com/CheckPointSW/cp_mgmt_api_python_sdk)
- [Check Point policy installation schema](https://github.com/CheckPointSW/terraform-provider-checkpoint/blob/master/website/docs/r/checkpoint_management_install_policy.html.markdown)
