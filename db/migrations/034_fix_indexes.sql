-- db/migrations/034_fix_indexes.sql
-- 1. Drop redundant index that is covered by the unique constraint uq_price_record
DROP INDEX IF EXISTS public.idx_prices_market_commodity_date;

-- 2. Create missing index for date-range queries on just arrival_date (e.g., backfill queries)
CREATE INDEX IF NOT EXISTS idx_prices_arrival_date ON public.prices (arrival_date DESC);

-- 3. Ensure forecasts has the correct index since we modified constraints in 033
CREATE INDEX IF NOT EXISTS idx_forecasts_market_commodity_date ON public.forecasts (market_id, commodity_id, forecast_date DESC);
