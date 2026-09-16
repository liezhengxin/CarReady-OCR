"""Liveness and readiness probes."""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from app.config import get_settings
from app.db import check_database

router = APIRouter(tags=["health"])
settings = get_settings()


class HealthResponse(BaseModel):
    status: str
    environment: str
    version: str


class ReadinessResponse(BaseModel):
    status: str
    checks: dict[str, bool]


@router.get("/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse:
    """Liveness. Answers "is the process up", nothing more.

    Deliberately does not touch the database: a liveness probe that fails on a
    transient database blip gets the container killed and restarted, which
    fixes nothing and takes the API down while the database recovers.
    """
    return HealthResponse(status="ok", environment=settings.environment, version="0.1.0")


@router.get("/readyz", response_model=ReadinessResponse)
def readyz(response: Response) -> ReadinessResponse:
    """Readiness. Answers "can this instance serve traffic".

    A failure here removes the instance from the load balancer without killing
    it, which is the correct response to a dependency being unavailable.
    """
    checks = {"database": check_database()}
    ok = all(checks.values())
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="ready" if ok else "not_ready", checks=checks)
