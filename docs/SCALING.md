# Scaling and Generalization Guide

Krishi Bazaar is currently implemented as a Deep Vertical prototype, intentionally constrained to Nashik and specific commodities (Onions, Tomatoes, Soybeans, Maize). This document outlines the roadmap for horizontal scaling, provides a worked example for onboarding a new region, and candidly acknowledges current limitations.

## How to Onboard a New District / Commodity

To add a new region and crop, no application code needs to change. The process is entirely data-driven via SQL migrations.

### Worked Example: Jalgaon Bananas

Jalgaon is famous for its bananas. To scale Krishi Bazaar to support Jalgaon banana farmers, we would execute the following SQL:

```sql
-- 1. Add the Commodity
INSERT INTO public.commodities (id, name_en, name_mr, name_hi, category, standard_unit, sanity_min, sanity_max)
VALUES (
    'e0000000-0000-0000-0000-000000000001',
    'Banana', 'केळी', 'केला', 'fruit', 'quintal',
    500.0, 5000.0 -- Rs/quintal sanity bounds
);

-- 2. Add Source Aliases for Ingestion
INSERT INTO public.commodity_alias (source, source_key, commodity_id)
VALUES
    ('data_gov_in', 'Banana', 'e0000000-0000-0000-0000-000000000001'),
    ('data_gov_in', 'Banana(Ripe)', 'e0000000-0000-0000-0000-000000000001');

-- 3. Add Jalgaon APMC
INSERT INTO public.markets (id, name, district, state, lat, lng, is_active)
VALUES (
    'f0000000-0000-0000-0000-000000000001',
    'Jalgaon APMC', 'Jalgaon', 'Maharashtra', 21.0077, 75.5626, true
);
```

After this migration, the ingestion worker will automatically begin fetching, validating, and normalizing Jalgaon banana prices into the `prices` table. The forecasting engine will automatically generate 7-day predictions once sufficient historical data points exist.

## What Generalizes Well

1.  **Ingestion & Validation**: The `PriceValidator` uses `commodity_alias` to map messy source strings to canonical UUIDs and normalizes unit variations to a standard quintal metric.
2.  **Multilingual Support**: Commodity names (`name_en`, `name_mr`, `name_hi`) are data-driven. The UI and SMS layers retrieve translations directly from the database without needing localization files updated.
3.  **Geo-spatial Routing**: The `/markets/nearby` RPC uses PostgreSQL's `earthdistance` extension to route logistics and storage requests universally based on coordinate proximity, agnostic to district boundaries.
4.  **Role-Based Security**: Row Level Security (RLS) policies dynamically adapt to new regions, safely isolating multi-tenant data independent of geographic scaling.

## Honest Limitations (What Does Not Yet Generalize)

As a prototype, several elements remain hardcoded or require significant refactoring to scale globally:

1.  **Language Fallbacks**: SMS templates and certain error messages fall back to Marathi as the default secondary language. Expanding beyond Maharashtra requires making the fallback chain dynamically configurable by state.
2.  **Unit Economics**: Hard assumptions exist around quintal metrics. Expanding to high-value spices (e.g., Saffron measured in grams) or bulk grains (e.g., Wheat in tonnes) may stretch the limits of the current `float` conversions in UI displays.
3.  **Transport Options**: Logistics currently assumes generic truck capacities (e.g., Pick-up, Mini Truck). Scaling to coastal/riverine or rail logistics requires a new data model for transit modes.
4.  **Payment Gateways**: The platform relies on a single generic bank transfer abstraction. Regional integration with state-specific payment systems or rural credit co-operatives is not yet supported.
