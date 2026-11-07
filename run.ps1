param (
    [Parameter(Mandatory=$false)]
    [ValidateSet("App", "Enterprise", "Lightweight", "Stop", "Kiosk", "Status", "Check")]
    [string]$Action = "Status"
)

$ErrorActionPreference = "Stop"
$RepoRoot = $PSScriptRoot
$EnvFile  = Join-Path $RepoRoot ".env"
$Python   = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

$ComposeApp        = Join-Path $RepoRoot "docker-compose.yml"
$ComposeEnterprise = Join-Path $RepoRoot "docker\docker-compose.enterprise.yml"
$ComposeLight      = Join-Path $RepoRoot "docker\docker-compose.lightweight.yml"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  THERMAL & BUSINESS COMMAND CENTER ORCHESTRATOR" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

function Test-Docker {
    try { docker version --format '{{.Server.Version}}' | Out-Null }
    catch {
        Write-Host "KHONG ket noi duoc Docker daemon." -ForegroundColor Red
        Write-Host "Hay khoi dong Docker Desktop roi chay lai." -ForegroundColor Yellow
        exit 1
    }
}

function Test-EnvFile {
    if (-not (Test-Path $EnvFile)) {
        Write-Host "KHONG TIM THAY .env o thu muc goc repo." -ForegroundColor Red
        Write-Host "Hay chay:  Copy-Item .env.example .env   roi dien secret that." -ForegroundColor Yellow
        exit 1
    }
}

function Get-EnvValue([string]$Key, [string]$Fallback) {
    if (-not (Test-Path $EnvFile)) { return $Fallback }
    $line = Select-String -Path $EnvFile -Pattern "^$Key=" -SimpleMatch:$false | Select-Object -First 1
    if (-not $line) { return $Fallback }
    $value = ($line.Line -split '=', 2)[1].Trim().Trim('"').Trim("'")
    if ([string]::IsNullOrWhiteSpace($value)) { return $Fallback }
    return $value
}

function Invoke-EnvCheck {
    Write-Host "-> Kiem tra .env so voi cac file cau hinh..." -ForegroundColor Green
    & $Python (Join-Path $RepoRoot "scripts\check_env.py") | Out-Host
    return $LASTEXITCODE
}

function Invoke-Compose([string]$File, [string[]]$ComposeArgs) {
    $envArgs = @()
    if (Test-Path $EnvFile) { $envArgs = @("--env-file", $EnvFile) }
    docker compose @envArgs -f $File @ComposeArgs
}

function Show-Stack([string]$Label, [string]$File, [string]$Color) {
    Write-Host ""
    Write-Host "--- $Label ---" -ForegroundColor $Color
    if (-not (Test-Path $File)) { Write-Host "  (khong tim thay $File)" -ForegroundColor DarkGray; return }
    Invoke-Compose $File @("ps", "--format", "table {{.Service}}\t{{.State}}\t{{.Status}}\t{{.Ports}}")
}

