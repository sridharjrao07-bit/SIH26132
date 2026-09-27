# Project rules

- Keep all backend, database, forecasting, ingestion, and API-contract files unchanged; frontend redesign work is isolated to `web/` because the supplied backend behavior is production-critical.
- Preserve the Krishi Bazaar project name across the frontend; reusable semantic tokens and shared primitives in `web/src/styles/index.css` must be preferred over page-local visual values.
- Dashboard visualizations use Recharts with existing query responses only, preserving API contracts and keeping all analytics frontend-derived.
