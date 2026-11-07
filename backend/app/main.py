"""
Executive Command Center - FastAPI Backend
Thermal Engineering x Business Administration
"""

import os
import asyncio
from datetime import date
from typing import List, Dict, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(
    title="Thermal & Business Command Center API",
    description="Real-time Executive Dashboard API combining Thermal Engineering & Business Management",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mock in-memory state with realistic engineering & business metrics
MOCK_THERMAL_DATA = [
    {
        "equipment_code": "KHO_DONG_01",
        "equipment_name": "Kho Đông Sâu Hải Sản 01 (-25°C)",
        "temperature_c": -23.8,
        "pressure_bar": 1.85,
        "power_kw": 42.5,
        "cop_efficiency": 3.85,
        "status": "RUNNING"
    },
    {
        "equipment_code": "KHO_MAT_02",
        "equipment_name": "Kho Mát Nông Sản & Trái Cây 02 (+2°C)",
        "temperature_c": 3.2,
        "pressure_bar": 3.40,
        "power_kw": 16.2,
        "cop_efficiency": 4.20,
        "status": "RUNNING"
    },
    {
        "equipment_code": "CHILLER_01",
        "equipment_name": "Trạm Chiller Trung Tâm Tòa Nhà",
        "temperature_c": 6.8,
        "pressure_bar": 4.10,
        "power_kw": 68.0,
        "cop_efficiency": 4.60,
        "status": "RUNNING"
    },
    {
        "equipment_code": "LO_HOI_01",
        "equipment_name": "Lò Hơi Đốt Tầng Sôi 01 (Hơi Nóng)",
        "temperature_c": 178.5,
        "pressure_bar": 9.20,
        "power_kw": 110.0,
        "cop_efficiency": 0.89,
        "status": "RUNNING"
    },
    {
        "equipment_code": "KHO_CAP_DONG_03",
        "equipment_name": "Hầm Cấp Đông Gió Nhanh 03",
        "temperature_c": -32.1,
        "pressure_bar": 1.45,
        "power_kw": 88.0,
        "cop_efficiency": 3.20,
        "status": "WARNING"
    }
]

MOCK_BUSINESS_DATA = {
    "today_revenue": 145200000,
    "mtd_revenue": 3480000000,
    "target_revenue": 4000000000,
    "electricity_cost_today": 38500000,
    "gross_margin_pct": 73.48,
    "total_volume_tons": 515.0,
    "recent_orders": [
        {"order_code": "ORD-101", "customer": "Công ty Thủy sản Biển Đông", "amount": 125000000, "service": "Cấp đông nhanh hải sản", "margin": 75.0},
        {"order_code": "ORD-102", "customer": "Tập đoàn Nông nghiệp Hoàng Gia", "amount": 85000000, "service": "Cho thuê kho lạnh nông sản", "margin": 79.0},
        {"order_code": "ORD-103", "customer": "Chuỗi Cung Ứng Lạnh MegaCold", "amount": 54000000, "service": "Bảo quản kem & sữa", "margin": 76.0},
        {"order_code": "ORD-104", "customer": "Nhà máy Dệt May Tân Bình", "amount": 72000000, "service": "Cung cấp hơi công nghiệp", "margin": 60.0}
    ]
}

MOCK_DEBT_DATA = {
    "total_receivables": 317000000,
    "overdue_debt": 242000000,
    "aging_breakdown": [
        {"bracket": "Trong hạn", "amount": 75000000, "color": "#10B981"},
        {"bracket": "1-30 ngày", "amount": 85000000, "color": "#F59E0B"},
        {"bracket": "31-60 ngày", "amount": 115000000, "color": "#EF4444"},
        {"bracket": ">60 ngày", "amount": 42000000, "color": "#991B1B"}
    ],
    "top_debtors": [
        {"customer": "Công ty Chế biến An Phát", "overdue_days": 48, "amount": 115000000, "status": "CRITICAL"},
        {"customer": "Tập đoàn Nông nghiệp Hoàng Gia", "overdue_days": 18, "amount": 85000000, "status": "WARNING"},
        {"customer": "Hợp tác xã Rau Đà Lạt", "overdue_days": 75, "amount": 42000000, "status": "DANGER"}
    ]
}

MOCK_ALERTS = [
    {"id": 1, "severity": "WARNING", "text": "Hầm Cấp Đông 03: Nhiệt độ tiệm cận ngưỡng -32.1°C, cần kiểm tra quạt gió dàn lạnh.", "time": "13:50"},
    {"id": 2, "severity": "CRITICAL", "text": "Cảnh báo nợ quá hạn: Khách hàng An Phát quá hạn 48 ngày (115 triệu VNĐ).", "time": "12:15"},
    {"id": 3, "severity": "INFO", "text": "Đã tự động chuyển đổi công suất Chiller sang khung giờ Thấp điểm (tiết kiệm 35% tiền điện).", "time": "11:00"}
]

@app.get("/api/health")
def health_check():
    return {"status": "ok", "system": "Thermal & Business Command Center", "version": "1.0.0"}

@app.get("/api/dashboard-summary")
def get_dashboard_summary():
    # Calculate thermal stats
    total_power = sum(item["power_kw"] for item in MOCK_THERMAL_DATA)
    avg_cop = round(sum(item["cop_efficiency"] for item in MOCK_THERMAL_DATA) / len(MOCK_THERMAL_DATA), 2)
    equipment_running = sum(1 for item in MOCK_THERMAL_DATA if item["status"] == "RUNNING")
    equipment_warning = sum(1 for item in MOCK_THERMAL_DATA if item["status"] == "WARNING")
    
    return {
        "business": MOCK_BUSINESS_DATA,
        "debts": MOCK_DEBT_DATA,
        "thermal_summary": {
            "total_power_kw": total_power,
            "avg_cop": avg_cop,
            "total_units": len(MOCK_THERMAL_DATA),
            "running": equipment_running,
            "warning": equipment_warning,
            "telemetry": MOCK_THERMAL_DATA
        },
        "alerts": MOCK_ALERTS
    }

@app.get("/api/thermal")
def get_thermal_telemetry():
    return MOCK_THERMAL_DATA

@app.get("/api/business")
def get_business_data():
    return MOCK_BUSINESS_DATA

@app.get("/api/debts")
def get_debts_data():
    return MOCK_DEBT_DATA

@app.get("/api/alerts")
def get_alerts():
    return MOCK_ALERTS

# WebSocket for live real-time simulation updates
@app.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await asyncio.sleep(3)
            # Send latest summary
            data = get_dashboard_summary()
            await websocket.send_json(data)
    except WebSocketDisconnect:
        pass
