# KIẾN TRÚC HƯỚNG B: DỊCH VỤ NĂNG LƯỢNG TINH GỌN & CHO THUÊ KHO LẠNH (ESCO)
## Home Assistant (Local IoT) $\times$ Twenty (CRM) $\times$ Invoice Ninja (Billing) $\times$ Grafana
*(Tận dụng hệ sinh thái Client đa nền tảng Flutter có sẵn: Windows .exe, Linux, Android, iOS)*

---

## 1. MỤC TIÊU & BỐI CẢNH ỨNG DỤNG
Dành cho **Mô hình Dịch vụ Năng lượng (ESCO), Cho thuê phòng kho lạnh, Tòa nhà thương mại cho thuê điều hòa Chiller, Co-working / Bất động sản**:
- Cần đo đếm điện năng tiêu thụ ($kWh$) và nhiệt độ buồng lạnh cho từng khách thuê độc lập.
- Nhu cầu cốt lõi là **Lập hóa đơn tự động theo sản lượng tiêu thụ thực tế (Usage-based & Recurring Billing)** và thu hồi công nợ nhanh chóng.
- Đội ngũ quản lý cần ứng dụng di động (iOS, Android) và Desktop (.exe, Linux) gọn nhẹ, trực quan, không cồng kềnh như ERP truyền thống.

---

## 2. PHÂN CÔNG VAI TRÒ CÁC NỀN TẢNG MÃ NGUỒN MỞ

```mermaid
flowchart TD
    subgraph Edge["TẦNG 1: ĐO ĐẾM NĂNG LƯỢNG & MÔI TRƯỜNG"]
        Sensors["Công tơ điện tử Modbus/Zigbee, Cảm biến nhiệt ESPHome, Khóa thông minh"]
        Sensors -->|Zigbee / MQTT / LAN| HA["Home Assistant Core\n- Đọc kWh từng phòng kho lạnh\n- Giám sát nhiệt độ buồng\n- Điều khiển van điện / relay ngắt nguồn"]
    end

    subgraph Connector["TẦNG TRUNG GIAN TÍNH CƯỚC"]
        HA -->|REST API / State Polling| Bridge["HA-to-InvoiceNinja Metering Bridge\n(Tính kWh x Đơn giá điện)"]
    end

    subgraph Business["TẦNG 2: BÁN HÀNG & HÓA ĐƠN THU TIỀN"]
        Twenty["Twenty CRM\n(Quản lý Lead, Hợp đồng thuê kho)"]
        Bridge -->|REST API v1| Ninja["Invoice Ninja (Billing & Invoicing)\n- Tự động lập hóa đơn tiền điện/tiền lạnh\n- Cổng thanh toán trực tuyến (Client Portal)\n- Theo dõi công nợ quá hạn"]
    end

    subgraph Command["TẦNG 3: TRUNG TÂM CHỈ HUY SỐ BAN ĐIỀU HÀNH"]
        HA -->|PostgreSQL / InfluxDB| Grafana["Grafana Real-time TV Dashboard"]
        Ninja -->|MySQL Database Connection| Grafana
    end
```

---

## 3. CƠ CHẾ VẬN HÀNH THỰC TẾ

1. **Khách hàng ký hợp đồng:**
   - Nhân viên kinh doanh tạo khách hàng và hợp đồng thuê kho trên **Twenty CRM**.
   - Dữ liệu khách hàng tự động đồng bộ sang **Invoice Ninja**.
2. **Đo đếm chỉ số điện & nhiệt:**
   - **Home Assistant** đọc công tơ điện thông minh đo lường điện năng tiêu thụ ($kWh$) cho từng kho lạnh của từng khách hàng.
3. **Tự động xuất hóa đơn (Automated Usage-based Billing):**
   - Vào ngày 25 hàng tháng (hoặc chu kỳ định kỳ), `ha-to-invoiceninja connector` tự động lấy số $kWh$ từ Home Assistant:
     $$\text{Tiền điện} = \Delta kWh \times \text{Đơn giá điện EVN} + \text{Phí quản lý bảo quản lạnh}$$
   - Connector gọi API của **Invoice Ninja** tạo ngay hóa đơn điện tử và gửi link thanh toán trực tiếp qua email cho khách.
4. **Xử lý trễ hạn & Điều khiển phần cứng (Local Automation):**
   - Khách hàng có thể tra cứu hóa đơn và thanh toán online qua Client Portal của Invoice Ninja.
   - Nếu hóa đơn quá hạn $> 15$ ngày và khách không phản hồi $\rightarrow$ Invoice Ninja bắn webhook về Home Assistant kích hoạt còi cảnh báo hoặc tạm khóa quyền truy cập kho lạnh qua mã khóa cửa số.
5. **Màn hình Chỉ huy TV:**
   - Grafana hiển thị tổng doanh số cho thuê kho, tổng tiền điện EVN phải trả, tỷ lệ thanh toán đúng hạn và nhiệt độ của từng kho hàng.

---

## 4. BẢN QUYỀN & HỆ SINH THÁI CLIENT CÓ SẴN (WINDOWS, LINUX, ANDROID, IOS)
Điểm vượt trội của Hướng B là **không cần lập trình lại ứng dụng Client**:
- **Invoice Ninja** được xây dựng bằng **Flutter**: Cung cấp app native có sẵn cho Windows (`.exe`), Linux, Android (`.apk`), và iOS trên App Store.
- **Home Assistant** cung cấp app native chính thức: `Home Assistant Companion` hỗ trợ đầy đủ Windows, Android, iOS.
- **Grafana** hỗ trợ app di động chính thức trên Android/iOS và chế độ TV Kiosk trên PC.
