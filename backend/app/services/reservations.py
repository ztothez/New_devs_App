from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any
from zoneinfo import ZoneInfo


def _quantize_currency(amount: Decimal) -> str:
    """Round to 2 decimal places for display while preserving DB precision during aggregation."""
    return str(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


async def calculate_monthly_revenue(
    property_id: str,
    tenant_id: str,
    month: int,
    year: int,
) -> Dict[str, Any]:
    """
    Calculates revenue for a specific month using the property's local timezone.
    Reservations are attributed to a month based on check-in date in the property timezone.
    """
    try:
        from app.core.database_pool import db_pool
        from sqlalchemy import text

        if not db_pool.session_factory:
            await db_pool.initialize()

        if not db_pool.session_factory:
            raise Exception("Database pool not available")

        async with db_pool.session_factory() as session:
            tz_result = await session.execute(
                text(
                    """
                    SELECT timezone FROM properties
                    WHERE id = :property_id AND tenant_id = :tenant_id
                    """
                ),
                {"property_id": property_id, "tenant_id": tenant_id},
            )
            tz_row = tz_result.fetchone()
            if not tz_row:
                return {
                    "property_id": property_id,
                    "tenant_id": tenant_id,
                    "total": "0.00",
                    "currency": "USD",
                    "count": 0,
                    "month": month,
                    "year": year,
                }

            property_tz = ZoneInfo(tz_row.timezone)
            start_local = datetime(year, month, 1, tzinfo=property_tz)
            if month < 12:
                end_local = datetime(year, month + 1, 1, tzinfo=property_tz)
            else:
                end_local = datetime(year + 1, 1, 1, tzinfo=property_tz)

            query = text(
                """
                SELECT
                    SUM(total_amount) as total_revenue,
                    COUNT(*) as reservation_count
                FROM reservations
                WHERE property_id = :property_id
                  AND tenant_id = :tenant_id
                  AND (check_in_date AT TIME ZONE :timezone) >= :start_local
                  AND (check_in_date AT TIME ZONE :timezone) < :end_local
                """
            )

            result = await session.execute(
                query,
                {
                    "property_id": property_id,
                    "tenant_id": tenant_id,
                    "timezone": tz_row.timezone,
                    "start_local": start_local.replace(tzinfo=None),
                    "end_local": end_local.replace(tzinfo=None),
                },
            )
            row = result.fetchone()

            if row and row.total_revenue is not None:
                total_revenue = Decimal(str(row.total_revenue))
                return {
                    "property_id": property_id,
                    "tenant_id": tenant_id,
                    "total": _quantize_currency(total_revenue),
                    "currency": "USD",
                    "count": row.reservation_count,
                    "month": month,
                    "year": year,
                }

            return {
                "property_id": property_id,
                "tenant_id": tenant_id,
                "total": "0.00",
                "currency": "USD",
                "count": 0,
                "month": month,
                "year": year,
            }

    except Exception as e:
        print(f"Database error for {property_id} (tenant: {tenant_id}): {e}")
        return {
            "property_id": property_id,
            "tenant_id": tenant_id,
            "total": "0.00",
            "currency": "USD",
            "count": 0,
            "month": month,
            "year": year,
        }
