"""HTTP boundary checks shared by the local dashboard routes."""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import Request


UNSAFE_HTTP_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; "
        "base-uri 'none'; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "form-action 'self'; "
        "img-src 'self' https://retroachievements.org https://*.retroachievements.org data:; "
        "media-src 'self'; "
        "object-src 'none'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'"
    ),
    "Permissions-Policy": "camera=(), geolocation=(), microphone=()",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}


def _normalized_origin(value: str) -> tuple[str, str, int | None] | None:
    """Return the comparable scheme, host, and effective port for an origin."""
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return parsed.scheme, parsed.hostname.lower(), port


def request_has_trusted_origin(request: Request) -> bool:
    """Allow non-browser clients and same-origin browser mutations."""
    if request.method not in UNSAFE_HTTP_METHODS:
        return True
    if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        return False
    origin = request.headers.get("origin")
    if not origin:
        return True
    return _normalized_origin(origin) == _normalized_origin(str(request.base_url))


def apply_security_headers(response) -> None:
    """Attach browser hardening headers without replacing route-specific values."""
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
