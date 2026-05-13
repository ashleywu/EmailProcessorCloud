# Runs the digest pipeline from the repository root (cwd matters for default DB / Gmail paths).
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $RepoRoot

$venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$python = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { "python" }

$logDir = Join-Path $RepoRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir ("run-daily-{0:yyyy-MM}.log" -f (Get-Date))

$stamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
Add-Content -LiteralPath $logFile -Value "`n======== $stamp ========"

$output = & $python -m app.main run-daily 2>&1
$code = $LASTEXITCODE
$output | Out-File -FilePath $logFile -Append -Encoding utf8
exit $code
