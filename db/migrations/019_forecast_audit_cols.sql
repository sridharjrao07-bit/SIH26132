-- db/migrations/019_forecast_audit_cols.sql
-- Add audit columns to forecasts table for ML traceability

ALTER TABLE public.forecasts
ADD COLUMN IF NOT EXISTS model_version TEXT,
ADD COLUMN IF NOT EXISTS features_used JSONB;
