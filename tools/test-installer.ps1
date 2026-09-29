param([string]$Installer = '')
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if (-not $Installer) { $Installer = Join-Path $projectRoot 'dist\NetworkProvisioningStudio-1.0.0rc1-Setup-x64.exe' }
$testRoot = Join-Path $projectRoot 'test-artifacts'
$installRoot = [IO.Path]::GetFullPath((Join-Path $testRoot 'installer-check'))
if (-not $installRoot.StartsWith($testRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid test install path.' }
$registryKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{C8EBB684-93E1-4972-9F82-E76EA6881F36}_is1'
$menuLink = Join-Path ([Environment]::GetFolderPath('Programs')) 'Network Provisioning Studio.lnk'
$desktopLink = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Network Provisioning Studio.lnk'
foreach ($existing in @($registryKey, $menuLink, $desktopLink, $installRoot)) {
    if (Test-Path -LiteralPath $existing) { throw "Refusing to overwrite an existing installation or shortcut: $existing" }
}
New-Item -ItemType Directory -Path $testRoot -Force | Out-Null
$report = Join-Path $testRoot 'installed-smoke.json'
$log = Join-Path $testRoot 'installer-test.log'
$uninstallLog = Join-Path $testRoot 'uninstaller-test.log'
$checks = [Collections.Generic.List[string]]::new()
try {
    $process = Start-Process -FilePath $Installer -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CURRENTUSER', "/DIR=`"$installRoot`"", '/TASKS=desktopicon', "/LOG=`"$log`"") -WindowStyle Hidden -PassThru -Wait
    if ($process.ExitCode -ne 0) { throw "Setup failed: $($process.ExitCode)" }
    $exe = Join-Path $installRoot 'NetworkProvisioningStudio.exe'
    if (-not (Test-Path -LiteralPath $exe)) { throw 'Installed executable missing.' }
    $registration = Get-ItemProperty -LiteralPath $registryKey
    if ([IO.Path]::GetFullPath($registration.InstallLocation).TrimEnd('\') -ne $installRoot) { throw 'Unexpected installation registration.' }
    $checks.Add('Per-user installation and uninstall registration')
    $shell = New-Object -ComObject WScript.Shell
    foreach ($link in @($menuLink, $desktopLink)) {
        if (-not (Test-Path -LiteralPath $link)) { throw "Missing shortcut: $link" }
        if ($shell.CreateShortcut($link).TargetPath -ne $exe) { throw "Incorrect shortcut target: $link" }
    }
    $checks.Add('Start menu and desktop shortcuts point to installed executable')
    $process = Start-Process -FilePath $exe -ArgumentList @('--smoke-test', "`"$report`"") -WindowStyle Hidden -PassThru -Wait
    if ($process.ExitCode -ne 0 -or -not (Get-Content -LiteralPath $report -Raw | ConvertFrom-Json).passed) { throw 'Installed application smoke test failed.' }
    $checks.Add('Installed runtime, icon, all discovery demos, API flows and GUI pages')
    # Reinstall over the same destination to verify the upgrade path.
    $process = Start-Process -FilePath $Installer -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CURRENTUSER', "/DIR=`"$installRoot`"", '/TASKS=desktopicon') -WindowStyle Hidden -PassThru -Wait
    if ($process.ExitCode -ne 0) { throw 'Reinstallation failed.' }
    $checks.Add('Reinstall over existing application')
} finally {
    $uninstaller = Join-Path $installRoot 'unins000.exe'
    if (Test-Path -LiteralPath $uninstaller) {
        $process = Start-Process -FilePath $uninstaller -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/LOG=`"$uninstallLog`"") -WindowStyle Hidden -PassThru -Wait
        if ($process.ExitCode -ne 0) { throw "Uninstall failed: $($process.ExitCode)" }
    }
}
foreach ($removed in @($registryKey, $menuLink, $desktopLink, (Join-Path $installRoot 'NetworkProvisioningStudio.exe'))) {
    if (Test-Path -LiteralPath $removed) { throw "Uninstall left an application component: $removed" }
}
$checks.Add('Uninstall removes executable, registration and both shortcuts')
@{ passed = $true; checks = @($checks); installer = [IO.Path]::GetFileName($Installer); hardware_tested = $false } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $testRoot 'installer-report.json') -Encoding utf8
Write-Host 'Installer lifecycle checks passed.'
