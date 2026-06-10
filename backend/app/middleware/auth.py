import hmac
import os

from fastapi import Request, HTTPException

from ..core.config import config

AUTH_COOKIE = "sistem1_auth"
ONE_MONTH_SEC = 30 * 24 * 60 * 60
MIN_AUTH_TOKEN_LENGTH = max(24, config.auth_token_min_length)


def _safe_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def _is_production() -> bool:
    return os.environ.get("APP_ENV") == "production" or os.environ.get("NODE_ENV") == "production"


def _is_loopback_host(host: str | None) -> bool:
    return (host or "").strip().lower() in ("127.0.0.1", "localhost", "::1")


def is_auth_disabled() -> bool:
    if _is_production():
        return False
    raw = (os.environ.get("DISABLE_AUTH") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def validate_auth_config() -> None:
    disabled_raw = (os.environ.get("DISABLE_AUTH") or "").strip().lower()
    disabled_requested = disabled_raw in ("1", "true", "yes", "on")
    if _is_production() and disabled_requested:
        raise RuntimeError("DISABLE_AUTH cannot be used in production")

    exposed_host = not _is_loopback_host(config.host)
    if is_auth_disabled():
        if exposed_host:
            raise RuntimeError("DISABLE_AUTH cannot be used when HOST is not loopback")
        return

    if not _is_production() and not exposed_host:
        return

    if (
        not os.environ.get("AUTH_TOKEN")
        or config.auth_token == "dev-token"
        or len(config.auth_token) < MIN_AUTH_TOKEN_LENGTH
    ):
        raise RuntimeError(
            f"AUTH_TOKEN with at least {MIN_AUTH_TOKEN_LENGTH} characters is required for production or exposed hosts"
        )


def is_auth_token_valid(token: str | None) -> bool:
    if is_auth_disabled():
        return True
    if not token:
        return False
    return _safe_compare(token, config.auth_token)


def token_from_request(request: Request) -> str | None:
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(AUTH_COOKIE)


async def require_auth(request: Request) -> None:
    if not is_auth_token_valid(token_from_request(request)):
        raise HTTPException(status_code=401, detail="Unauthorized")


def cookie_kwargs(request: Request) -> dict:
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    return {"httponly": True, "samesite": "lax", "path": "/", "secure": secure}
