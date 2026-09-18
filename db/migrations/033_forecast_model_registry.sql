-- db/migrations/033_forecast_model_registry.sql
-- 1. Create forecast_models registry to track available models
-- 2. Drop the restrictive uq_forecast constraint so we can keep history (insert instead of upsert)
-- 3. Add model_id to forecasts table
-- 4. Create an index to quickly fetch the latest forecast for a date/market/commodity

CREATE TABLE IF NOT EXISTS public.forecast_models (
    id uuid primary key default gen_random_uuid(),
    name text not null unique,
    description text,
    is_active boolean default true,
    created_at timestamptz not null default now()
);

-- Insert baseline models
INSERT INTO public.forecast_models (name, description) VALUES
('auto', 'Fallback auto-selected heuristic (Blend of MA and LR)'),
('feature_ols', 'Feature-engineered Ordinary Least Squares regression'),
('gbm', 'Gradient Boosting Machine model'),
('holt_winters', 'Holt-Winters exponential smoothing')
ON CONFLICT (name) DO NOTHING;

-- Alter forecasts table to add model_id
ALTER TABLE public.forecasts 
ADD COLUMN IF NOT EXISTS model_id uuid REFERENCES public.forecast_models(id);

-- Link existing forecasts to 'auto' model to maintain integrity
UPDATE public.forecasts 
SET model_id = (SELECT id FROM public.forecast_models WHERE name = 'auto') 
WHERE model_id IS NULL;

-- Drop the old unique constraint to allow revision history (multiple generated_at for the same forecast_date)
ALTER TABLE public.forecasts DROP CONSTRAINT IF EXISTS uq_forecast;

-- Add a new unique constraint that includes generated_at and model_id to prevent exact duplicates 
-- but allow new runs on the same date to be stored
ALTER TABLE public.forecasts ADD CONSTRAINT uq_forecast_revision 
UNIQUE (market_id, commodity_id, forecast_date, model_id, generated_at);

-- Create an index to support fetching the "latest" forecast efficiently
CREATE INDEX IF NOT EXISTS idx_forecasts_history 
ON public.forecasts (market_id, commodity_id, forecast_date, generated_at DESC);
