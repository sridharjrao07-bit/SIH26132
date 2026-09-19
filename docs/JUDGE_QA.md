# Anticipated Judge Q&A

This document contains candid answers to the hardest questions we anticipate from the hackathon judges regarding the architecture, design choices, and limitations of the Krishi Bazaar platform.

### 1. "You used Supabase for auth and database. Isn't that vendor lock-in? Why didn't you build a custom backend?"

**Answer**: Yes, there is some vendor lock-in, but it is heavily mitigated by Supabase being built entirely on open-source PostgreSQL. By pushing our core business logic into PostgreSQL (via Row Level Security and PL/pgSQL RPCs), we are locking ourselves into the *SQL standard* and PostgreSQL ecosystem, rather than proprietary NoSQL APIs. We can export our schema and data via standard `pg_dump` and migrate to any managed PostgreSQL provider (AWS RDS, GCP Cloud SQL) at any time. We chose this architecture to maximize delivery speed during the hackathon, focusing on building agri-tech features rather than reinventing authentication and ORM boilerplate.

### 2. "Your integration tests use a `FakeSupabase` in memory instead of spinning up a real test database. Doesn't this mean your tests are lying to you?"

**Answer**: This is a known risk of mock-based testing. However, we have designed `FakeSupabase` to meticulously enforce PostgreSQL's Row Level Security (RLS) constraints in memory. Our test suite forces every endpoint to resolve the caller's role and strictly applies ownership filters before returning data. Furthermore, we maintain a separate live testing gate (`KB_LIVE_SUPABASE=1`) to perform automated smoke tests against a real staging database to catch cross-tenant leaks or query malformations that the in-memory fake might miss. The trade-off grants us sub-second test suite execution times, enabling rapid local iteration.

### 3. "How do you know your data is fresh and trustworthy? Scrapers break all the time."

**Answer**: We do not blindly trust the scrapers. We implemented a robust `ingestion_log` table that acts as our heartbeat monitor. Every pipeline run logs exactly how many records were seen, written, and rejected. Crucially, our `PriceValidator` enforces strict sanity bounds on per-commodity prices and arrival quantities. If a scraper hallucinates that onions are Rs. 100,000 per quintal, it is rejected and audited, preventing database poisoning. Additionally, our forecast engine marks predictions as `stale` if recent price data is unavailable, ensuring farmers aren't misled by outdated insights.

### 4. "You added warehousing/logistics, but are you actually verifying physical capacity in real-time?"


**Answer**: Our current capacity check is a strong database-enforced invariant: we calculate a godown's remaining capacity by summing all `confirmed` storage bookings and rejecting any new booking that exceeds the total physical capacity. However, this relies entirely on the platform being the single source of truth for the godown's inventory. In a real-world scenario where farmers show up offline or use other booking systems, our digital ledger would drift from physical reality. Future iterations require an API integration with godown management systems or a dedicated partner portal to reconcile physical stock daily.

### 5. "What stops a bad actor from scraping the entire farmer database?"

**Answer**: We employ a multi-layered defense. First, our PostgreSQL RLS policies strictly isolate `user_profiles`, ensuring that a farmer can only ever query their own profile; even authenticated peers cannot see each other's phone numbers or locations. Second, the API is rate-limited at the Gateway layer to prevent brute-force enumeration. Third, our integration tests explicitly contain cross-tenant canary assertions that deliberately attempt to read another user's data, ensuring that any accidental regression in our RLS policies causes an immediate CI failure.

### 6. "Your app runs everything in-process. How does this scale if you get thousands of concurrent users?"

**Answer**: For this hackathon, we accepted a hard architectural limitation: our system uses an in-memory rate limiter and an in-process APScheduler, which forces us into a single-worker/single-replica deployment model. This ensures our background tasks (like outbound SMS capping) and rate limiting function correctly without complex distributed state. To scale horizontally in production, we would need to introduce Redis or a similar external store for job locking and distributed rate limiting to safely run multiple replicas.

### 7. "Generative AI is trendy. Why didn't you just ask an LLM to predict tomorrow's onion price?"

**Answer**: Because LLMs are fundamentally incapable of robust, deterministic time-series forecasting. They hallucinate numbers and cannot reliably model complex multivariate variance over time. Instead, our single most important rule is **the LLM never predicts a number**. We restrict the LLM to what it excels at: extracting structured intelligence (events, direction, magnitude, confidence) from unstructured news and policy text. This deterministic event data is then fed as a structured feature (`event_pressure`) into classical statistical and gradient-boosting models that actually compute the numerical forecast.

### 8. "How does your model actually work under the hood?"

**Answer**: Our forecasting engine uses an ensemble approach. For baseline stability, we use a classic Moving Average (MA) model. For our primary predictions, we use a feature-based Ordinary Least Squares (OLS) model (and optionally LightGBM for complex non-linear relationships) that trains on a wide matrix of signals. This matrix incorporates historical prices, district-level arrival volumes, cumulative weather data (e.g., 7-day rainfall and temperature), and the LLM-extracted market event pressure. We use Gaussian elimination to drop features with zero variance before training, ensuring the model remains mathematically sound even during data droughts.

### 9. "Most hackathon projects just hardcode an accuracy metric like '95% accurate'. How do we know your model actually works?"

**Answer**: We reject static accuracy claims. Instead, we built a rigorous walk-forward backtesting harness directly into the backend. It trains the model on a bounded historical window, predicts the next 7 days, and then steps forward in time, strictly preventing data leakage from the future into the training set. It repeats this across 8 folds of 7 days over the last 56 days. The result is an honest "accuracy card" that quantifies the Mean Absolute Percentage Error (MAPE) against real, out-of-sample holdout data.

### 10. "What happens if a data source goes down, like the government mandi portal?"

**Answer**: The forecasting engine is designed with "kill-gates" and fallback mechanisms. If the primary price feed goes down, the `FeatureOLS` model gracefully degrades. If weather data or event data lacks variance (e.g., no recent news or identical precipitation values), the feature is dynamically dropped from the training matrix to prevent singular matrix errors. We also ensure that no forecast is served if it is older than 48 hours, preventing farmers from making decisions based on stale or missing data.
