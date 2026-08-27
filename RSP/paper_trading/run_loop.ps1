# RSP - paper_trading/run_loop.ps1
#
# Runs the paper-trading validation cycle every 15 minutes (matching the
# 15M base candle close). It only calls runner.py - no parameter is ever
# changed here.
#
# Usage (from the project root, arsan.1):
#   powershell -ExecutionPolicy Bypass -File RSP\paper_trading\run_loop.ps1
#   or with other coins:
#   powershell -ExecutionPolicy Bypass -File RSP\paper_trading\run_loop.ps1 -Coins bitcoin,ethereum
#
# To stop: close the PowerShell window or press Ctrl+C.
# Run this from the same "python" you already tested RSP.paper_trading.runner
# with (i.e. from the arsan.1 folder, with the same venv/activation active).

param(
    [string[]]$Coins = @("bitcoin"),
    [int]$IntervalMinutes = 15,
    [string]$LogFile = "RSP\paper_trading\logs\run_loop.log"
)

$ErrorActionPreference = "Continue"
$logDir = Split-Path $LogFile -Parent
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

function Write-Log($msg) {
    $ts = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    $line = "[$ts] $msg"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line
}

Write-Log "=== RSP paper-trading loop started | coins=$($Coins -join ',') | interval=${IntervalMinutes}m ==="
Write-Log "Stop with Ctrl+C or by closing this window"

while ($true) {
    $cycleStart = Get-Date
    try {
        Write-Log "--- cycle start ---"
        $output = & python -m RSP.paper_trading.runner --coins @Coins 2>&1
        $output | ForEach-Object { Write-Log $_ }
        if ($LASTEXITCODE -ne 0) {
            Write-Log "WARNING: runner exited with code $LASTEXITCODE"
        }
    }
    catch {
        Write-Log "ERROR running cycle: $_"
    }

    # Schedule relative to cycle start (not end) so drift does not accumulate.
    $elapsed = (Get-Date) - $cycleStart
    $waitSeconds = [Math]::Max(0, ($IntervalMinutes * 60) - $elapsed.TotalSeconds)
    $msg = "cycle done in {0:N1}s, sleeping {1:N0}s until next cycle" -f $elapsed.TotalSeconds, $waitSeconds
    Write-Log $msg
    Start-Sleep -Seconds $waitSeconds
}
