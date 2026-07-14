# Loom Script — Property Revenue Dashboard Bug Fixes

**Assignment:** [ASSIGNMENT.md](./ASSIGNMENT.md)  
**Target length:** 6–8 minutes (max 10)  
**Scope:** The 3 reported client issues first; bonus findings only if time remains.

---

## What the assignment asks you to cover

1. What bugs you discovered and **how you found them**
2. The **root cause** of each issue
3. Your **fix** for each problem
4. A quick **demonstration** that the fixes work

---

## Setup before recording

```bash
cd New_devs_App-main
docker compose up --build -d
```

| Resource | URL |
|----------|-----|
| App | http://localhost:3000 |
| API docs | http://localhost:8000/docs |

| Client | Email | Password |
|--------|-------|----------|
| Sunset Properties (A) | `sunset@propertyflow.com` | `client_a_2024` |
| Ocean Rentals (B) | `ocean@propertyflow.com` | `client_b_2024` |

**Open these files in your editor before recording:**

1. `database/seed.sql`
2. `backend/app/services/cache.py`
3. `backend/app/services/reservations.py`
4. `backend/app/api/v1/dashboard.py`

---

## Part 1 — Intro (0:00–0:40)

**Say:**

> "I investigated the Property Revenue Dashboard after reports from Sunset Properties, Ocean Rentals, and our finance team. I logged in as both clients, traced the revenue flow from frontend → API → cache → database, and found three bugs in the existing code. I'll show how I found each one, the root cause, my fix, and a live demo."

**Show:** Dashboard at http://localhost:3000

---

## Part 2 — How I investigated (0:40–1:10)

**Say:**

> "I started by logging in as each client and comparing what the dashboard showed. Both tenants use the same property ID `prop-001`, but they're different properties. I checked the seed data, then followed the backend path: `dashboard.py` → `cache.py` → `reservations.py`."

**Show:** `database/seed.sql` lines 7–9

```sql
INSERT INTO properties (id, tenant_id, name, timezone) VALUES
    ('prop-001', 'tenant-a', 'Beach House Alpha', 'Europe/Paris'),
    ('prop-001', 'tenant-b', 'Mountain Lodge Beta', 'America/New_York'),
```

> "Same property ID, different tenants — important for the privacy bug."

---

## Bug 1 — Client B: Cross-tenant data on refresh (1:10–2:40)

**Reporter:** Ocean Rentals — *"Sometimes when we refresh, we see revenue that belongs to another company."*

### How I found it

**Say:**

> "I logged in as Sunset, viewed prop-001, then logged out and logged in as Ocean Rentals and viewed the same property. After a refresh, Ocean sometimes showed Sunset's revenue. That's the privacy issue Client B reported."

**Demo:**

1. Login as **Sunset** → prop-001 → note **$2,250.00**
2. Logout → login as **Ocean** → prop-001 → should be **$0.00** (not $2,250)

### Root cause

**Say:**

> "The Redis cache key only used `property_id`. Since both tenants share `prop-001`, Client B could get Client A's cached result for up to 5 minutes."

**File:** `backend/app/services/cache.py`

**Before (bug):**

```python
cache_key = f"revenue:{property_id}"
```

**After (fix) — line 19:**

```python
cache_key = f"revenue:{tenant_id}:{property_id}:{year}-{month:02d}"
```

### How I fixed it

**Say:**

> "I added `tenant_id` and the month/year to the cache key so each tenant gets isolated cache entries. I didn't change the caching pattern — just fixed the key to match how tenant isolation works elsewhere in the codebase."

### Demo fix works

**Say:**

> "Now Ocean always sees $0 for prop-001, even after Sunset loaded it first and I refresh."

---

## Bug 2 — Client A: March revenue mismatch (2:40–4:40)

**Reporter:** Sunset Properties — *"March totals don't match our internal records."*

### How I found it

**Say:**

> "Sunset said March totals didn't match their records. Their Beach House is in Paris. In the seed data there's a booking at Feb 29 23:30 UTC — that's March 1 in Paris. The dashboard was undercounting March."

