"""FastAPI application entrypoint."""

from __future__ import annotations

import sys
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.config import get_settings, grading_is_placeholder, load_config
from app.logging_config import configure_logging, get_logger, request_id_ctx
from app.routers import auth, health, meta

settings = get_settings()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()

    problems = settings.assert_production_safe()
    if problems:
        # In production these are startup failures, not warnings. A service
        # that boots with a default JWT secret and logs a warning nobody reads
        # is worse than one that refuses to start.
        for problem in problems:
            logger.critical("unsafe_production_config", problem=problem)
        sys.exit(1)

    # Fail fast on an unparseable config rather than at the first request that
    # happens to need it.
    for name in ("grading", "pricing", "crosschecks", "capture", "catalog", "pdp", "providers"):
        load_config(name)

    logger.info(
        "api_started",
        environment=settings.environment,
        synthetic_data_mode=settings.synthetic_data_mode,
        grading_rubric_placeholder=grading_is_placeholder(),
    )
    if settings.synthetic_data_mode:
        logger.warning(
            "synthetic_data_mode_active",
            detail=(
                "All pricing output is derived from synthetic data and carries "
                "no real-world validity."
            ),
        )
    yield
    logger.info("api_stopped")


app = FastAPI(
    title="Caready Inspection & Pricing API",
    version="0.1.0",
    description=(
        "Vehicle inspection, exterior grading, and auction base price system.\n\n"
        "**Synthetic data notice:** when `SYNTHETIC_DATA_MODE` is enabled, all "
        "pricing output is derived from synthetic seed data and carries no "
        "real-world validity."
    ),
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "prod" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Attach a request id to logs, audit rows, and the response.

    The client may supply one (the PWA does, so an offline-queued capture can
    be traced end to end); otherwise one is generated.
    """
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request_id_ctx.set(request_id)
    request.state.request_id = request_id

    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "request_failed",
            method=request.method,
            path=request.url.path,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        raise
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request_completed",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=duration_ms,
    )
    return response


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "validation_error",
            "detail": "Data yang dikirim tidak valid",
            "fields": exc.errors(),
            "request_id": getattr(request.state, "request_id", None),
        },
    )


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError):
    """Surface a constraint violation without leaking the schema.

    Several of the system's guarantees are database constraints - append-only
    audit tables, "an override requires a reason", "a flagged checklist item
    requires a note". Hitting one is a bug in the service layer, so it is
    logged at error level rather than treated as a routine client mistake.
    """
    logger.error("integrity_error", path=request.url.path, detail=str(exc.orig))
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "error": "integrity_error",
            "detail": "Operasi melanggar aturan integritas data",
            "request_id": getattr(request.state, "request_id", None),
        },
    )


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError):
    logger.exception("database_error", path=request.url.path)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "error": "database_error",
            "detail": "Layanan sedang tidak tersedia, coba lagi",
            "request_id": getattr(request.state, "request_id", None),
        },
    )


app.include_router(health.router)
app.include_router(meta.router)
app.include_router(auth.router)
