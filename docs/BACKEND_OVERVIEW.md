# Krishi Bazaar (SIH26132) Backend Overview

This document provides a comprehensive, deep-dive architectural explanation of the Krishi Bazaar backend. It outlines the technologies used, the security posture, core modules, and the distinct background engines that power the marketplace.

---

## 1. High-Level Architecture & Stack

- **Framework**: FastAPI (Python 3.12). Selected for asynchronous capabilities and Pydantic validation.
- **Database**: PostgreSQL (hosted via Supabase).
- **Authentication**: JWT-based via Supabase Auth.
- **Data Access Layer**: Supabase Python Client (PostgREST wrapper).
- **Testing**: `pytest` with `respx` for HTTP mocking and comprehensive test fakes simulating RLS locally.

The backend operates as a modular monolith. It serves a RESTful JSON API via FastAPI while housing standalone background worker scripts (cron tasks) for data ingestion, price forecasting, and notifications.

---

## 2. Zero-Trust Security Posture (RLS)

The backend utilizes a **"Thick Database, Thin API"** approach to security.

1. **Row-Level Security (RLS)**: `app/deps.py` intercepts the incoming JWT and constructs a user-scoped `supabase` client for every request, so PostgREST executes as the authenticated role and RLS policies apply server-side. Ownership is additionally asserted in application code: eleven router queries carry explicit `.eq("user_id", …)` filters (`alerts.py`, `grievances.py`, `logistics.py`, `lots.py`, `offers.py`, `payments.py`, `storage.py`) as defence-in-depth, so a policy regression cannot silently expose another user's rows.
2. **Database Hard Boundary**: When FastAPI makes a query using that scoped client, PostgreSQL's native RLS policies intercept the execution, silently dropping any rows the `authenticated` user does not own.
3. **Fail-Closed Guard**: `app/startup_checks.py` validates the environment on boot. If the application is set to mock RLS locally (`AUTH_DB_ENFORCEMENT=app`), the server will explicitly refuse to start in a production environment.
4. **RPC State Machines**: High-risk state transitions (like confirming a payment or advancing a logistics step) are pushed entirely into PostgreSQL as `SECURITY DEFINER` RPCs (e.g., `transition_payment_status`). These functions enforce explicit ownership constraints (`auth.uid() = p_user_id`) natively, guaranteeing that no rogue endpoint logic can bypass the rules.

---

## 3. The FastAPI Domain (Routers)

The core API is split across several domain-specific routers inside `app/routers/`:

- **`profile.py` & `buyers.py`**: Handles user identity. Includes a self-service registration flow for institutional buyers that dictates they remain restricted until an Admin explicitly verifies them.
- **`lots.py` & `offers.py`**: The fundamental marketplace. Farmers list inventory (`lots`), and buyers submit bids (`offers`).
- **`payments.py` & `grievances.py`**: Workflows tracking the post-matching financial lifecycle and dispute resolution process. 
- **`logistics.py` & `matching.py`**: Automates supply chain assignments. Geospatial proximity search (`GET /markets/nearby`) uses the PostgreSQL `earthdistance` extension via RPC; logistics assignment itself is not distance-routed.
- **`storage.py`**: Manages warehouse and cold-storage bookings as first-class resources, enforcing physical capacity constraints before confirming requests.
- **`prices.py` & `forecasts.py`**: Exposes real-time ingestion data and AI-driven 7-day predictive pricing.

---

## 4. Background Engines

Beyond the REST API, the repository houses three autonomous background processes, typically executed via cron or task schedulers:

### A. Ingestion Engine (`ingestion/`)
An automated ETL pipeline that updates real-time commodity prices.
- **Crawlers**: Fetches live APMC (Mandi) prices from external sources (e.g., `data.gov.in` and `agmarknet`).
- **Validation**: Enforces strict unit consistency constraints (e.g., `MAX_ARRIVAL_QTY_QTL`) to prevent corrupted unit dimensions (like kilograms mistakenly ingested as tonnes) from polluting the dataset.
- **Deduplication**: Merges overlapping sources using a strict precedence ranking (Government API > Scraped > Manual).

### B. Forecasting Engine (`forecasting/`)
A lightweight, dependency-free statistical inference engine executing in pure Python.
- **Methodology**: It blends a short-term Moving Average (7-day window) with an Ordinary Least Squares (OLS) linear regression fitted over a 30-day lookback window.
- **Resiliency**: Calendar-aware gaps (like market holidays) are mathematically smoothed.
- **Tiered Confidence**:
  - `n < 10` observations: Skipped entirely (Insufficient Data).
  - `n = 10-14`: Defaults to purely Moving Average modeling (Medium Confidence).
  - `n > 15`: Triggers the MA + OLS Blend (High Confidence).

### C. Notification Engine (`notifications/`)
A scalable worker evaluating threshold limits to send alerts.
- **`alert_checker.py`**: Scans the database for user-defined triggers (e.g., "SMS me when Onion prices in Nashik cross ₹2,000/qtl"). 
- **`sale_window.py`**: Evaluates optimal sale windows based on the latest forecasting engine outputs.
- **`sms_gateway.py`**: A generic abstraction layer designed to plug into enterprise gateways like Twilio or NIC SMS.
