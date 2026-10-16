"""FastAPI application factory."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from croppulse import __version__
from croppulse.api import metrics
from croppulse.api.routers import auth, cases, fields, monitoring
from croppulse.config import get_settings, science_config
from croppulse.db import get_engine
from croppulse.logging_setup import configure_logging, log

logger = logging.getLogger("croppulse.api")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="CropPulse API",
        version=__version__,
        description=(
            "Agricultural screening and decision-support API. Outputs distinguish observations (satellite/reanalysis), "
            "derived indicators, unvalidated screening states and expert-verified findings. "
            "Nothing here is an official drought declaration or crop-loss assessment."
        ),
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def observe(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        rid = uuid.uuid4().hex[:12]
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("unhandled error", extra={"ctx": {"request_id": rid, "path": request.url.path}})
            response = JSONResponse({"detail": "Internal server error", "request_id": rid}, status_code=500)
        ms = (time.perf_counter() - start) * 1000
        route = request.scope.get("route")
        template = getattr(route, "path", "unmatched")
        metrics.record(f"{request.method} {template}", response.status_code, ms)
        log(logger, logging.INFO, "request", request_id=rid, method=request.method, route=template, status=response.status_code, ms=int(ms))
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        if settings.environment == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Do not echo submitted values (they may contain coordinates or passwords).
        errors: list[dict[str, Any]] = [{"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return JSONResponse({"detail": "Invalid request", "errors": errors}, status_code=422)

    @app.get("/health", tags=["ops"])
    def health() -> dict[str, str]:
        """Liveness: the process is running. No dependency checks, no infrastructure details."""
        return {"status": "ok"}

    @app.get("/ready", tags=["ops"])
    def ready() -> JSONResponse:
        """Readiness: database reachable and configuration loadable."""
        checks = {}
        try:
            with get_engine().connect() as conn:
                conn.execute(text("SELECT 1 FROM alembic_version"))
            checks["database"] = "ok"
        except Exception:
            checks["database"] = "unavailable_or_not_migrated"
        try:
            science_config()
            checks["configuration"] = "ok"
        except Exception:
            checks["configuration"] = "invalid"
        ok = all(v == "ok" for v in checks.values())
        return JSONResponse({"status": "ready" if ok else "not_ready", "checks": checks}, status_code=200 if ok else 503)

    app.include_router(auth.router)
    app.include_router(fields.router)
    app.include_router(cases.router)
    app.include_router(monitoring.router)
    return app


app = create_app()
