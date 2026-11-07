#!/usr/bin/env bash
# Linux TV Kiosk Launcher
echo "========================================================"
echo "  KHOI DONG MAN HINH TV KIOSK CHO BAN GIAM DOC (LINUX)  "
echo "========================================================"
echo "Chon man hinh:"
echo "[1] Huong A: ThingsBoard + ERPNext"
echo "[2] Huong B: Home Assistant + Invoice Ninja"
read -p "Nhap lua chon [1/2]: " choice

if [ "$choice" = "2" ]; then
    URL="http://localhost:3000/d/esco-invoiceninja-cockpit?kiosk&refresh=10s"
else
    URL="http://localhost:3000/d/industrial-thermal-erpnext?kiosk&refresh=10s"
fi

google-chrome --kiosk "$URL" || chromium-browser --kiosk "$URL" || firefox --kiosk "$URL"
