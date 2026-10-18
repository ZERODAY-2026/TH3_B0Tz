<#
.SYNOPSIS
  Layer 2 of the privacy proof on Windows: watch every TCP/UDP endpoint owned
  by the LegalLens process and by llama-server while a full analysis runs.

.DESCRIPTION
  Starts `python -m privacy.capture` (which itself records every connection
  attempt through Python audit hooks), then polls Get-NetTCPConnection and
  Get-NetUDPEndpoint for both process IDs until the run ends. Writes
  connections.csv and monitor_summary.json to -Out. Exit code 0 only if the
  capture passed and no connection to a non-loopback address was seen.

  Polling can miss a connection shorter than the interval; the in-process
  audit hook cannot, which is why both layers run together.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File privacy\monitor.ps1 -ServerLog E:\tools\llama-server.log
#>
param(
    [string]$File = "data/samples/privacy_canary.txt",
    [string]$Canary = "QZX-CANARY-41907",
    [string]$Out = "docs/examples/privacy/run-monitored",
    [string]$ServerLog = "",
    [ValidateSet("record", "block")][string]$Mode = "block",
    [int]$IntervalMs = 200
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
New-Item -ItemType Directory -Force -Path $Out | Out-Null

$server = Get-Process llama-server -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $server) {
    Write-Host "llama-server is not running. Start it on 127.0.0.1:8080 first (docs/MODEL_SETUP.md)."
    exit 3
}

function Test-Loopback([string]$addr) {
    return ($addr -like "127.*") -or ($addr -eq "::1") -or ($addr -eq "0.0.0.0") -or ($addr -eq "::")
}

$env:GEMMA_TIMEOUT = "900"
$env:PYTHONIOENCODING = "utf-8"
$pyArgs = @("-m", "privacy.capture", "--file", $File, "--out", $Out, "--mode", $Mode, "--canary", $Canary)
if ($ServerLog) { $pyArgs += @("--server-log", "`"$ServerLog`"") }

$started = Get-Date
$py = Start-Process -FilePath "python" -ArgumentList $pyArgs -NoNewWindow -PassThru `
    -RedirectStandardOutput "$Out/capture_stdout.txt" -RedirectStandardError "$Out/capture_stderr.txt"
$null = $py.Handle   # cache the handle now, or ExitCode reads as null after exit
$names = @{ $py.Id = "python (LegalLens)"; $server.Id = "llama-server" }

$seen = @{}
$rows = New-Object System.Collections.Generic.List[object]
$samples = 0
while (-not $py.HasExited) {
    $ids = @($py.Id, $server.Id)
    $tcp = @(Get-NetTCPConnection -ErrorAction SilentlyContinue | Where-Object { $ids -contains $_.OwningProcess })
    $udp = @(Get-NetUDPEndpoint -ErrorAction SilentlyContinue | Where-Object { $ids -contains $_.OwningProcess })
    foreach ($c in $tcp) {
        $remote = "$($c.RemoteAddress):$($c.RemotePort)"
        $key = "tcp|$($c.OwningProcess)|$($c.LocalAddress):$($c.LocalPort)|$remote|$($c.State)"
        if (-not $seen.ContainsKey($key)) {
            $seen[$key] = 1
            $rows.Add([pscustomobject]@{
                first_seen = (Get-Date).ToString("HH:mm:ss.fff"); proto = "tcp"; process = $names[[int]$c.OwningProcess]
                local = "$($c.LocalAddress):$($c.LocalPort)"; remote = $remote; state = "$($c.State)"
                loopback = (Test-Loopback "$($c.RemoteAddress)") -and (Test-Loopback "$($c.LocalAddress)")
            })
        }
    }
    foreach ($u in $udp) {
        $key = "udp|$($u.OwningProcess)|$($u.LocalAddress):$($u.LocalPort)"
        if (-not $seen.ContainsKey($key)) {
            $seen[$key] = 1
            $rows.Add([pscustomobject]@{
                first_seen = (Get-Date).ToString("HH:mm:ss.fff"); proto = "udp"; process = $names[[int]$u.OwningProcess]
                local = "$($u.LocalAddress):$($u.LocalPort)"; remote = "-"; state = "bound"
                loopback = (Test-Loopback "$($u.LocalAddress)")
            })
        }
    }
    $samples++
    Start-Sleep -Milliseconds $IntervalMs
}
$py.WaitForExit()
$elapsed = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)

$rows | Export-Csv -NoTypeInformation -Encoding UTF8 -Path "$Out/connections.csv"
$outside = @($rows | Where-Object { -not $_.loopback })
$captureOk = ($py.ExitCode -eq 0)
$verdict = if ($captureOk -and $outside.Count -eq 0) { "PASS" } else { "FAIL" }
$summary = [ordered]@{
    started            = $started.ToString("yyyy-MM-dd HH:mm:ss")
    duration_s         = $elapsed
    poll_interval_ms   = $IntervalMs
    samples            = $samples
    watched            = @("python (LegalLens) pid $($py.Id)", "llama-server pid $($server.Id)")
    endpoints_seen     = $rows.Count
    non_loopback       = @($outside | ForEach-Object { "$($_.proto) $($_.process) $($_.local) -> $($_.remote) $($_.state)" })
    capture_exit_code  = $py.ExitCode
    verdict            = $verdict
}
$summary | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 -Path "$Out/monitor_summary.json"

Get-Content "$Out/capture_stdout.txt"
Write-Host "monitor: $samples samples over $elapsed s, $($rows.Count) endpoint(s) seen, $($outside.Count) non-loopback"
Write-Host "overall: $verdict  (evidence in $Out)"
if ($verdict -eq "PASS") { exit 0 } else { exit 1 }