**Show:** `database/seed.sql` lines 18–19

```sql
('res-tz-1', 'prop-001', 'tenant-a', '2024-02-29 23:30:00+00', '2024-03-05 10:00:00+00', 1250.000);
```

**Say:**

> "Wrong: **$1,000** — 3 bookings (UTC filtering excluded res-tz-1).  
> Correct: **$2,250** — 4 bookings (includes the Paris-local March check-in)."

### Root cause

**Say:**

> "Two problems in the existing code:
> 1. Revenue used naive UTC month boundaries instead of the property's timezone.
> 2. `calculate_monthly_revenue()` existed but was never wired to the dashboard — the API returned all-time totals while the UI said 'Monthly'."

**File:** `backend/app/services/reservations.py` lines 54–70

```python
property_tz = ZoneInfo(tz_row.timezone)
start_local = datetime(year, month, 1, tzinfo=property_tz)
...
  AND (check_in_date AT TIME ZONE :timezone) >= :start_local
  AND (check_in_date AT TIME ZONE :timezone) < :end_local
```

**File:** `backend/app/api/v1/dashboard.py` lines 8–17

```python
@router.get("/dashboard/summary")
async def get_dashboard_summary(
    property_id: str,
    month: int = 3,
    year: int = 2024,
    ...
    revenue_data = await get_revenue_summary(property_id, tenant_id, month, year)
```

### How I fixed it

**Say:**

> "I updated the existing `calculate_monthly_revenue()` to look up the property timezone from the database and filter check-ins in local time using SQL `AT TIME ZONE`. Then I connected the dashboard endpoint to call it with month/year params. I also fixed the database pool to use `DATABASE_URL` from docker-compose instead of missing Supabase settings, so queries hit Postgres instead of falling back to mock data."

**Related files:**

| File | Change |
|------|--------|
| `backend/app/core/database_pool.py` | Use `DATABASE_URL`; singleton `db_pool` |
| `backend/app/main.py` | Initialize pool once at startup |
| `backend/app/services/cache.py` | Call `calculate_monthly_revenue` instead of all-time total |

### Demo fix works

**Demo:** Login as **Sunset** → prop-001 → **USD 2,250.00**, **4 bookings**

---

## Bug 3 — Finance: Revenue off by cents (4:40–5:50)

**Reporter:** Finance team — *"Totals slightly off by a few cents."*

### How I found it

**Say:**

> "Finance reported totals slightly off. In seed data, prop-001 has amounts like 333.333 that sum to exactly 1000 in Postgres NUMERIC, but float conversion in the API can introduce drift."

**Show:** `database/seed.sql` lines 24–26

```sql
('res-dec-1', ..., 333.333),
('res-dec-2', ..., 333.333),
('res-dec-3', ..., 333.334),
```

### Root cause

**Say:**

> "Money was handled correctly as Decimal/NUMERIC in the database, but `dashboard.py` converted to float before returning JSON. Binary floats can't represent decimals like 333.333 exactly."

**Before (bug) in `backend/app/api/v1/dashboard.py`:**

```python
total_revenue_float = float(revenue_data['total'])
return { "total_revenue": total_revenue_float, ... }
```

**After (fix) — lines 19–26:**

```python
return {
    "property_id": revenue_data["property_id"],
    "total_revenue": revenue_data["total"],  # decimal string, e.g. "4975.50"
    "currency": revenue_data["currency"],
    "reservations_count": revenue_data["count"],
    "month": revenue_data.get("month", month),
    "year": revenue_data.get("year", year),
}
```

**Also:** `backend/app/services/reservations.py` lines 7–9 — `_quantize_currency()` keeps Decimal through aggregation.

### How I fixed it

**Say:**

> "I removed the float conversion and return the total as a decimal string. Aggregation stays in Decimal end-to-end, quantized to 2 decimal places before the response."

### Demo fix works

**Demo:** Sunset → prop-002 → **USD 4,975.50** (exact, no drift)

---

## Part 3 — Final demo (5:50–6:30)

