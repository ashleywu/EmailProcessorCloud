# One-time: register Windows Task Scheduler job for scripts/run-daily.ps1
param(
    [string]$DailyAt = "15:00",
    [string]$TaskName = "DailyKnowledgeDigest"
)

$ErrorActionPreference = "Stop"
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Tip: run PowerShell as Administrator if registration fails for your account." -ForegroundColor Yellow
}

$runner = Join-Path $PSScriptRoot "run-daily.ps1"
if (-not (Test-Path -LiteralPath $runner)) {
    throw "Missing script: $runner"
}

$arg = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$runner`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg
$trigger = New-ScheduledTaskTrigger -Daily -At $DailyAt
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue | Unregister-ScheduledTask -Confirm:$false

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Daily Knowledge Digest: python -m app.main run-daily (repo: $(Split-Path -Parent $PSScriptRoot))"

Write-Host "Registered scheduled task '$TaskName' daily at $DailyAt (local time)." -ForegroundColor Green
Write-Host "Logs append under $(Split-Path -Parent $PSScriptRoot)\logs\" -ForegroundColor Green
