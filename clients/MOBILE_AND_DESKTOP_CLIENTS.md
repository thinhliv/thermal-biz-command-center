# HƯỚNG DẪN ỨNG DỤNG ĐA NỀN TẢNG (CLIENT SUITE)
## Windows (.exe), Linux, Android (.apk) và iOS

Hệ sinh thái này tận dụng các ứng dụng Client native chính thức và sẵn có của các nền tảng mở mà không cần viết lại từ đầu:

---

## 1. INVOICE NINJA CLIENT (FLUTTER ENGINE NATIVE)
Invoice Ninja sử dụng mã nguồn **Flutter** cho toàn bộ ứng dụng Client:
- **Kho mã nguồn Client:** `https://github.com/invoiceninja/admin-portal`
- **Windows PC (`.exe`):**
  - Tải file cài đặt `.msi` hoặc `.exe` chính thức: [Invoice Ninja Desktop Releases](https://github.com/invoiceninja/admin-portal/releases)
  - Hoặc tự build từ source: `flutter build windows` (Tạo ra file `.exe` tại `build/windows/runner/Release/`).
- **Linux (`.AppImage` / Snap):**
  - Tải file `.tar.gz` hoặc snap: `sudo snap install invoiceninja`
  - Hoặc tự build: `flutter build linux`.
- **Android (`.apk`):**
  - Cài đặt từ Google Play Store: Tìm *"Invoice Ninja v5"*
  - Hoặc tải trực tiếp file APK từ GitHub Releases.
- **iOS (iPhone/iPad):**
  - Cài đặt từ Apple App Store: *"Invoice Ninja v5"*.
- **Kết nối về máy chủ:** Khi mở ứng dụng lần đầu, chỉ cần nhập URL máy chủ của anh (ví dụ: `http://localhost:8088` hoặc qua domain/IP tĩnh) và API Token.

---

## 2. HOME ASSISTANT COMPANION APPS (LOCAL IOT)
Home Assistant sở hữu bộ ứng dụng native hàng đầu thế giới:
- **Windows & Linux Desktop:**
  - Tải app desktop: [Home Assistant Desktop Releases](https://github.com/j-ha/home-assistant-desktop/releases)
- **Android:**
  - App *"Home Assistant"* trên CH Play hoặc file APK từ [GitHub](https://github.com/home-assistant/android/releases).
- **iOS:**
  - App *"Home Assistant"* trên Apple App Store.

---

## 3. GRAFANA EXECUTIVE TV KIOSK & MOBILE
Trung tâm Điều hành TV của Ban Giám đốc:
- **Màn hình TV / PC Kiosk Mode:**
  - Chạy file script: [`clients/desktop-kiosk/launch-kiosk.bat`](launch-kiosk.bat)
  - Script sẽ tự động bật trình duyệt ở chế độ Fullscreen Kiosk (không thanh địa chỉ, không viền) trỏ thẳng vào Dashboard:
    - Hướng A: `http://localhost:3000/d/industrial-thermal-erpnext?kiosk`
    - Hướng B: `http://localhost:3000/d/esco-invoiceninja-cockpit?kiosk`
- **Mobile Smartphone:**
  - Cài đặt ứng dụng **Grafana** chính thức trên iOS App Store và Android Google Play.
  - Hoặc mở trình duyệt trên điện thoại $\rightarrow$ Chọn **"Add to Home Screen"** để dùng như một ứng dụng Native toàn màn hình.

---

## 4. ERPNEXT MOBILE & DESK
- **ERPNext Desk:** Chạy mượt mà trên trình duyệt web PC.
- **ERPNext Mobile App:** Có sẵn trên Google Play và App Store (hoặc thông qua Frappe Mobile Framework).
