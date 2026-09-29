param([string]$Compiler = '', [switch]$SkipBuild)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not $SkipBuild) {
    & "$PSScriptRoot\build-release.ps1"
    if ($LASTEXITCODE -ne 0) { throw 'Portable release build failed.' }
}
if (-not $Compiler) {
    $candidates = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")
    $Compiler = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $Compiler) { throw 'Install Inno Setup 6, or supply -Compiler with the path to ISCC.exe.' }
$releaseVersion = & '.\.venv\Scripts\python.exe' -c 'from switch_configurator import __version__; print(__version__)'
if ($LASTEXITCODE -ne 0) { throw 'Could not read application version.' }
$smokeReport = Get-Content -LiteralPath '.\dist\NetworkProvisioningStudio\smoke-report.json' -Raw | ConvertFrom-Json
if (-not $smokeReport.passed -or $smokeReport.version -ne $releaseVersion) { throw 'A verified portable build of this version is required.' }
& $Compiler "/DAppVersion=$releaseVersion" '.\installer\NetworkProvisioningStudio.iss'
if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }
$installerFile = Join-Path $PSScriptRoot "dist\NetworkProvisioningStudio-$releaseVersion-Setup-x64.exe"
$installerHash = (Get-FileHash -LiteralPath $installerFile -Algorithm SHA256).Hash.ToLower()
"$installerHash  $([System.IO.Path]::GetFileName($installerFile))" | Set-Content -LiteralPath "$installerFile.sha256" -Encoding ascii
Write-Host "Installer created: $installerFile"
