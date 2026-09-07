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
