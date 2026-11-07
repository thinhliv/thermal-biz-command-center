# ❄️🔥 THERMAL & BUSINESS EXECUTIVE COMMAND CENTER
### Hệ Thống Điều Hành Doanh Nghiệp Liên Ngành: Quản Trị Kinh Doanh &times; Công Nghệ Kỹ Thuật Nhiệt

Dự án tích hợp và tối ưu hóa năng lực của **7 nền tảng mã nguồn mở hàng đầu thế giới** thành hai bộ giải pháp kiến trúc hoàn chỉnh, phục vụ cho các doanh nghiệp hoạt động trong lĩnh vực **Kỹ thuật Nhiệt - Lạnh** (Kho lạnh bảo quản, Trạm Chiller điều hòa trung tâm, Lò hơi công nghiệp, Cho thuê kho và Dịch vụ năng lượng ESCO).

---

## 📌 BẢN ĐỒ KHAI THÁC 7 NỀN TẢNG MÃ NGUỒN MỞ

| Nền tảng | Kho mã nguồn GitHub | Tầng kiến trúc | Vai trò chính xác trong hệ thống |
| :--- | :--- | :--- | :--- |
| **ThingsBoard** | [thingsboard/thingsboard](https://github.com/thingsboard/thingsboard) | **IIoT & SCADA** | Thu thập telemetry nhiệt độ, áp suất, công suất điện kW, độ rung máy nén; Rule Engine kích hoạt Alarm khi $COP < 3.2$. |
| **Home Assistant** | [home-assistant/core](https://github.com/home-assistant/core) | **Local IoT & Metering** | Đọc công tơ điện thông minh theo từng kho buồng, cảm biến môi trường tòa nhà, điều khiển van ngắt nguồn. |
| **ERPNext** | [frappe/erpnext](https://github.com/frappe/erpnext) | **ERP Toàn Diện** | Quản lý kho lạnh (WMS), tự động tạo Lệnh bảo trì máy (Maintenance Work Order) khi IoT báo quá nhiệt, kế toán giá thành. |
| **Odoo** | [odoo/odoo](https://github.com/odoo/odoo) | **ERP Thay Thế** | Lựa chọn thay thế cho ERPNext khi doanh nghiệp cần hệ sinh thái App thương mại điện tử, POS và bán lẻ rộng lớn. |
| **Twenty** | [twentyhq/twenty](https://github.com/twentyhq/twenty) | **CRM Bán Hàng** | Quản lý danh sách khách hàng thuê kho lạnh, theo dõi hợp đồng cung cấp nhiệt/lạnh, phễu chốt deal B2B. |
| **Invoice Ninja** | [invoiceninja/invoiceninja](https://github.com/invoiceninja/invoiceninja) | **Billing & Invoicing** | Tự động xuất hóa đơn dựa trên số đo điện/nhiệt thực tế (Usage-based Billing), cổng thanh toán trực tuyến, quản trị công nợ. |
| **Grafana** | [grafana/grafana](https://github.com/grafana/grafana) | **Command Center** | Hợp nhất dữ liệu IoT và Tài chính lên màn hình TV của Ban Giám đốc; tự động làm mới thời gian thực (Kiosk Mode). |

---

## 🏗️ HAI BỘ GIẢI PHÁP KIẾN TRÚC TRIỂN KHAI

### 🔹 HƯỚNG A: DOANH NGHIỆP CÔNG NGHIỆP & CHUỖI KHO LẠNH LỚN
> **ThingsBoard (IIoT) $\times$ ERPNext (ERP & Bảo trì) $\times$ Grafana (Chỉ huy TV)**
- **Bối cảnh:** Nhà máy chế biến, kho bảo quản âm sâu ($-25^\circ\text{C}$ đến $-35^\circ\text{C}$), trạm Chiller cỡ lớn, lò hơi công nghiệp.
- **Điểm nhấn:** Thu thập dữ liệu SCADA từ PLC qua MQTT $\rightarrow$ Tự động sinh phiếu sửa chữa máy móc và xuất kho linh kiện thay thế trên ERPNext.
- **Tài liệu chi tiết:** [architecture/ARCHITECTURE_A_ENTERPRISE.md](architecture/ARCHITECTURE_A_ENTERPRISE.md)
- **Lệnh khởi chạy 1-click:**
  ```bash
  docker-compose -f docker/docker-compose.enterprise.yml up -d
  ```

---

### 🔹 HƯỚNG B: DỊCH VỤ NĂNG LƯỢNG TINH GỌN & CHO THUÊ KHO (ESCO)
> **Home Assistant (Local IoT) $\times$ Twenty (CRM) $\times$ Invoice Ninja (Billing) $\times$ Grafana**
- **Bối cảnh:** Cho thuê phòng kho lạnh theo buồng, đo đếm điện năng điều hòa tòa nhà, bán hơi nhiệt công nghiệp theo sản lượng.
- **Điểm nhấn:** Home Assistant đo công tơ $kWh$ $\rightarrow$ Connector B tự động tính tiền điện theo khung giờ EVN $\rightarrow$ Invoice Ninja tự động xuất hóa đơn gửi khách hàng.
- **Tài liệu chi tiết:** [architecture/ARCHITECTURE_B_LIGHTWEIGHT.md](architecture/ARCHITECTURE_B_LIGHTWEIGHT.md)
- **Lệnh khởi chạy 1-click:**
  ```bash
  docker-compose -f docker/docker-compose.lightweight.yml up -d
  ```

---

## 📱 HỆ SINH THÁI CLIENT ĐA NỀN TẢNG (WINDOWS .EXE, LINUX, ANDROID, IOS)

Không cần code lại từ đầu, hệ thống tận dụng các ứng dụng native chính thức:

| Nền tảng | Ứng dụng Quản trị & Hóa đơn (Invoice Ninja) | Ứng dụng IoT & Đo đếm (Home Assistant) | Màn hình Điều hành (Grafana) |
| :--- | :--- | :--- | :--- |
| **Windows PC** | File **`.exe`** (Flutter native) | Home Assistant Desktop | Browser TV Kiosk Mode (`launch-kiosk.bat`) |
| **Linux** | File **`.AppImage`** / Snap | Home Assistant Linux Desktop | Browser Kiosk (`launch-kiosk.sh`) |
| **Android** | File **`.apk`** / Google Play | App "Home Assistant" trên CH Play | App "Grafana" trên CH Play |
| **iOS** | App Store (iPhone / iPad) | App "Home Assistant" trên App Store | App "Grafana" trên App Store |

👉 *Xem hướng dẫn chi tiết cách tải và kết nối tại:* [clients/MOBILE_AND_DESKTOP_CLIENTS.md](clients/MOBILE_AND_DESKTOP_CLIENTS.md).

---

## ⚡ HƯỚNG DẪN ĐIỀU KHIỂN NHANH (POWERSHELL / BASH)

Trên Windows, sử dụng script điều phối `run.ps1`:
```powershell
# 1. Khởi chạy Hướng A (ThingsBoard + ERPNext + Grafana)
.\run.ps1 -Action Enterprise

# 2. Khởi chạy Hướng B (Home Assistant + Invoice Ninja + Grafana)
.\run.ps1 -Action Lightweight

# 3. Mở màn hình TV Kiosk không viền toàn màn hình cho Ban Giám đốc
.\run.ps1 -Action Kiosk

# 4. Dừng toàn bộ các container
.\run.ps1 -Action Stop
```

---

## 📂 CẤU TRÚC THƯ MỤC DỰ ÁN

```
thermal-biz-command-center/
├── architecture/
│   ├── ARCHITECTURE_A_ENTERPRISE.md       # Thiết kế kỹ thuật Hướng A (ThingsBoard + ERPNext)
│   └── ARCHITECTURE_B_LIGHTWEIGHT.md      # Thiết kế kỹ thuật Hướng B (HA + Invoice Ninja + Twenty)
├── docker/
│   ├── docker-compose.enterprise.yml      # Cụm container Hướng A
│   ├── docker-compose.lightweight.yml     # Cụm container Hướng B
│   └── env.sample                         # Mẫu cấu hình cổng và secret keys
├── connectors/
│   ├── thingsboard-to-erpnext/            # Cầu nối: Alarm IoT -> Phiếu bảo trì ERPNext
│   └── ha-to-invoiceninja/                # Cầu nối: Số đo kWh -> Hóa đơn Invoice Ninja
├── grafana/
│   ├── provisioning/                      # Cấu hình tự động nạp Datasource và Dashboard
│   └── dashboards/
│       ├── industrial_thermal_erpnext.json # Dashboard TV Hướng A
│       └── esco_billing_invoiceninja.json  # Dashboard TV Hướng B
├── clients/
│   ├── desktop-kiosk/                     # File kích hoạt TV Kiosk cho Windows & Linux
│   └── MOBILE_AND_DESKTOP_CLIENTS.md      # Hướng dẫn setup client Windows, Linux, Android, iOS
├── database/                              # SQL Schema & Seed Data cho Kỹ thuật Nhiệt & Kinh doanh
├── run.ps1                                # Script điều phối 1-click
└── README.md                              # Tài liệu tổng thể
```