**Say:**

> "Quick recap with both client accounts."

| Test | Expected result |
|------|-----------------|
| Sunset, prop-001, March | **$2,250.00**, 4 bookings |
| Ocean, prop-001, March | **$0.00**, 0 bookings |
| Sunset, prop-002, March | **$4,975.50** |
| Refresh after switching clients | No cross-tenant leakage |

---

## Part 4 — Close (6:30–7:00)

**Say:**

> "Summary: three bugs in existing code — cache key missing tenant_id, UTC instead of property timezone for March revenue, and float conversion on money values. I debugged and patched the existing services without rebuilding the system. All fixes verified with the provided client credentials. Thanks."

---

## Fix summary cheat sheet

| # | Reporter | Bug | Root cause | File(s) | Fix |
|---|----------|-----|------------|---------|-----|
| 1 | Client B (Ocean) | Wrong company's revenue after refresh | Cache key `revenue:{property_id}` — no tenant | `backend/app/services/cache.py:19` | `revenue:{tenant_id}:{property_id}:{year}-{month}` |
| 2 | Client A (Sunset) | March total wrong ($1,000 vs $2,250) | UTC month filter; timezone-edge booking excluded; monthly fn not wired | `reservations.py`, `cache.py`, `dashboard.py`, `database_pool.py` | Property timezone + `AT TIME ZONE`; wire monthly revenue; use `DATABASE_URL` |
| 3 | Finance | Cents off | `float()` on Decimal money | `dashboard.py:21`, `reservations.py:7-9` | Return decimal string; `_quantize_currency()` |

---

## Code locations quick reference

| Bug | File | Lines |
|-----|------|-------|
| Cache leak | `backend/app/services/cache.py` | 19 |
| Timezone query | `backend/app/services/reservations.py` | 54–70 |
| Seed data proof | `database/seed.sql` | 7–9, 18–19, 24–26 |
| Float fix | `backend/app/api/v1/dashboard.py` | 19–26 |
| Decimal handling | `backend/app/services/reservations.py` | 7–9, 86–91 |
| DB pool singleton | `backend/app/core/database_pool.py` | 55–56 |
| DB init at startup | `backend/app/main.py` | ~107–115 |

---

## Optional extras (only if under 8 min)

> "While testing I also found: dashboard property dropdown showed all tenants' properties — fixed in `frontend/src/components/Dashboard.tsx`. Profile page hit wrong API URL — fixed in `frontend/src/lib/apiBase.ts`. These weren't in the original reports but came up during investigation."

**Do not lead with these** — assignment wants the 3 client issues first.

---

## Pre-recording checklist

- [ ] `docker compose up --build -d` running
- [ ] Sunset → prop-001 → **$2,250.00**, 4 bookings
- [ ] Ocean → prop-001 → **$0.00**, 0 bookings (after Sunset cached)
- [ ] Sunset → prop-002 → **$4,975.50**
- [ ] Editor tabs open: seed.sql, cache.py, reservations.py, dashboard.py
- [ ] Both client logins work

---

## Recording tips

1. Use the same structure for every bug: **Found → Cause → Fix → Demo**
2. Spend ~70% on the 3 assignment bugs, ~30% on demo
3. When showing code, say **"before"** vs **"after"** — one screen per bug
4. Say **"debugging existing code"** once — addresses the "don't rebuild" note
5. If something fails live, fall back to http://localhost:8000/docs and show the JSON response

---

## Assignment alignment

| ASSIGNMENT.md requirement | Covered in |
|---------------------------|------------|
| Investigate by logging in as each client | Part 2 + Bug 1 & 2 demos |
| Identify bugs | Each bug: "How I found it" |
| Fix problems | Each bug: "How I fixed it" |
| Root cause of each issue | Each bug: "Root cause" |
| Demo fixes work | Part 3 final demo |
| 5–10 minutes | ~7 minutes |
| Do NOT rebuild system | Close: "patched existing services" |
| Test with provided credentials | Both clients in demo |
| Use existing structure | Fixed cache key, wired existing monthly fn |
