# =============================================================================
# transfer-orchestrate.ps1
# Windows PowerShell orchestrator — drives the full source→destination transfer
# via SSH without you having to log in to each server manually.
#
# Requirements on your Windows machine:
#   - OpenSSH client (built into Windows 10/11)
#   - SSH key access to both servers (or password auth via $env:SSHPASS)
#
# Usage:
#   .\scripts\transfer-orchestrate.ps1 `
#       -Source "root@1.2.3.4" `
#       -Dest   "root@5.6.7.8" `
#       -SourceProjectDir "/opt/alovpnBot" `
#       -DestProjectDir   "/opt/alovpnBot" `
#       -DestRepoUrl      "https://github.com/yourname/alovpnBot.git"
# =============================================================================

param(
    [Parameter(Mandatory)] [string] $Source,          # user@source-ip
    [Parameter(Mandatory)] [string] $Dest,            # user@dest-ip
    [string] $SourceProjectDir = "/opt/alovpnBot",
    [string] $DestProjectDir   = "/opt/alovpnBot",
    [string] $DestRepoUrl      = "",                  # leave empty to skip git clone
    [string] $SshKeyFile       = "",                  # path to private key, e.g. ~/.ssh/id_rsa
    [switch] $SkipConfirmation
)

$ErrorActionPreference = "Stop"

# ── helpers ───────────────────────────────────────────────────────────────────
function Write-Step { param($msg) Write-Host "`n[STEP] $msg" -ForegroundColor Cyan }
function Write-OK   { param($msg) Write-Host "  ✔  $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "  ⚠  $msg" -ForegroundColor Yellow }
function Write-Fail { param($msg) Write-Host "  ✖  $msg" -ForegroundColor Red; exit 1 }

function Invoke-SSH {
    param([string]$Host, [string]$Command)
    $sshArgs = @()
    if ($SshKeyFile) { $sshArgs += "-i", $SshKeyFile }
    $sshArgs += "-o", "StrictHostKeyChecking=no"
    $sshArgs += $Host
    $sshArgs += $Command
    $output = ssh @sshArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host $output -ForegroundColor Red
        throw "SSH command failed on $Host (exit $LASTEXITCODE): $Command"
    }
    return $output
}

function Copy-Via-SCP {
    param([string]$From, [string]$To)
    $scpArgs = @()
    if ($SshKeyFile) { $scpArgs += "-i", $SshKeyFile }
    $scpArgs += "-o", "StrictHostKeyChecking=no"
    $scpArgs += $From, $To
    scp @scpArgs
    if ($LASTEXITCODE -ne 0) { throw "SCP failed: $From -> $To" }
}

# ── banner ────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════╗" -ForegroundColor Magenta
Write-Host "║         alovpnBot  —  Server Transfer Tool           ║" -ForegroundColor Magenta
Write-Host "╚══════════════════════════════════════════════════════╝" -ForegroundColor Magenta
Write-Host ""
Write-Host "  Source : $Source  ($SourceProjectDir)" -ForegroundColor White
Write-Host "  Dest   : $Dest    ($DestProjectDir)"   -ForegroundColor White
Write-Host ""

if (-not $SkipConfirmation) {
    $ans = Read-Host "  Proceed with transfer? (yes/no)"
    if ($ans -ne "yes") { Write-Host "Aborted."; exit 0 }
}

# ── step 1: copy scripts to source ───────────────────────────────────────────
Write-Step "1/6  Uploading transfer scripts to source server…"
$transferScripts = @("transfer-export.sh", "transfer-import.sh", "transfer-disable-source.sh")
foreach ($s in $transferScripts) {
    Copy-Via-SCP `
        "$PSScriptRoot\$s" `
        "${Source}:${SourceProjectDir}/scripts/$s"
}
Invoke-SSH $Source "chmod +x ${SourceProjectDir}/scripts/transfer-export.sh ${SourceProjectDir}/scripts/transfer-disable-source.sh"
Write-OK "Scripts uploaded."

# ── step 2: export on source ──────────────────────────────────────────────────
Write-Step "2/6  Running export on source server…"
$archiveName = "alovpn_transfer_$(Get-Date -Format 'yyyyMMdd_HHmmss').tar.gz"
$srcArchivePath = "/tmp/$archiveName"

