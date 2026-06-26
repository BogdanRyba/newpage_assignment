"""Liveness/readiness endpoint. Compose healthchecks and the seed step gate on it."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: str
    service: str = "ariadne-api"


@router.get("/health", response_model=Health)
async def health() -> Health:
    return Health(status="ok")
