"""Map infrastructure failures to boring HTTP responses. Never leak PostgREST text."""
from __future__ import annotations

from fastapi.responses import JSONResponse
from postgrest.exceptions import APIError


def json_for_api_error(exc: APIError) -> JSONResponse:
    code = str(getattr(exc, "code", None) or "")
    message = str(getattr(exc, "message", None) or "")
    lower = message.lower()

    if code == "PGRST301" or "jwt" in lower or "does not match" in lower:
        return JSONResponse(status_code=401, content={"detail": "invalid token"})
    if code in ("22P02", "PGRST100") or "invalid input syntax" in lower:
        return JSONResponse(status_code=422, content={"detail": "invalid id"})
    if code == "23503":
        return JSONResponse(status_code=400, content={"detail": "referenced record not found"})
    if code == "23505":
        return JSONResponse(status_code=409, content={"detail": "already exists"})
    if code == "23514":
        return JSONResponse(status_code=422, content={"detail": "failed a data check"})
    if code == "42501":
        return JSONResponse(status_code=403, content={"detail": "not allowed"})
    return JSONResponse(
        status_code=503,
        content={"detail": "data store temporarily unavailable"},
    )
