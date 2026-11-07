"""
Connector B: Home Assistant Metering -> Invoice Ninja Usage Billing Bridge
Periodically polls energy sensors (kWh) from Home Assistant and creates draft invoices in Invoice Ninja.
"""

import os
import logging
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("HA_InvoiceNinja_Bridge")

HA_URL = os.getenv("HASS_URL", "http://homeassistant:8123")
HA_TOKEN = os.getenv("HASS_TOKEN", "mock_ha_token")

NINJA_URL = os.getenv("INVOICE_NINJA_URL", "http://invoiceninja:80")
NINJA_API_TOKEN = os.getenv("INVOICE_NINJA_TOKEN", "mock_ninja_token")

# EVN industrial average electricity rate in VND per kWh
ELECTRICITY_RATE_VND = float(os.getenv("ELECTRICITY_RATE_VND", "2500"))

app = FastAPI(
    title="Home Assistant to Invoice Ninja Metering Bridge",
    description="Automated Usage-based billing from Home Assistant IoT power meters into Invoice Ninja"
)

class BillingTriggerRequest(BaseModel):
    client_id: str                      # Invoice Ninja Client ID
    tenant_name: str
    sensor_entity_id: str               # e.g., 'sensor.kho_dong_01_energy_kwh'
    service_rate_per_kwh: float = 3500.0 # VND per kWh (including storage service fee)

@app.get("/health")
def health():
    return {"status": "ok", "service": "ha-invoiceninja-bridge"}

@app.post("/api/generate-invoice")
def generate_usage_invoice(req: BillingTriggerRequest):
    """
    Reads kWh consumption from Home Assistant and generates an invoice in Invoice Ninja.
    """
    logger.info(f"Generating usage invoice for tenant: {req.tenant_name}, reading sensor: {req.sensor_entity_id}")

    kwh_consumed = 0.0

    # Step 1: Read sensor from Home Assistant
    if HA_TOKEN != "mock_ha_token":
        try:
            ha_res = requests.get(
                f"{HA_URL}/api/states/{req.sensor_entity_id}",
                headers={"Authorization": f"Bearer {HA_TOKEN}"},
                timeout=5
            )
            ha_res.raise_for_status()
            state_data = ha_res.json()
            kwh_consumed = float(state_data.get("state", 0.0))
        except Exception as e:
            logger.warning(f"Could not reach Home Assistant, falling back to simulated reading: {e}")
            kwh_consumed = 1250.0 # Mock reading 1250 kWh
    else:
        kwh_consumed = 1250.0 # Mock 1250 kWh consumed

    total_amount = kwh_consumed * req.service_rate_per_kwh
    invoice_item = {
        "product_key": "COLD_STORAGE_ENERGY",
        "notes": f"Điện năng & dịch vụ bảo quản lạnh ({kwh_consumed} kWh x {req.service_rate_per_kwh:,.0f} đ/kWh)",
        "cost": req.service_rate_per_kwh,
        "quantity": kwh_consumed
    }

    # Step 2: Push invoice to Invoice Ninja API
    if NINJA_API_TOKEN != "mock_ninja_token":
        try:
            ninja_payload = {
                "client_id": req.client_id,
                "line_items": [invoice_item]
            }
            ninja_res = requests.post(
                f"{NINJA_URL}/api/v1/invoices",
                headers={
                    "X-Api-Token": NINJA_API_TOKEN,
                    "Content-Type": "application/json"
                },
                json=ninja_payload,
                timeout=10
            )
            ninja_res.raise_for_status()
            return {"status": "success", "invoice": ninja_res.json()}
        except Exception as e:
            logger.error(f"Error creating invoice in Invoice Ninja: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    else:
        # Simulation Mode
        logger.info(f"[SIMULATION] Created Invoice Ninja invoice for {req.tenant_name}: {total_amount:,.0f} VNĐ")
        return {
            "status": "simulated",
            "tenant": req.tenant_name,
            "kwh_metered": kwh_consumed,
            "total_vnd": total_amount,
            "line_item": invoice_item
        }
