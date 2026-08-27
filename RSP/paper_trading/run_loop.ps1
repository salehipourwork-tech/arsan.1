# RSP — paper_trading/run_loop.ps1
#
# اجرای مداوم چرخه‌ی validation هر ۱۵ دقیقه (هم‌زمان با بسته‌شدن کندل 15M).
# فقط runner.py را صدا می‌زند — هیچ پارامتری اینجا تغییر نمی‌کند.
#
# استفاده (از پوشه‌ی اصلی پروژه arsan.1):
#   powershell -ExecutionPolicy Bypass -File RSP\paper_trading\run_loop.ps1
#   یا با کوین‌های دیگر:
#   powershell -ExecutionPolicy Bypass -File RSP\paper_trading\run_loop.ps1 -Coins bitcoin,ethereum
#
# برای توقف: پنجره‌ی PowerShell را ببندید یا Ctrl+C بزنید.
# این اسکریپت را با همان "python" که RSP.paper_trading.runner با آن تست
# کردید اجرا کنید (یعنی از همان پوشه‌ی arsan.1، با همان venv/فعال‌سازی).

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
Write-Log "توقف: Ctrl+C یا بستن این پنجره"

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

    # زمان‌بندی نسبت به شروع چرخه، نه پایان آن — تا drift جمع نشود.
    $elapsed = (Get-Date) - $cycleStart
    $waitSeconds = [Math]::Max(0, ($IntervalMinutes * 60) - $elapsed.TotalSeconds)
    Write-Log ("cycle done in {0:N1}s — sleeping {1:N0}s until next cycle" -f $elapsed.TotalSeconds, $waitSeconds)
    Start-Sleep -Seconds $waitSeconds
}
