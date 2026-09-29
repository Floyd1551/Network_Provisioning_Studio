# Windows deployment — v1.0 release candidate 1

## Install and launch

1. Extract the entire `NetworkProvisioningStudio-1.0.0rc1-windows-x64.zip` archive into a writable folder.
2. Open the extracted `NetworkProvisioningStudio` folder.
3. Run `NetworkProvisioningStudio.exe`. Keep `_internal` alongside the executable.

Python, a web server and administrator rights are not required. This is a portable x64 Windows build, not an installer. The executable is unsigned; organizational application controls may require approval. USB serial adapters still require their manufacturer's driver.

Start in Demo mode. The three configuration workspaces are **Switch workspace**, **Routers / firewalls** and **Firewall APIs**. Use a provisioning wizard or a settings form to stage changes, review the native commands/payloads, then approve application. Demo sessions never connect to hardware.

## Data and upgrades

User data stays in `%LOCALAPPDATA%\VisualSwitchConfigurator`, outside the release folder. Saved passwords remain in Windows Credential Manager. Configuration backups can contain device secrets. Protect the data folder and review backups before sharing them.

Close the app before upgrading. Back up the data folder, extract a new release into a separate directory, then launch its executable. Do not copy individual DLLs or executables between release folders. Removing the release folder does not delete saved data or credentials. Credentials must be removed with **Forget credentials** in Saved devices while the profile is still present.

## Release scope

- Eight switch platform drivers, five managed router/firewall CLI platforms, three firewall API rule adapters, and three additional discovery-only SSH adapters.
- Twelve provisioning wizard scenarios, saved inventory and optional secure credentials, native review, configuration backups, readback verification and bounded network service scenarios.
- Initial interface cleanup: consistent release branding, workflow guidance, focus/hover feedback, table styling and empty-state help.
- Platform support is feature-specific; consult the platform, router/firewall, network-services and firewall-API documents before connecting devices.

**This is a software release candidate for local review and lab qualification. It is not a hardware-qualified production release.** No physical devices have been tested. Cisco 3750X-48 is the intended first qualification target; its exact firmware, SKU and license still need recording. Recovery/rollback (phase 5) remains deferred. Failed or partially applied configurations require manual inspection and recovery.

## Verification and rebuild

The source test suite covers parsers, scenario planning, transaction guards, simulated deployment/readback, credential handling and GUI workflows. The build script stops on any test failure. The packaged executable then runs an isolated offline smoke check: all 16 switch/router discovery demos, all three API deploy/readback demos, real transport imports and all seven GUI pages. `smoke-report.json` records the result; no user data or network endpoint is used.

Rebuild from the source folder with Python 3.11+ and a project virtual environment:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build-release.ps1
```

This invocation changes execution policy only for that process. `requirements-build.txt` pins the tested dependency set. `build-manifest.json` records the actual Python/platform/package versions. The ZIP is accompanied by a SHA-256 file. The build includes dependency license files under `third-party-licenses`; these dependencies retain their own licenses. Packaging uses [PyInstaller's folder bundle](https://pyinstaller.org/en/stable/operating-mode.html).

The package has been checked on the build machine. A clean Windows machine check, signing/installer decisions and exact-device qualification remain release acceptance work.
