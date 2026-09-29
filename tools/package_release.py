"""Build, verify and zip a portable Windows release from the current environment."""
import hashlib
import importlib.metadata as metadata
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from switch_configurator import __version__

root = Path(__file__).resolve().parents[1]
name = "NetworkProvisioningStudio"
if sys.platform != "win32":
    raise SystemExit("Build the Windows release on Windows.")
subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed", "--noupx",
                "--name", name, "--paths", str(root / "src"), "--specpath", str(root / "build"),
                "--icon", str(root / "src/switch_configurator/assets/app.ico"),
                "--add-data", str(root / "src/switch_configurator/assets") + ";switch_configurator/assets",
                "--collect-submodules", "netmiko", "--copy-metadata", "netmiko", str(root / "launcher.py")], cwd=root, check=True)
folder = root / "dist" / name
shutil.copytree(root / "docs", folder / "docs", dirs_exist_ok=True)
shutil.copy2(root / "README.md", folder / "README.md")
shutil.copy2(root / "requirements-build.txt", folder / "requirements-build.txt")
licenses = folder / "third-party-licenses"
licenses.mkdir(exist_ok=True)
shutil.copy2(Path(sys.base_prefix) / "LICENSE.txt", licenses / "Python-LICENSE.txt")
shutil.copy2(root / "docs" / "third-party" / "pyserial-LICENSE.txt", licenses / "pyserial-LICENSE.txt")
packages = []
for dist in metadata.distributions():
    package = dist.metadata["Name"]
    packages.append({"name": package, "version": dist.version, "license": dist.metadata.get("License-Expression") or dist.metadata.get("License", "See bundled license")})
    for file in dist.files or []:
        if ".." not in file.parts and any(part.lower().startswith(("license", "copying", "notice")) for part in file.parts):
            source = Path(dist.locate_file(file))
            if source.is_file():
                target = licenses / package / Path(*file.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
(folder / "build-manifest.json").write_text(json.dumps({"version": __version__, "python": sys.version, "platform": platform.platform(), "packages": sorted(packages, key=lambda p: p["name"].lower()), "hardware_qualified": False}, indent=2), encoding="utf-8")
report = folder / "smoke-report.json"
report.unlink(missing_ok=True)
subprocess.run([str(folder / (name + ".exe")), "--smoke-test", str(report)], cwd=folder, check=True, timeout=180)
if not json.loads(report.read_text(encoding="utf-8"))["passed"]:
    raise SystemExit("Packaged smoke check failed.")
archive = Path(shutil.make_archive(str(root / "dist" / f"{name}-{__version__}-windows-x64"), "zip", root / "dist", name))
digest = hashlib.file_digest(archive.open("rb"), "sha256").hexdigest()
archive.with_suffix(".zip.sha256").write_text(digest + "  " + archive.name + "\n", encoding="ascii")
print(f"Verified portable release: {archive}")
