param([string]$Python = "$PSScriptRoot\.venv\Scripts\python.exe")
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& $Python -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Build dependency installation failed.' }
& $Python -m pip install --no-deps -e .
if ($LASTEXITCODE -ne 0) { throw 'Application installation failed.' }
& $Python -m unittest discover -s tests
if ($LASTEXITCODE -ne 0) { throw 'Tests failed; release stopped.' }
& $Python tools/package_release.py
if ($LASTEXITCODE -ne 0) { throw 'Packaging or standalone smoke check failed.' }
