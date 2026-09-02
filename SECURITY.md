# Security

## Reporting

Do **not** open a public issue for a vulnerability that exposes farmer PII, JWTs, or the service-role key. Email the maintainers or use a private GitHub security advisory.

## Non-negotiables

- `.env` is gitignored. `.env.example` has placeholders only.
- `SUPABASE_SERVICE_ROLE_KEY` bypasses RLS. It is for jobs and authenticated handlers that already verified the JWT. It is never returned in a response.
- Locally minted HS256 JWTs are verified **inside FastAPI**. They are not sent to PostgREST.
- `INBOUND_HMAC_SECRET` is required in production for `/api/v1/sms/webhook`. Unsigned bodies are `403`.
- OpenAPI (`/docs`, `/redoc`, `/openapi.json`) is disabled when `APP_ENV=production`.
- CORS is an allow-list (`CORS_ORIGIN`). Do not use `*`.
- Admin HTML is `/dashboard` only (ops). Farmer product UI is not in this repo.

## Headers

`app/security.py` sets `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, CSP, and HSTS on HTTPS.

## Dependencies

CI runs `pip-audit -r requirements.txt` and a secret-pattern grep on every pull request.
