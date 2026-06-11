"""
Rate limiting middleware module for FastAPI using slowapi.
Implements custom IP resolution supporting X-Real-IP and X-Forwarded-For headers
to correctly track clients behind proxies/Nginx.
"""

import os
import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

logger = logging.getLogger(__name__)



def get_real_client_ip(request: Request) -> str:
    """
    Resolve the real client IP address, prioritizing headers forwarded by proxy servers/Nginx.
    """
    # 1. Check for X-Forwarded-For header (comma-separated list of proxies, first is the original client)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        ip = forwarded_for.split(",")[0].strip()
        if ip:
            return ip

    # 2. Check for X-Real-IP header
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip

    # 3. Fallback to direct client host
    if request.client:
        return request.client.host

    return "127.0.0.1"


# Initialize the Limiter instance
limiter = Limiter(key_func=get_real_client_ip, headers_enabled=True)



async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """
    Custom exception handler to return 429 Too Many Requests JSON payload
    with rate limiting headers.
    """
    response = JSONResponse(
        status_code=429,
        content={"detail": f"Rate limit exceeded: {exc.detail}"},
    )
    # Inject slowapi headers into the response
    if hasattr(request.app.state, "limiter"):
        limiter_obj = request.app.state.limiter
        view_rate_limit = getattr(request.state, "view_rate_limit", None)
        response = limiter_obj._inject_headers(response, view_rate_limit)
    return response



def init_rate_limiting(app: FastAPI) -> None:
    """
    Register the slowapi limiter instance and exception handler onto the FastAPI application.
    """
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    logger.info("Rate limiting middleware initialized with real IP resolver.")

