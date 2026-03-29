# openhort Windows setup script
# Runs via Azure Custom Script Extension on first boot.
#
# Installs Python 3.12, openhort, and starts the server.
# The VM already has RDP access via the Azure-created admin user.

$ErrorActionPreference = "Stop"

Write-Host "=== openhort Windows Setup ==="

# ── Install Python 3.12 ─────────────────────────────────────────────
Write-Host "Installing Python 3.12..."
$pythonUrl = "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe"
$installer = "$env:TEMP\python-installer.exe"
Invoke-WebRequest -Uri $pythonUrl -OutFile $installer
Start-Process -Wait -FilePath $installer -ArgumentList "/quiet", "InstallAllUsers=1", "PrependPath=1", "Include_pip=1"
Remove-Item $installer

# Refresh PATH
$env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH", "User")

# Verify
python --version
pip --version

# ── Install Git ──────────────────────────────────────────────────────
Write-Host "Installing Git..."
$gitUrl = "https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.2/Git-2.47.1.2-64-bit.exe"
$gitInstaller = "$env:TEMP\git-installer.exe"
Invoke-WebRequest -Uri $gitUrl -OutFile $gitInstaller
Start-Process -Wait -FilePath $gitInstaller -ArgumentList "/VERYSILENT", "/NORESTART"
Remove-Item $gitInstaller
$env:PATH += ";C:\Program Files\Git\bin"

# ── Install openhort ─────────────────────────────────────────────────
Write-Host "Installing openhort..."
$hortDir = "C:\openhort"
New-Item -ItemType Directory -Force -Path $hortDir | Out-Null

python -m venv "$hortDir\venv"
& "$hortDir\venv\Scripts\python.exe" -m pip install --upgrade pip
& "$hortDir\venv\Scripts\pip.exe" install "git+https://github.com/Alyxion/llming-com.git@main"
& "$hortDir\venv\Scripts\pip.exe" install httpx

# Clone openhort
git clone https://github.com/openhort/openhort.git "$hortDir\src"
Set-Location "$hortDir\src"
git checkout feature/windows-support 2>$null
& "$hortDir\venv\Scripts\pip.exe" install -e .

# Create logs directory
New-Item -ItemType Directory -Force -Path "$hortDir\src\logs" | Out-Null

# ── Create startup script ────────────────────────────────────────────
$startScript = @"
@echo off
set LLMING_AUTH_SECRET=openhort-test
cd /d C:\openhort\src
C:\openhort\venv\Scripts\python.exe -m uvicorn hort.app:app --host 0.0.0.0 --port 8940
"@
$startScript | Out-File -FilePath "$hortDir\start.bat" -Encoding ASCII

# ── Open firewall ────────────────────────────────────────────────────
Write-Host "Opening firewall port 8940..."
New-NetFirewallRule -DisplayName "openhort" -Direction Inbound -Port 8940 -Protocol TCP -Action Allow | Out-Null

# ── Register as a scheduled task (runs at login) ─────────────────────
Write-Host "Registering startup task..."
$action = New-ScheduledTaskAction -Execute "$hortDir\start.bat"
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit 0
Register-ScheduledTask -TaskName "openhort" -Action $action -Trigger $trigger -Settings $settings -User "hortuser" -RunLevel Highest -Force | Out-Null

# ── Start openhort now ────────────────────────────────────────────────
Write-Host "Starting openhort..."
Start-Process -FilePath "$hortDir\start.bat" -WindowStyle Hidden

Write-Host "=== openhort Windows Setup Complete ==="
Write-Host "  openhort: http://localhost:8940"
Write-Host "  RDP in and check Task Manager for uvicorn process"
