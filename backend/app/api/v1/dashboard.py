from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any
from app.services.cache import get_revenue_summary
from app.core.auth import authenticate_request as get_current_user

router = APIRouter()

@router.get("/dashboard/summary")
async def get_dashboard_summary(
    property_id: str,
    month: int = 3,
    year: int = 2024,
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    tenant_id = getattr(current_user, "tenant_id", None) or "default_tenant"

    revenue_data = await get_revenue_summary(property_id, tenant_id, month, year)

    return {
        "property_id": revenue_data["property_id"],
        "total_revenue": revenue_data["total"],
        "currency": revenue_data["currency"],
        "reservations_count": revenue_data["count"],
        "month": revenue_data.get("month", month),
        "year": revenue_data.get("year", year),
    }
