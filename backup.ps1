# سکریپت‌های بک‌اپ AlovpnBot برای Windows PowerShell

param(
    [Parameter(Mandatory=$false)]
    [ValidateSet('now', 'stats', 'cleanup', 'setup', 'help')]
    [string]$Command = 'help'
)

# رنگ‌ها
$Green = [System.ConsoleColor]::Green
$Red = [System.ConsoleColor]::Red
$Yellow = [System.ConsoleColor]::Yellow
$Cyan = [System.ConsoleColor]::Cyan

# متغیرهای پیش‌فرض
$BackupDir = "./backups"
$RetentionDays = 30

function Write-Log {
    param([string]$Message, [System.ConsoleColor]$Color = $Green)
    $timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    Write-Host "[$timestamp] $Message" -ForegroundColor $Color
}

function Write-Error-Log {
    param([string]$Message)
    $timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    Write-Host "[$timestamp] ERROR: $Message" -ForegroundColor $Red
}

function Write-Warning-Log {
    param([string]$Message)
    $timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    Write-Host "[$timestamp] WARNING: $Message" -ForegroundColor $Yellow
}

# بک‌اپ فوری
function Backup-Now {
    Write-Log "شروع بک‌اپ..."
    
    # ایجاد پوشه اگر وجود نداشته باشد
    if (-not (Test-Path $BackupDir)) {
        New-Item -ItemType Directory -Path $BackupDir | Out-Null
        Write-Log "پوشه بک‌اپ ایجاد شد: $BackupDir"
    }
    
    try {
        # اجرای بک‌اپ توسط Docker
        $timestamp = (Get-Date).ToString("yyyyMMdd_HHmmss")
        Write-Log "اجرای دستور بک‌اپ در Docker..."
        
        docker exec alovpn-backup /bin/sh /backup.sh now
        
        if ($LASTEXITCODE -eq 0) {
            Write-Log "✅ بک‌اپ موفقیت‌آمیز انجام شد" $Green
            Show-Stats
            return $true
        } else {
            Write-Error-Log "خرابی در اجرای بک‌اپ (کد خروج: $LASTEXITCODE)"
            return $false
        }
    } catch {
        Write-Error-Log "خطای Docker: $_"
        return $false
    }
}

# نمایش آمار
function Show-Stats {
    Write-Log "📊 آمار بک‌اپ‌ها:" $Cyan
    
    if (Test-Path $BackupDir) {
        $backups = Get-ChildItem -Path $BackupDir -Filter "bot_backup_*.db.gz" -ErrorAction SilentlyContinue
        
        if ($backups.Count -gt 0) {
            $totalSize = ($backups | Measure-Object -Property Length -Sum).Sum
            $totalSizeGB = $totalSize / 1GB
            
            Write-Host ""
            Write-Host "تعداد بک‌اپ: $($backups.Count)"
            Write-Host "حجم کل: $([Math]::Round($totalSizeGB, 2)) GB"
            Write-Host ""
            Write-Host "آخرین بک‌اپ‌ها:" -ForegroundColor $Cyan
            Write-Host ""
            
            $backups | Sort-Object LastWriteTime -Descending | Select-Object -First 5 |
                ForEach-Object {
                    $size = $_.Length / 1MB
                    $date = $_.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
                    Write-Host "  $('{0,8:F2}' -f $size) MB  $date  $($_.Name)"
                }
        } else {
            Write-Warning-Log "هیچ بک‌اپی یافت نشد"
        }
    } else {
        Write-Warning-Log "پوشه بک‌اپ وجود ندارد"
    }
    Write-Host ""
}

# حذف بک‌اپ‌های قدیمی
function Cleanup-Old-Backups {
    Write-Log "🧹 حذف بک‌اپ‌های قدیمی‌تر از $RetentionDays روز..."
    
    try {
        docker exec alovpn-backup /bin/sh /backup.sh cleanup
        
        if ($LASTEXITCODE -eq 0) {
            Write-Log "✅ پاکسازی انجام شد" $Green
        } else {
            Write-Error-Log "خرابی در پاکسازی (کد خروج: $LASTEXITCODE)"
        }
    } catch {
        Write-Error-Log "خطای Docker: $_"
    }
}

# نمایش راهنما
function Show-Help {
    Write-Host ""
    Write-Host "AlovpnBot - ابزارهای بک‌اپ" -ForegroundColor $Cyan
    Write-Host ""
    Write-Host "استفاده: .\backup.ps1 [دستور]" -ForegroundColor $Cyan
    Write-Host ""
    Write-Host "دستورات:" -ForegroundColor $Cyan
    Write-Host "  now      - اجرای بک‌اپ فوری"
    Write-Host "  stats    - نمایش آمار بک‌اپ‌ها"
    Write-Host "  cleanup  - حذف بک‌اپ‌های قدیمی"
    Write-Host "  help     - نمایش این راهنما"
    Write-Host ""
    Write-Host "مثال‌ها:" -ForegroundColor $Cyan
    Write-Host "  .\backup.ps1 now        # بک‌اپ فوری"
    Write-Host "  .\backup.ps1 stats      # نمایش آمار"
    Write-Host ""
}

# بررسی Docker
function Check-Docker {
    try {
        $null = docker ps 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Error-Log "Docker در دسترس نیست"
            return $false
        }
        return $true
    } catch {
        Write-Error-Log "Docker نصب نیست یا قابل دسترس نیست"
        return $false
    }
}

# اجرای دستور
Write-Host ""

if (-not (Check-Docker)) {
    Write-Error-Log "Docker را شروع کنید و دوباره تلاش کنید"
    exit 1
}

switch ($Command) {
    'now' {
        Backup-Now
    }
    'stats' {
        Show-Stats
    }
    'cleanup' {
        Cleanup-Old-Backups
    }
    'help' {
        Show-Help
    }
    default {
        Show-Help
    }
}

Write-Host ""
