# ❄️🔥 THERMAL & BUSINESS EXECUTIVE COMMAND CENTER
### Hệ Thống Điều Hành Doanh Nghiệp Liên Ngành: Quản Trị Kinh Doanh &times; Công Nghệ Kỹ Thuật Nhiệt

---

## 📌 GIỚI THIỆU TỔNG QUAN

Dự án này là giải pháp **Trung tâm Điều hành Số Hợp nhất (Unified Executive Command Center)** được thiết kế chuyên biệt cho các doanh nghiệp hoạt động trong lĩnh vực **Kỹ thuật Nhiệt - Lạnh** (Kho lạnh bảo quản thủy hải sản/nông sản, hệ thống điều hòa không khí Chiller trung tâm, nhà máy cung cấp nhiệt/lò hơi công nghiệp).

Hệ thống kết nối trực tiếp hai huyết mạch của doanh nghiệp:
1. **Dòng dữ liệu Kỹ thuật Nhiệt (Thermal Telemetry):** Nhiệt độ phòng lạnh, áp suất bay hơi/ngưng tụ, công suất điện tiêu thụ ($kW$), hệ số hiệu quả làm lạnh $COP$.
2. **Dòng dữ liệu Quản trị & Tài chính (Business & P&L):** Doanh số theo thời gian thực, chi phí điện năng vận hành ($kWh \times \text{Đơn giá EVN}$), biên lợi nhuận gộp %, và phân tích tuổi nợ khách hàng (Aging Receivables).

---

## 💻 HỖ TRỢ ĐA NỀN TẢNG (CROSS-PLATFORM SUITE)

Hệ thống được đóng gói để chạy mượt mà trên tất cả các thiết bị:

| Nền tảng | Định dạng phần mềm | Mục đích sử dụng |
| :--- | :--- | :--- |
| **Windows PC** | `.exe` (Cài đặt installer & Bản portable không cần cài) | Màn hình máy tính làm việc của Ban Giám đốc & TV Kiosk phòng họp |
| **Linux** | `.AppImage` / `.deb` | Trạm vận hành xưởng máy hoặc máy chủ trung tâm Ubuntu/Debian |
| **Android** | `.apk` (Capacitor Android native) | Ban Lãnh đạo giám sát từ xa trên điện thoại Android |
| **iOS** | Xcode Project / PWA Web App native | Ban Lãnh đạo giám sát từ xa trên iPhone / iPad |
| **Web / TV Kiosk** | Responsive Web App | Hiển thị toàn màn hình trên Smart TV phòng chỉ huy |

---

## 🚀 HƯỚNG DẪN CÀI ĐẶT & CHẠY DỰ ÁN

### 1. Khởi chạy Cụm Cơ sở Dữ liệu & Grafana (Docker)
```bash
docker-compose up -d
```
- **PostgreSQL Database:** Cổng `5432` (Chứa sẵn schema và dữ liệu mẫu nhiệt & kinh doanh).
- **Grafana Dashboard:** Cổng `3000` (Tài khoản xem không cần mật khẩu).
- **Backend FastAPI:** Cổng `8000` (Tài liệu API tại `http://localhost:8000/docs`).

### 2. Chạy ứng dụng Dashboard Frontend (Chế độ Nhà phát triển)
```bash
cd frontend
npm install
npm run dev
```
Truy cập: `http://localhost:5173` để xem giao diện với đầy đủ nút chuyển đổi **PC Widescreen View** và **Mobile Smartphone View**.

---

## 📦 HƯỚNG DẪN ĐÓNG GÓI RA PHẦN MỀM (.EXE, LINUX, ANDROID, IOS)

### A. Đóng gói ra File `.exe` cho Windows & File cho Linux
```bash
cd frontend
# Đóng gói ra file cài đặt Windows (.exe)
npm run electron:build:win

# Đóng gói ra file Linux (.AppImage)
npm run electron:build:linux
```
*File `.exe` sẽ được tự động xuất ra trong thư mục `frontend/release/`.*

### B. Đóng gói ra Ứng dụng Di động (Android & iOS)
Hệ thống sử dụng **Capacitor**:
```bash
cd frontend
# 1. Build mã nguồn giao diện
npm run build

# 2. Đồng bộ mã nguồn sang Android / iOS
npx cap add android
npx cap add ios
npx cap sync

# 3. Mở Android Studio để xuất file .apk
npx cap open android

# 4. Mở Xcode trên macOS để xuất file .ipa cho iPhone
npx cap open ios
```

---

## 🔄 TỰ ĐỘNG HÓA CI/CD TRÊN GITHUB ACTIONS

Kho lưu trữ đã được tích hợp sẵn file cấu hình tự động: `.github/workflows/build-crossplatform.yml`.
Mỗi khi bạn đẩy mã nguồn lên GitHub, GitHub Actions sẽ tự động:
1. Dựng máy ảo Windows để biên dịch file **`.exe`**.
2. Dựng máy ảo Linux để biên dịch file **`AppImage`**.
3. Đóng gói file cài đặt và đưa vào mục **Releases / Artifacts** của GitHub để tải về dùng ngay mà không cần cài đặt các công cụ build nặng nề trên máy tính cá nhân.
