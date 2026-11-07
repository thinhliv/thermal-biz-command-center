"""
Connector A: ThingsBoard Alarm -> ERPNext Maintenance Request Bridge
Bridge service listening to ThingsBoard telemetry alarms and creating maintenance tickets in ERPNext.
"""

import os
import logging
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("TB_ERPNext_Bridge")

ERPNEXT_URL = os.getenv("ERPNEXT_URL", "http://erpnext:8000")
ERPNEXT_API_KEY = os.getenv("ERPNEXT_API_KEY", "mock_key")
ERPNEXT_API_SECRET = os.getenv("ERPNEXT_API_SECRET", "mock_secret")

app = FastAPI(
    title="ThingsBoard to ERPNext Maintenance Bridge",
    description="Captures IoT thermal alarms from ThingsBoard and auto-creates ERPNext Maintenance Requests"
)

class ThingsBoardAlarmPayload(BaseModel):
    alarm_id: Optional[str] = None
    device_name: str
    alarm_type: str                     # e.g., 'COP_DROP', 'BOILER_OVERHEAT', 'COMPRESSOR_VIBRATION'
    severity: str                       # 'CRITICAL', 'MAJOR', 'WARNING'
    details: Dict[str, Any] = {}

@app.get("/health")
def health():
    return {"status": "ok", "service": "thingsboard-erpnext-bridge"}

@app.post("/webhook/thingsboard-alarm")
def handle_thingsboard_alarm(payload: ThingsBoardAlarmPayload):
    """
    Receives Alarm payload from ThingsBoard Rule Engine Webhook Action
    and creates a Maintenance Request in ERPNext.
    """
    logger.info(f"Received IoT Alarm from ThingsBoard: {payload.device_name} - {payload.alarm_type} [{payload.severity}]")

    issue_subject = f"[IoT Alert] {payload.alarm_type} trên thiết bị {payload.device_name}"
    issue_description = (
        f"Cảnh báo tự động từ ThingsBoard Rule Engine:\n"
        f"- Thiết bị: {payload.device_name}\n"
        f"- Mức độ nghiêm trọng: {payload.severity}\n"
        f"- Chi tiết thông số: {payload.details}\n"
        f"Hành động yêu cầu: Kỹ thuật viên kiểm tra áp suất, hệ số COP và nhiệt độ máy."
    )

    # In production, call ERPNext REST API
    headers = {
        "Authorization": f"token {ERPNEXT_API_KEY}:{ERPNEXT_API_SECRET}",
        "Content-Type": "application/json"
    }

    erpnext_payload = {
        "doctype": "Issue",
        "subject": issue_subject,
        "raised_by": "iot-thingsboard@system.local",
        "description": issue_description,
        "priority": "High" if payload.severity in ["CRITICAL", "MAJOR"] else "Medium"
    }

    try:
        if ERPNEXT_API_KEY != "mock_key":
            response = requests.post(
                f"{ERPNEXT_URL}/api/resource/Issue",
                json=erpnext_payload,
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            created_issue = response.json()
            logger.info(f"Successfully created ERPNext Issue: {created_issue}")
            return {"status": "success", "erpnext_response": created_issue}
        else:
            # Standalone Simulation Mode
            logger.info(f"[SIMULATION] Mock ERPNext Issue created: '{issue_subject}'")
            return {
                "status": "simulated",
                "message": "ERPNext issue created in staging simulation mode",
                "data": erpnext_payload
            }
    except Exception as e:
        logger.error(f"Failed to push issue to ERPNext: {str(e)}")
        raise HTTPException(status_code=500, detail=f"ERPNext integration error: {str(e)}")
