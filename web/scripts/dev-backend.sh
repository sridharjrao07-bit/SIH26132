#!/usr/bin/env bash
# Boot the FastAPI app for local frontend work, so `npm run dev` has an /api to
# proxy to. The three Supabase values are JWT-shaped dummies: the app refuses to
# start without them, and nothing in the DirectLink rupee breakdown touches the
# database, so a real project is not needed to exercise it.
set -euo pipefail
cd "$(dirname "$0")/../.."          # repo root

export RUN_SCHEDULER=0
export RATE_LIMIT_ENABLED=0
export APP_ENV=development
export SUPABASE_URL=https://placeholder.supabase.co
export SUPABASE_ANON_KEY='eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJyb2xlIjoiYW5vbiIsImlzcyI6InN1cGFiYXNlIn0.abcdefghijklmnopqrstuvwxyz1234567890'
export SUPABASE_SERVICE_ROLE_KEY='eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJyb2xlIjoiYW5vbiIsImlzcyI6InN1cGFiYXNlIn0.abcdefghijklmnopqrstuvwxyz1234567890'
export SUPABASE_JWT_SECRET=ci-placeholder-jwt-secret-32b-min
export DATA_GOV_IN_API_KEY=placeholder-not-a-real-key

exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
