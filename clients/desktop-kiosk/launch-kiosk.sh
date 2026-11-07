#!/usr/bin/env bash
# ============================================================
#   MAN HINH TV KIOSK CHO BAN GIAM DOC (LINUX)
#
#   Uu tien ban desktop (AppImage/deb) vi no tu noi backend va
#   chay --kiosk that su. Khong tim thay thi moi dung trinh duyet.
#
#   Bien tuy chinh (khong bat buoc):
#     THERMAL_KIOSK_URL       dia chi ban web, mac dinh http://localhost:5173
#     THERMAL_KIOSK_EXE       duong dan ThermalBiz / *.AppImage neu de o cho khac
# ============================================================
set -u

THERMAL_KIOSK_URL="${THERMAL_KIOSK_URL:-http://localhost:5173}"

find_desktop_app() {
  if [ -n "${THERMAL_KIOSK_EXE:-}" ] && [ -x "${THERMAL_KIOSK_EXE}" ]; then
    printf '%s' "$THERMAL_KIOSK_EXE"
    return 0
  fi

  local candidate
  # deb cai vao /opt/<productName>/, AppImage thi nguoi dung dat o dau cung duoc.
  for candidate in \
    "/opt/Thermal & Biz Command Center/ThermalBiz" \
    /opt/Thermal*/ThermalBiz \
    "$HOME"/ThermalBiz-*.AppImage \
    "$HOME"/Downloads/ThermalBiz-*.AppImage
  do
    if [ -x "$candidate" ]; then
      printf '%s' "$candidate"
      return 0
    fi
  done

  # `command -v` cuoi cung: electron-builder tao symlink trong /usr/bin cho ban deb.
  command -v ThermalBiz 2>/dev/null || command -v thermalbiz 2>/dev/null
}

EXE="$(find_desktop_app || true)"

if [ -n "$EXE" ]; then
  echo "Dang mo ban desktop o che do kiosk toan man hinh..."
  echo "  $EXE"
  exec "$EXE" --kiosk
fi

echo "Khong tim thay ban desktop da cai."
echo "Mo trinh duyet o che do kiosk toi: $THERMAL_KIOSK_URL"
google-chrome --kiosk "$THERMAL_KIOSK_URL" \
  || chromium-browser --kiosk "$THERMAL_KIOSK_URL" \
  || firefox --kiosk "$THERMAL_KIOSK_URL"
