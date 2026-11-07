@echo off
title Thermal & Business Command Center - TV Kiosk Launcher
echo ========================================================
echo   KHOI DONG MAN HINH TV KIOSK CHO BAN GIAM DOC
echo ========================================================
echo.
echo Chon man hinh can bat:
echo [1] Huong A: ThingsBoard + ERPNext Command Center
echo [2] Huong B: Home Assistant + Invoice Ninja Cockpit
echo.
set /p choice="Nhap lua chon (1 hoac 2, mac dinh la 1): "

if "%choice%"=="2" (
    set TARGET_URL=http://localhost:3000/d/esco-invoiceninja-cockpit?kiosk^&refresh=10s
) else (
    set TARGET_URL=http://localhost:3000/d/industrial-thermal-erpnext?kiosk^&refresh=10s
)

echo Dang mo trinh duyet o che do Kiosk toan man hinh...
start msedge --kiosk "%TARGET_URL%" --edge-kiosk-type=fullscreen || start chrome --kiosk "%TARGET_URL%"
