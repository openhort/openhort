# openhort Windows setup script
# Runs via Azure Custom Script Extension on first boot.
#
# Installs: OpenSSH Server, Python 3.12, Git, openhort
# Configures: firewall, SSH key auth, startup task

$ErrorActionPreference = "Continue"

Write-Host "=== openhort Windows Setup ==="

# ── Install OpenSSH Server (for remote management) ──────────────────
Write-Host "Installing OpenSSH Server..."
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Start-Service sshd
Set-Service -Name sshd -StartupType Automatic
New-ItemProperty -Path "HKLM:\SOFTWARE\OpenSSH" -Name DefaultShell -Value "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -PropertyType String -Force
netsh advfirewall firewall add rule name="SSH" dir=in action=allow protocol=TCP localport=22

# ── Install Python 3.12 ─────────────────────────────────────────────
Write-Host "Installing Python 3.12..."
$pythonUrl = "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe"
$installer = "$env:TEMP\python-installer.exe"
Invoke-WebRequest -Uri $pythonUrl -OutFile $installer
Start-Process -Wait -FilePath $installer -ArgumentList "/quiet", "InstallAllUsers=1", "PrependPath=1", "Include_pip=1"
Remove-Item $installer

# Refresh PATH
$env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH", "User")

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
& "$hortDir\venv\Scripts\pip.exe" install httpx aiogram

# Clone and install openhort
git clone https://github.com/openhort/openhort.git "$hortDir\src"
Set-Location "$hortDir\src"
# Suppress git stderr (branch switch message causes Custom Script Extension to report failure)
$null = git checkout feature/windows-support 2>&1
& "$hortDir\venv\Scripts\pip.exe" install -e .

# Install all runtime deps explicitly (pip install -e doesn't resolve them when llming-com is a local path dep)
& "$hortDir\venv\Scripts\pip.exe" install "uvicorn[standard]" "Pillow" "qrcode[pil]" "pydantic>=2.10" "websockets" "itsdangerous" "pyyaml" "psutil" "aiortc"

# Create logs directory
New-Item -ItemType Directory -Force -Path "$hortDir\src\logs" | Out-Null

# ── Create startup script ────────────────────────────────────────────
$runScript = @"
`$env:LLMING_AUTH_SECRET = "openhort-test"
Set-Location C:\openhort\src
C:\openhort\venv\Scripts\python.exe -m uvicorn hort.app:app --host 0.0.0.0 --port 8940
"@
$runScript | Out-File -FilePath "$hortDir\run.ps1" -Encoding ASCII

# ── Open firewall ────────────────────────────────────────────────────
Write-Host "Opening firewall port 8940..."
netsh advfirewall firewall add rule name="openhort" dir=in action=allow protocol=TCP localport=8940

# ── Register as a scheduled task (runs at startup as SYSTEM) ─────────
Write-Host "Registering startup task..."
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -File C:\openhort\run.ps1"
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit 0
Register-ScheduledTask -TaskName "openhort" -Action $action -Trigger $trigger -Settings $settings -User "SYSTEM" -RunLevel Highest -Force | Out-Null

# ── Start openhort now ────────────────────────────────────────────────
Write-Host "Starting openhort..."
Start-Process powershell -ArgumentList "-ExecutionPolicy","Bypass","-File","C:\openhort\run.ps1" -WindowStyle Hidden

Write-Host "=== openhort Windows Setup Complete ==="
Write-Host "  SSH:      port 22 (key or password auth)"
Write-Host "  openhort: http://localhost:8940"
Write-Host "  RDP:      port 3389"
