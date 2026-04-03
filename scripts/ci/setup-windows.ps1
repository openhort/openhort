# openhort Windows setup script
# Runs via Azure Custom Script Extension on first boot.
#
# Installs: OpenSSH Server (key auth), Python 3.12, Git, openhort
# Configures: firewall, scheduled task (interactive), .env
# Result: SSH + RDP + openhort fully operational, no manual steps

$ErrorActionPreference = "Continue"

Write-Host "=== openhort Windows Setup ==="

# ── Install OpenSSH Server ───────────────────────────────────────────
Write-Host "Installing OpenSSH Server..."
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0

# Generate host keys if missing (some Azure images don't auto-generate)
$sshDir = "C:\ProgramData\ssh"
if (-not (Test-Path "$sshDir\ssh_host_rsa_key")) {
    & "C:\Windows\System32\OpenSSH\ssh-keygen.exe" -A 2>$null
    Write-Host "  Host keys generated"
}

# Write a clean sshd_config with password auth enabled
@"
Port 22
AddressFamily any
ListenAddress 0.0.0.0
ListenAddress ::
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
PasswordAuthentication yes
PermitEmptyPasswords no
Subsystem sftp sftp-server.exe
"@ | Set-Content "$sshDir\sshd_config" -Encoding ASCII

# Set PowerShell as default SSH shell
New-ItemProperty -Path "HKLM:\SOFTWARE\OpenSSH" -Name DefaultShell `
    -Value "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" `
    -PropertyType String -Force

# Firewall
netsh advfirewall firewall add rule name="SSH" dir=in action=allow protocol=TCP localport=22

# Fix host key permissions (sshd is very strict about this)
icacls "$sshDir\ssh_host*" /inheritance:r /grant "NT AUTHORITY\SYSTEM:(F)" /grant "BUILTIN\Administrators:(R)" 2>$null

# Start sshd
Start-Service sshd -ErrorAction SilentlyContinue
Set-Service -Name sshd -StartupType Automatic
Write-Host "  sshd: $((Get-Service sshd -ErrorAction SilentlyContinue).Status)"

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
$null = git checkout feature/windows-support 2>&1
& "$hortDir\venv\Scripts\pip.exe" install -e .

# Install all runtime deps explicitly (editable install doesn't resolve them with local path dev deps)
& "$hortDir\venv\Scripts\pip.exe" install "uvicorn[standard]" "Pillow" "qrcode[pil]" "pydantic>=2.10" "websockets" "itsdangerous" "pyyaml" "psutil" "aiortc"

# Create dirs
New-Item -ItemType Directory -Force -Path "$hortDir\src\logs" | Out-Null

# ── Create .env ──────────────────────────────────────────────────────
@"
LLMING_DEV=0
LLMING_AUTH_SECRET=openhort-test
"@ | Out-File -FilePath "$hortDir\src\.env" -Encoding ASCII

# ── Create run script ────────────────────────────────────────────────
@"
`$env:LLMING_AUTH_SECRET = "openhort-test"
Set-Location C:\openhort\src
C:\openhort\venv\Scripts\python.exe -m uvicorn hort.app:app --host 0.0.0.0 --port 8940
"@ | Out-File -FilePath "$hortDir\run.ps1" -Encoding ASCII

# ── Firewall for openhort ────────────────────────────────────────────
netsh advfirewall firewall add rule name="openhort" dir=in action=allow protocol=TCP localport=8940

# ── Scheduled task: starts openhort in interactive (RDP) session ─────
# /IT = interactive only, /I on Run = run in interactive session
# This ensures BitBlt/PrintWindow have desktop access for screen capture
schtasks /Create /TN "openhort" /TR "powershell -ExecutionPolicy Bypass -File C:\openhort\run.ps1" /SC ONLOGON /RL HIGHEST /IT /F

Write-Host "=== openhort Windows Setup Complete ==="
Write-Host "  SSH:      port 22 (password: OpenHort2026!)"
Write-Host "  RDP:      port 3389 (hortuser / OpenHort2026!)"
Write-Host "  openhort: starts on RDP login at http://localhost:8940"
Write-Host "  Note: RDP login required for screen capture to work"
