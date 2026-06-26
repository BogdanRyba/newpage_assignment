"""The health endpoint backs compose healthchecks and the seed gate."""

from __future__ import annotations

import httpx
from httpx import ASGITransport

from app.main import app


async def test_health_returns_ok() -> None:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "ariadne-api"


async def test_unknown_route_404() -> None:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/does-not-exist")
    assert resp.status_code == 404