switch ($Action) {
    "Check" {
        Test-EnvFile
        $code = Invoke-EnvCheck
        exit $code
    }

    "App" {
        Test-Docker
        Test-EnvFile
        if ((Invoke-EnvCheck) -ne 0) { Write-Host "Sua .env truoc khi khoi chay." -ForegroundColor Red; exit 1 }
        Write-Host "-> Khoi chay stack ung dung (FastAPI + PostgreSQL + Grafana)..." -ForegroundColor Green
        Invoke-Compose $ComposeApp @("up", "-d", "--build")
        $apiPort = Get-EnvValue "API_PORT" "8080"
        $grafPort = Get-EnvValue "GRAFANA_PORT" "3000"
        Write-Host "Da khoi chay! API: http://localhost:$apiPort/docs | Grafana: http://localhost:$grafPort" -ForegroundColor Yellow
    }

    "Enterprise" {
        Test-Docker
        Test-EnvFile
        if ((Invoke-EnvCheck) -ne 0) { Write-Host "Sua .env truoc khi khoi chay." -ForegroundColor Red; exit 1 }
        Write-Host "-> Khoi chay Huong A (ThingsBoard + ERPNext + Grafana + Connector A)..." -ForegroundColor Green
        Invoke-Compose $ComposeEnterprise @("up", "-d")
        $tbPort = Get-EnvValue "TB_PORT" "8083"
        $grafPort = Get-EnvValue "GRAFANA_PORT" "3000"
        Write-Host "Da khoi chay! Grafana: http://localhost:$grafPort | ThingsBoard: http://localhost:$tbPort" -ForegroundColor Yellow
    }

    "Lightweight" {
        Test-Docker
        Test-EnvFile
        if ((Invoke-EnvCheck) -ne 0) { Write-Host "Sua .env truoc khi khoi chay." -ForegroundColor Red; exit 1 }
        Write-Host "-> Khoi chay Huong B (Home Assistant + Invoice Ninja + Grafana + Connector B)..." -ForegroundColor Green
        Invoke-Compose $ComposeLight @("up", "-d")
        $grafPort = Get-EnvValue "GRAFANA_PORT_B" "3001"
        $ninjaPort = Get-EnvValue "INVOICE_NINJA_PORT" "8088"
        $haPort = Get-EnvValue "HASS_PORT" "8123"
        Write-Host "Da khoi chay! Grafana: http://localhost:$grafPort | Invoice Ninja: http://localhost:$ninjaPort | HA: http://localhost:$haPort" -ForegroundColor Yellow
    }

    "Stop" {
        Test-Docker
        Write-Host "-> Dang dung tat ca cac stack..." -ForegroundColor Red
        Invoke-Compose $ComposeApp @("down")
        Invoke-Compose $ComposeEnterprise @("down")
        Invoke-Compose $ComposeLight @("down")
        Write-Host "Da dung thanh cong! (du lieu trong volume van duoc giu)" -ForegroundColor Yellow
    }

    "Status" {
        Test-Docker
        Show-Stack "Stack ung dung (FastAPI + Postgres + Grafana)" $ComposeApp "Green"
        Show-Stack "Huong A - Enterprise (ThingsBoard + ERPNext)" $ComposeEnterprise "Cyan"
        Show-Stack "Huong B - Lightweight (Home Assistant + Invoice Ninja)" $ComposeLight "Magenta"
        Write-Host ""
        if (Test-Path $EnvFile) {
            Write-Host "-> Kiem tra .env..." -ForegroundColor Green
            & $Python (Join-Path $RepoRoot "scripts\check_env.py")
        } else {
            Write-Host "Chua co .env - chay: Copy-Item .env.example .env" -ForegroundColor Yellow
        }
        Write-Host ""
        Write-Host "Cac lenh kha dung:" -ForegroundColor Yellow
        Write-Host "  .\run.ps1 -Action App          : Chay stack ung dung viet rieng (khuyen nghi bat dau tu day)"
        Write-Host "  .\run.ps1 -Action Enterprise   : Chay stack Huong A (ThingsBoard + ERPNext)"
        Write-Host "  .\run.ps1 -Action Lightweight  : Chay stack Huong B (Home Assistant + Invoice Ninja)"
        Write-Host "  .\run.ps1 -Action Status       : Xem container dang chay + kiem tra .env"
        Write-Host "  .\run.ps1 -Action Check        : Chi kiem tra .env, khong dung Docker"
        Write-Host "  .\run.ps1 -Action Stop         : Dung cac container dang chay"
        Write-Host "  .\run.ps1 -Action Kiosk        : Mo man hinh TV Kiosk tren Edge/Chrome"
    }

    "Kiosk" {
        Write-Host "-> Dang khoi dong man hinh TV Kiosk..." -ForegroundColor Cyan
        Start-Process (Join-Path $RepoRoot "clients\desktop-kiosk\launch-kiosk.bat")
    }
}
