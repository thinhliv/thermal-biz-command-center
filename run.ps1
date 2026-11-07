param (
    [Parameter(Mandatory=$false)]
    [ValidateSet("Enterprise", "Lightweight", "Stop", "Kiosk", "Status")]
    [string]$Action = "Status"
)

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  THERMAL & BUSINESS COMMAND CENTER ORCHESTRATOR" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

switch ($Action) {
    "Enterprise" {
        Write-Host "-> Khoi chay Huong A (ThingsBoard + ERPNext + Grafana + Connector A)..." -ForegroundColor Green
        docker-compose -f docker/docker-compose.enterprise.yml up -d
        Write-Host "Da khoi chay! Grafana: http://localhost:3000 | ThingsBoard: http://localhost:8080" -ForegroundColor Yellow
    }
    "Lightweight" {
        Write-Host "-> Khoi chay Huong B (Home Assistant + Invoice Ninja + Grafana + Connector B)..." -ForegroundColor Green
        docker-compose -f docker/docker-compose.lightweight.yml up -d
        Write-Host "Da khoi chay! Grafana: http://localhost:3000 | Invoice Ninja: http://localhost:8088 | HA: http://localhost:8123" -ForegroundColor Yellow
    }
    "Stop" {
        Write-Host "-> Dang dung tat ca cac stack..." -ForegroundColor Red
        docker-compose -f docker/docker-compose.enterprise.yml down
        docker-compose -f docker/docker-compose.lightweight.yml down
        Write-Host "Da dung thanh cong!" -ForegroundColor Yellow
    }
    "Kiosk" {
        Write-Host "-> Dang khoi dong man hinh TV Kiosk..." -ForegroundColor Cyan
        Start-Process "clients/desktop-kiosk/launch-kiosk.bat"
    }
    Default {
        Write-Host "Cac lenh kha dung:" -ForegroundColor Yellow
        Write-Host "  .\run.ps1 -Action Enterprise   : Chay stack Huong A (ThingsBoard + ERPNext)"
        Write-Host "  .\run.ps1 -Action Lightweight  : Chay stack Huong B (Home Assistant + Invoice Ninja)"
        Write-Host "  .\run.ps1 -Action Stop         : Dung cac container dang chay"
        Write-Host "  .\run.ps1 -Action Kiosk        : Mo man hinh TV Kiosk tren Edge/Chrome"
    }
}