Invoke-SSH $Source "bash ${SourceProjectDir}/scripts/transfer-export.sh --output $srcArchivePath"
Write-OK "Export complete: $srcArchivePath on source."

# ── step 3: transfer archive to destination ────────────────────────────────────
Write-Step "3/6  Transferring archive from source to destination…"

# Determine dest tmp path
$dstArchivePath = "/tmp/$archiveName"

# Source → local temp → Dest  (avoids needing source→dest direct SSH)
$localTmp = Join-Path $env:TEMP $archiveName

Write-Warn "Downloading archive to local machine…"
Copy-Via-SCP "${Source}:${srcArchivePath}" $localTmp
Write-OK "Archive downloaded locally: $localTmp"

Write-Warn "Uploading archive to destination…"
Copy-Via-SCP $localTmp "${Dest}:${dstArchivePath}"
Remove-Item $localTmp -Force
Write-OK "Archive uploaded to destination."

# ── step 4: copy import script to destination ──────────────────────────────────
Write-Step "4/6  Uploading import script to destination…"
Copy-Via-SCP "$PSScriptRoot\transfer-import.sh" "${Dest}:${DestProjectDir}/scripts/transfer-import.sh" 2>/dev/null

# Also copy all scripts for future use on dest
foreach ($s in $transferScripts) {
    try {
        Copy-Via-SCP "$PSScriptRoot\$s" "${Dest}:${DestProjectDir}/scripts/$s"
    } catch {
        Write-Warn "Could not copy $s to dest (directory may not exist yet, import will handle it)."
    }
}

# Run import
Write-Step "5/6  Running import on destination server…"
$importEnv = "INSTALL_DIR=$DestProjectDir"
if ($DestRepoUrl) { $importEnv += " REPO_URL=$DestRepoUrl" }

Invoke-SSH $Dest "bash -c 'mkdir -p ${DestProjectDir}/scripts && $importEnv bash /tmp/transfer-import-run.sh $dstArchivePath'" 2>/dev/null

# If scripts dir didn't exist yet, upload and run directly
try {
    Invoke-SSH $Dest "$importEnv bash ${DestProjectDir}/scripts/transfer-import.sh $dstArchivePath"
} catch {
    Write-Warn "Running import directly from /tmp…"
    Copy-Via-SCP "$PSScriptRoot\transfer-import.sh" "${Dest}:/tmp/transfer-import.sh"
    Invoke-SSH $Dest "chmod +x /tmp/transfer-import.sh && $importEnv bash /tmp/transfer-import.sh $dstArchivePath"
}
Write-OK "Import complete on destination."

# ── step 5: verify destination ────────────────────────────────────────────────
Write-Step "5/6  Verifying destination bot status…"
$status = Invoke-SSH $Dest "docker inspect --format '{{.State.Status}}' alovpn-bot 2>/dev/null || echo 'not-found'"
if ($status -match "running") {
    Write-OK "Destination bot is running."
} else {
    Write-Warn "Container status: $status"
    Write-Warn "Check destination logs: ssh $Dest 'docker logs --tail 30 alovpn-bot'"
}

# ── step 6: prompt to disable source ─────────────────────────────────────────
Write-Step "6/6  Disable source server?"
Write-Host ""
Write-Host "  Please verify the destination bot is working correctly in Telegram." -ForegroundColor Yellow
Write-Host "  Then confirm here to permanently disable the source server."          -ForegroundColor Yellow
Write-Host ""

$disable = Read-Host "  Disable source server NOW? (yes/no)"
if ($disable -eq "yes") {
    Invoke-SSH $Source "bash ${SourceProjectDir}/scripts/transfer-disable-source.sh <<< 'yes'"
    Write-OK "Source server disabled."
} else {
    Write-Warn "Source server NOT disabled yet."
    Write-Host "  Run manually when ready:" -ForegroundColor Yellow
    Write-Host "    ssh $Source 'bash ${SourceProjectDir}/scripts/transfer-disable-source.sh'" -ForegroundColor Yellow
}

# ── done ──────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║         Transfer completed successfully!              ║" -ForegroundColor Green
Write-Host "╚══════════════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
Write-Host "  Monitor destination:  ssh $Dest 'docker logs -f alovpn-bot'" -ForegroundColor Cyan
Write-Host ""
