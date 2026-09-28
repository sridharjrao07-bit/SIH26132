# Judge Q&A

## How do you know the number is not invented?

The visible lane is seeded from the audited Lasalgaon example and the result is produced by the pure DirectLink engine. The backend contract and frontend integration tests exercise real response schemas; the browser run showed 48.1155% farmer share, ₹2,032.2147 avoidable margin, and ₹368.5753 real work. Rounded for presentation, these are 48.1%, ₹2,032, and ₹369.

## Are all intermediaries bad?

No. The UI explicitly separates margin from real work such as freight, handling, packaging, and loss. The claim is that avoidable margin can be reduced through coordinated direct trade, not that logistics has zero cost.

## Is the forecast accurate?

Not yet proven to a production standard. The current snapshot covers only August 2026; the honest holdout evaluation has negative aggregate R². The project keeps forecasting behind its gates and does not use it as the headline demo claim.

## What happens without internet or a database?

The deterministic rupee explanation runs without a database and is suitable for an offline local demo. Persistence, impact history, and external ingestion require configured services and are explicitly outside the critical stage path.

## Can this scale?

The pure calculation handled 40 concurrent requests at roughly 117 requests/sec in the local smoke test. That is a code-path signal, not a production capacity promise; deployment sizing, database load tests, and authenticated staging remain required.

## What is novel?

The product turns the price gap into an auditable value-chain explanation and an actionable direct-trade comparison, rather than only showing another price chart. It quantifies who receives each rupee and labels what is avoidable.

## What are the limitations?

The current demo is strongest for the explainable DirectLink flow. Forecast history is short, real persistence needs Supabase/Postgres, and CORS is intentionally limited to configured localhost origins.
