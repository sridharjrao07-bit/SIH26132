"""Map infrastructure failures to boring HTTP responses. Never leak PostgREST text.

RPC error convention (from migrations 013 and 032):
  P0001  cross-tenant violation or domain constraint  → 409
  P0002  row not found or not owned                   → 404
  P0003  invalid state-machine transition             → 409
  P0004  invalid input value                          → 422

Postgres constraint errors:
  23503  foreign key violation                        → 400
  23505  unique violation (incl. double-accept index) → 409
  23514  check constraint violation                   → 422
  42501  insufficient privilege (revoked role)        → 403

PostgREST errors:
  PGRST301  JWT expired/invalid                       → 401
  PGRST100  malformed request / parse error           → 422
"""

from __future__ import annotations

from fastapi.responses import JSONResponse
from postgrest.exceptions import APIError

# Maps our RPC raise codes (P000x) to HTTP status + human message.
_RPC_CODE_MAP: dict[str, tuple[int, str]] = {
    "P0001": (409, "operation not permitted"),
    "P0002": (404, "not found"),
    "P0003": (409, "invalid state transition"),
    "P0004": (422, "invalid input"),
}

# Maps Postgres error codes to HTTP status + human message.
_PG_CODE_MAP: dict[str, tuple[int, str]] = {
    "23503": (400, "referenced record not found"),
    "23505": (409, "already exists"),
    "23514": (422, "failed a data check"),
    "42501": (403, "not allowed"),
    "22P02": (422, "invalid id"),
}


def json_for_api_error(exc: APIError) -> JSONResponse:
    """Convert a PostgREST APIError into a safe, opaque HTTP response.

    Never returns the raw PostgREST message to the client — it may contain
    schema details, row values, or constraint names.
    """
    code = str(getattr(exc, "code", None) or "")
    message = str(getattr(exc, "message", None) or "")
    lower = message.lower()

    # JWT / auth errors
    if code == "PGRST301" or "jwt" in lower or "does not match" in lower:
        return JSONResponse(status_code=401, content={"detail": "invalid token"})

    # PostgREST parse errors
    if code in ("PGRST100",) or "invalid input syntax" in lower:
        return JSONResponse(status_code=422, content={"detail": "invalid id"})

    # RPC domain errors (P000x series from our security-definer functions)
    if code in _RPC_CODE_MAP:
        status, detail = _RPC_CODE_MAP[code]
        return JSONResponse(status_code=status, content={"detail": detail})

    # Postgres constraint errors
    if code in _PG_CODE_MAP:
        status, detail = _PG_CODE_MAP[code]
        return JSONResponse(status_code=status, content={"detail": detail})

    # 22P02 can also surface from PostgREST directly
    if code == "22P02":
        return JSONResponse(status_code=422, content={"detail": "invalid id"})

    # Default: opaque 503 — something is wrong with the data store
    return JSONResponse(
        status_code=503,
        content={"detail": "data store temporarily unavailable"},
    )
