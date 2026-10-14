# [R186] Zhuge start-all: start Futu OpenD, MT5 and the data-push scripts after Windows logon.
# Read-only data pushers only: no orders, no unlock_trade. Safe to re-run: anything already running is skipped.
#
# One-time setup (PowerShell, user env vars; reopen PowerShell afterwards):
#   setx ZHUGE_OPEND_EXE "C:\path\to\Futu_OpenD.exe"        # Futu OpenD (GUI) executable
#   setx ZHUGE_MT5_EXE   "C:\Program Files\MetaTrader 5\terminal64.exe"
#   setx ZHUGE_DAEMONS   "auto_risk,push_to_gcp,iv_push,mt5_push"   # optional; this is the default
# Startup folder shortcut (created by the runbook): ZhugeStartAll.cmd -> this script.
# Logs: tradingview\out\logs\<name>.log and tradingview\out\logs\start_all.log
# [R187] Once the futu-data VM runs OpenD/auto_risk/push scripts: setx ZHUGE_DAEMONS "mt5_push" and setx ZHUGE_OPEND_EXE ""
#        so this PC only starts MT5 + mt5_push (see tradingview\RUNBOOK_FUTU_VM.md).

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root "tradingview\out\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$MainLog = Join-Path $LogDir "start_all.log"
function Log($msg) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg" | Add-Content -Path $MainLog -Encoding utf8; Write-Host $msg }

$env:PYTHONIOENCODING = "utf-8"
$Py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $Py) { Log "python not found in PATH; stop"; exit 1 }

function Start-App($label, $exe, $procName) {
    if (-not $exe) { Log "$label : path env var not set, skip"; return $false }
    if (-not (Test-Path $exe)) { Log "$label : not found at $exe, skip"; return $false }
    if (Get-Process -Name $procName -ErrorAction SilentlyContinue) { Log "$label : already running"; return $true }
    Start-Process -FilePath $exe -WorkingDirectory (Split-Path -Parent $exe) | Out-Null
    Log "$label : started"
    return $true
}

function Wait-Port($port, $seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        if ($c) { return $true }
        Start-Sleep -Seconds 5
    }
    return $false
}

# 1. Futu OpenD (API port 11111). Login is done by OpenD itself (remember-login); 2FA prompts need the user.
$opendExe = $env:ZHUGE_OPEND_EXE
$opendName = if ($opendExe) { [IO.Path]::GetFileNameWithoutExtension($opendExe) } else { "" }
if (Start-App "OpenD" $opendExe $opendName) {
    if (Wait-Port 11111 180) { Log "OpenD : port 11111 ready" } else { Log "OpenD : port 11111 not ready after 180s (login needed?); scripts will retry" }
}

# 2. MetaTrader 5 (EA heartbeats go to Cloud Run by themselves once the terminal is up and logged in)
if (Start-App "MT5" $env:ZHUGE_MT5_EXE "terminal64") { Start-Sleep -Seconds 30 }

# 3. Python data pushers (each loops by itself; skipped if already running)
$scripts = @{
    "auto_risk"   = @("gcp_ib\auto_risk.py", "--every", "15")
    "push_to_gcp" = @("futu\push_to_gcp.py")
    "iv_push"     = @("futu\iv_push.py")
    "mt5_push"    = @("futu\mt5_push.py")
    "inline_push" = @("futu\inline_push.py", "--every", "30")
    "scan_push"   = @("futu\scan_push.py", "--every", "30")
}
$want = if ($env:ZHUGE_DAEMONS) { $env:ZHUGE_DAEMONS } else { "auto_risk,push_to_gcp,iv_push,mt5_push" }
$running = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" | ForEach-Object { $_.CommandLine }
foreach ($name in ($want -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ })) {
    if (-not $scripts.ContainsKey($name)) { Log "$name : unknown name, skip"; continue }
    $args_ = $scripts[$name]
    $file = $args_[0]
    if ($running | Where-Object { $_ -and $_ -like "*$($file.Split('\')[-1])*" }) { Log "$name : already running"; continue }
    $log = Join-Path $LogDir "$name.log"
    $cmd = "set PYTHONIOENCODING=utf-8&& `"$Py`" $($args_ -join ' ') >> `"$log`" 2>&1"
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c", $cmd -WorkingDirectory $Root -WindowStyle Hidden | Out-Null
    Log "$name : started (log $log)"
}
Log "start_all done"
