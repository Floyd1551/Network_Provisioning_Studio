# Hardware validation

No physical device has been tested. Automated fixtures and demos are synthetic.

The first intended lab device is the user's Cisco Catalyst 3750X-48 at home. Its exact SKU, IOS version, license and stack configuration are unknown. Do not infer routing or service support from the model family alone.

## Capture workflow

1. Connect using the switch workspace, selecting Cisco IOS. Use serial or a saved SSH profile with a verified host key.
2. Open **Saved devices → Capture connected device lab evidence**. Select the session. The app refreshes discovery before recording it; this does not deploy configuration.
3. Find the report under `%LOCALAPPDATA%\VisualSwitchConfigurator\lab-evidence`. It includes the model, version, raw command responses, configuration and SHA-256 digest. Simulator reports are labeled simulation and never count as hardware testing.
4. Review the files before sharing: configuration and raw discovery can contain secrets.

A live discovery capture is evidence of discovery only. Provisioning remains unvalidated until an isolated lab scenario is reviewed, applied, read back and independently observed on that exact model and firmware.

## Initial 3750X lab record

| Check | Current status |
| --- | --- |
| Exact model / IOS / license / stack membership | Unknown |
| Serial discovery | Not tested |
| SSH discovery with verified host key | Not tested |
| Port/VLAN discovery matches physical inventory | Not tested |
| Access-port scenario on an unused lab port | Not tested |
| Trunk scenario with explicit allowed VLANs | Not tested |
| Configuration readback and independent traffic observation | Not tested |
| Startup configuration persistence | Not tested; saving remains manual |

Record deployment history paths and independent observations per scenario. A successful app readback confirms modeled configuration fields, not end-to-end traffic behavior. Phase 5 recovery work remains deferred.
