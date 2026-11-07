-- ============================================================================
-- THERMAL & BUSINESS EXECUTIVE COMMAND CENTER
-- MariaDB / MySQL Initial Schema & Seed Data
-- ============================================================================

-- 1. Bảng Dữ liệu Giám sát Kỹ thuật Nhiệt (Thermal Telemetry)
CREATE TABLE IF NOT EXISTS thermal_telemetry (
    id INT AUTO_INCREMENT PRIMARY KEY,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    equipment_code VARCHAR(30) NOT NULL,
    equipment_name VARCHAR(100) NOT NULL,
    temperature_c DECIMAL(5, 2) NOT NULL,
    pressure_bar DECIMAL(5, 2) NOT NULL,
    power_kw DECIMAL(7, 2) NOT NULL,
    cop_efficiency DECIMAL(4, 2) NOT NULL,
    status VARCHAR(20) DEFAULT 'RUNNING',
    INDEX idx_thermal_telemetry_timestamp (timestamp DESC),
    INDEX idx_thermal_telemetry_code (equipment_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. Bảng Doanh số Bán hàng & Dịch vụ Năng lượng (Business Revenue)
CREATE TABLE IF NOT EXISTS business_revenue (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_code VARCHAR(50) UNIQUE NOT NULL,
    order_date DATE DEFAULT (CURRENT_DATE),
    customer_name VARCHAR(150) NOT NULL,
    service_type VARCHAR(100) NOT NULL,
    volume_units DECIMAL(10, 2) NOT NULL,
    revenue_amount DECIMAL(15, 2) NOT NULL,
    electricity_cost DECIMAL(15, 2) NOT NULL,
    gross_margin_pct DECIMAL(5, 2) GENERATED ALWAYS AS (
        CASE WHEN revenue_amount > 0 THEN ROUND(((revenue_amount - electricity_cost) / revenue_amount) * 100, 2) ELSE 0 END
    ) STORED,
    INDEX idx_business_revenue_date (order_date DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. Bảng Quản trị Công nợ Khách hàng (Accounts Receivable & Aging Debt)
CREATE TABLE IF NOT EXISTS accounts_receivable (
    id INT AUTO_INCREMENT PRIMARY KEY,
    invoice_number VARCHAR(50) UNIQUE NOT NULL,
    customer_name VARCHAR(150) NOT NULL,
    issued_date DATE DEFAULT (CURRENT_DATE - INTERVAL 15 DAY),
    due_date DATE NOT NULL,
    total_amount DECIMAL(15, 2) NOT NULL,
    paid_amount DECIMAL(15, 2) DEFAULT 0,
    remaining_amount DECIMAL(15, 2) NOT NULL,
    status VARCHAR(20) DEFAULT 'UNPAID',
    INDEX idx_accounts_receivable_due (due_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. Bảng Cảnh báo Khẩn cấp (System Alerts)
CREATE TABLE IF NOT EXISTS system_alerts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    alert_type VARCHAR(50) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    message TEXT NOT NULL,
    is_resolved BOOLEAN DEFAULT FALSE,
    INDEX idx_system_alerts_created (created_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- SEED DATA
INSERT IGNORE INTO thermal_telemetry (equipment_code, equipment_name, temperature_c, pressure_bar, power_kw, cop_efficiency, status) VALUES
('KHO_DONG_01', 'Kho Đông Sâu Hải Sản 01 (-25°C)', -23.8, 1.85, 42.5, 3.85, 'RUNNING'),
('KHO_MAT_02', 'Kho Mát Nông Sản & Trái Cây 02 (+2°C)', 3.2, 3.40, 16.2, 4.20, 'RUNNING'),
('CHILLER_01', 'Trạm Chiller Trung Tâm Tòa Nhà', 6.8, 4.10, 68.0, 4.60, 'RUNNING'),
('LO_HOI_01', 'Lò Hơi Công Nghiệp Đốt Tầng Sôi 01', 178.5, 9.20, 110.0, 0.89, 'RUNNING'),
('KHO_CAP_DONG_03', 'Hầm Cấp Đông Gió Nhanh 03', -32.1, 1.45, 88.0, 3.20, 'WARNING');

INSERT IGNORE INTO business_revenue (order_code, customer_name, service_type, volume_units, revenue_amount, electricity_cost) VALUES
('ORD-2026-101', 'Công ty Thủy sản Biển Đông', 'Cấp đông nhanh hải sản xuất khẩu', 85.0, 125000000, 31250000),
('ORD-2026-102', 'Tập đoàn Nông nghiệp Hoàng Gia', 'Cho thuê kho lạnh nông sản', 250.0, 85000000, 17850000),
('ORD-2026-103', 'Chuỗi Cung Ứng Lạnh MegaCold', 'Bảo quản kem & sữa đặc biệt', 60.0, 54000000, 12960000),
('ORD-2026-104', 'Nhà máy Dệt May Tân Bình', 'Cung cấp hơi nóng công nghiệp', 120.0, 72000000, 28800000);

INSERT IGNORE INTO accounts_receivable (invoice_number, customer_name, due_date, total_amount, paid_amount, remaining_amount, status) VALUES
('INV-VN-2026-001', 'Công ty Thủy sản Biển Đông', CURRENT_DATE + INTERVAL 12 DAY, 125000000, 50000000, 75000000, 'PARTIALLY_PAID'),
('INV-VN-2026-002', 'Tập đoàn Nông nghiệp Hoàng Gia', CURRENT_DATE - INTERVAL 18 DAY, 85000000, 0, 85000000, 'UNPAID'),
('INV-VN-2026-003', 'Công ty Chế biến Thực phẩm An Phát', CURRENT_DATE - INTERVAL 48 DAY, 115000000, 0, 115000000, 'UNPAID'),
('INV-VN-2026-004', 'Hợp tác xã Rau Sạch Đà Lạt', CURRENT_DATE - INTERVAL 75 DAY, 42000000, 0, 42000000, 'UNPAID');

INSERT INTO system_alerts (alert_type, severity, message) VALUES
('THERMAL_WARNING', 'WARNING', 'Hầm Cấp Đông 03: Nhiệt độ tiệm cận ngưỡng giới hạn (-32.1°C), kiểm tra lưu lượng quạt dàn lạnh.'),
('OVERDUE_DEBT', 'CRITICAL', 'Cảnh báo nợ xấu: Khách hàng An Phát quá hạn thanh toán 48 ngày (115 triệu VNĐ).'),
('POWER_OPTIMIZATION', 'INFO', 'Hệ thống đã tự động chuyển đổi công suất máy nén sang khung giờ điện Thấp điểm để tiết kiệm 35% chi phí.');
