# 3–5 minute SIH demo script

## Setup

Use the pinned Python 3.12 / Node 22 environment. Start the mock API on port 8000, the real backend on port 8001 with `web/scripts/dev-backend.sh`, and Vite with `VITE_API_BASE_URL=http://127.0.0.1:8001`. Open **http://localhost:5173/direct** (the hostname matters for CORS).

## Presentation flow

1. Open `/direct`. Say: “We are starting with a real Lasalgaon onion lane, not a fabricated dashboard.” Show farm-gate ₹2,226/qtl and retail ₹5,392/qtl.
2. Scroll through the five chain stages. Explain that each stage is split into margin (avoidable) and cost (real work), so the project does not label every rupee of logistics as profiteering.
3. Point to farmer share **48.1%**, avoidable margin **₹2,032**, and real work **₹369**.
4. Scroll to “What direct trade would pay.” Show farmer **₹3,663 / 64.5% more**, consumer **₹3,890 / 27.9% less**, and the new surplus.
5. Explain the safety boundary: this demo path is deterministic and explainable; forecasting is not presented as production-validated because the current history is too short.
6. Optional: open `/direct/rupee` to show the intentional 404 page, demonstrating that mistyped URLs are handled as a product state.

## Recovery

If Wi-Fi is unavailable, run the local mock/API stack and keep the `/direct` deterministic path. If the database is unavailable, do not open persistence/impact screens; the rupee explanation does not need a database. If the backend is down, restart the local service and reload; do not claim a successful live API response until the browser shows the values.
