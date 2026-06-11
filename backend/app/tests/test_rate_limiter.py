"""
Tests for rate_limiter.py — T73: Rate Limiting Middleware.
Verifies IP resolution from forwarding headers and rate limiting response headers.
"""

from unittest import mock
import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from app.rate_limiter import init_rate_limiting, limiter, get_real_client_ip


class TestGetRealClientIp:

    """Verifies that the IP address resolver prioritizes proxy/Nginx headers correctly."""

    def test_prioritizes_x_forwarded_for_first_ip(self):
        req = mock.MagicMock(spec=Request)
        req.headers = {"X-Forwarded-For": "203.0.113.195, 70.41.3.18, 150.172.238.178"}
        req.client = mock.MagicMock()
        req.client.host = "127.0.0.1"
        assert get_real_client_ip(req) == "203.0.113.195"

    def test_uses_x_real_ip_when_no_x_forwarded_for(self):
        req = mock.MagicMock(spec=Request)
        req.headers = {"X-Real-IP": "198.51.100.1"}
        req.client = mock.MagicMock()
        req.client.host = "127.0.0.1"
        assert get_real_client_ip(req) == "198.51.100.1"

    def test_falls_back_to_request_client_host(self):
        req = mock.MagicMock(spec=Request)
        req.headers = {}
        req.client = mock.MagicMock()
        req.client.host = "192.0.2.1"
        assert get_real_client_ip(req) == "192.0.2.1"

    def test_falls_back_to_localhost_when_no_client(self):
        req = mock.MagicMock(spec=Request)
        req.headers = {}
        req.client = None
        assert get_real_client_ip(req) == "127.0.0.1"


class TestRateLimitingMiddleware:
    """Verifies that rate limits are enforced and return standard headers."""

    def test_enforces_limits_and_returns_429_with_headers(self):
        # Create a dummy FastAPI app to isolate middleware testing
        app = FastAPI()
        init_rate_limiting(app)

        @app.get("/test-limit")
        @limiter.limit("2/minute")
        def route_under_limit(request: Request, response: Response):
            return {"status": "ok"}


        # Use mock.patch on database.init_db since FastAPI TestClient might trigger lifespan
        with mock.patch("app.main.init_db"):
            client = TestClient(app)

            # Request 1: Allowed
            resp1 = client.get("/test-limit")
            assert resp1.status_code == 200
            assert resp1.json() == {"status": "ok"}
            assert "x-ratelimit-limit" in resp1.headers
            assert "x-ratelimit-remaining" in resp1.headers

            # Request 2: Allowed
            resp2 = client.get("/test-limit")
            assert resp2.status_code == 200
            assert int(resp2.headers["x-ratelimit-remaining"]) == 0

            # Request 3: Blocked (429)
            resp3 = client.get("/test-limit")
            assert resp3.status_code == 429
            assert "detail" in resp3.json()
            assert "Rate limit exceeded" in resp3.json()["detail"]
            assert "retry-after" in resp3.headers
