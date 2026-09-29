# Third-party runtime notices

This application uses Python, Qt/PySide6, pySerial, Netmiko and their dependencies. The portable build records exact versions in `build-manifest.json` and copies available distribution license files to `third-party-licenses`. Additional pySerial and Qt open-source license texts accompany this file because their installed wheel metadata did not include those texts.

Qt/PySide6 is provided under its applicable open-source license options. Its DLLs remain separate in `_internal` and may be replaced with compatible modified builds. This application imposes no restriction on modifying those libraries or reverse engineering for debugging such modifications.

Corresponding upstream source and notices:

- Qt 6.11.2: https://download.qt.io/archive/qt/6.11/6.11.2/submodules/ and https://code.qt.io/cgit/qt/qtbase.git/tree/?h=v6.11.2
- PySide6/shiboken 6.11.2: https://code.qt.io/cgit/pyside/pyside-setup.git/tree/?h=v6.11.2
- Python: https://www.python.org/downloads/source/ (exact version in the manifest)
- pySerial 3.5: https://github.com/pyserial/pyserial/tree/v3.5
- Netmiko: https://github.com/ktbyers/netmiko (exact version in the manifest)

Each dependency retains its own copyright and license. Build-tool entries in the manifest describe the build environment; they do not necessarily indicate included runtime code.
