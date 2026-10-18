<#
.SYNOPSIS
  Layer 1 of the privacy proof on Windows: run the full analysis with the
  machine offline, and keep the evidence.

.DESCRIPTION
  1. Turn on Airplane mode (or disable every network adapter). Keep
     llama-server running: it listens on 127.0.0.1, which still works offline.
  2. Run:  powershell -ExecutionPolicy Bypass -File privacy\run_offline.ps1
  The script refuses to start while the machine can still reach the
  internet, saves the network state before and after, and runs the same
  monitored capture as monitor.ps1 (audit-hook guard in block mode + OS
  connection polling + canary leak check). Evidence lands in -Out.
#>
param(
    [string]$File = "data/samples/privacy_canary.txt",
    [string]$Canary = "QZX-CANARY-41907",
    [string]$Out = "docs/examples/privacy/run-offline",
    [string]$ServerLog = ""
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
New-Item -ItemType Directory -Force -Path $Out | Out-Null

function Save-NetworkState([string]$path) {
    $lines = @("# Network state at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')", "", "## Adapters")
    $lines += (Get-NetAdapter -ErrorAction SilentlyContinue | Select-Object Name, InterfaceDescription, Status, MediaConnectionState | Format-Table -AutoSize | Out-String).Trim()
    $lines += @("", "## Connection profiles")
    $lines += (Get-NetConnectionProfile -ErrorAction SilentlyContinue | Select-Object Name, InterfaceAlias, IPv4Connectivity, IPv6Connectivity | Format-Table -AutoSize | Out-String).Trim()
    $lines += @("", "## Default routes")
    $lines += (Get-NetRoute -DestinationPrefix "0.0.0.0/0", "::/0" -ErrorAction SilentlyContinue | Select-Object InterfaceAlias, DestinationPrefix, NextHop | Format-Table -AutoSize | Out-String).Trim()
    $lines | Set-Content -Encoding UTF8 -Path $path
}

function Test-Online {
    $internet = @(Get-NetConnectionProfile -ErrorAction SilentlyContinue |
        Where-Object { $_.IPv4Connectivity -eq "Internet" -or $_.IPv6Connectivity -eq "Internet" })
    $routes = @(Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue)
    return ($internet.Count -gt 0) -or ($routes.Count -gt 0)
}

Save-NetworkState "$Out/network_state_before.txt"
if (Test-Online) {
    Write-Host "This computer can still reach the internet (see $Out/network_state_before.txt)."
    Write-Host "Turn on Airplane mode or disable every network adapter, keep llama-server running, and run this script again."
    exit 2
}
Write-Host "Offline confirmed. Running the full analysis with no network..."

$monArgs = @{ File = $File; Canary = $Canary; Out = $Out; Mode = "block" }
if ($ServerLog) { $monArgs.ServerLog = $ServerLog }
& "$PSScriptRoot\monitor.ps1" @monArgs
$code = $LASTEXITCODE

Save-NetworkState "$Out/network_state_after.txt"
if (Test-Online) { Write-Host "Warning: the network came back during the run; the offline claim does not hold for this run." ; $code = 1 }
Write-Host "offline run: $(if ($code -eq 0) { 'PASS' } else { 'FAIL' })  (evidence in $Out)"
exit $code
