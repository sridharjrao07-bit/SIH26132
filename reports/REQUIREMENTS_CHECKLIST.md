# SIH requirements checklist

Problem statement: **“Multiple intermediaries reduce farmers earnings and increase consumer prices.”** Ministry of Consumer Affairs, Food & Public Distribution; Agriculture, FoodTech & Rural Development; Software.

| Requirement implied by the statement | Status | Evidence |
|---|---|---|
| Make the intermediary chain visible | Done | `/direct` renders five audited stages and a rupee allocation |
| Quantify farmer earnings | Done | Farmer share and direct farmer receipt are displayed |
| Quantify consumer price impact | Done | Traditional retail price and direct consumer price/saving are displayed |
| Distinguish avoidable margin from real logistics work | Done | Stage cards expose margin versus cost |
| Use an auditable calculation rather than a black-box number | Done | Pure DirectLink engine, schemas, contract tests, deterministic seeded lane |
| Connect real farmers/buyers and persist plans | Partial | API and fake-Supabase contracts exist; real DB credentials/staging were not available in this audit |
| Production-grade market forecasting | Partial | Framework exists; current snapshot does not support an accuracy claim |
| Resilient public demo | Done with conditions | PWA build, local fallback path, custom 404, documented two-port startup; use `localhost` for CORS |
