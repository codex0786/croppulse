"""Ingestion jobs: idempotent, restartable, observable.

Each job writes an IngestionJob row (status, counts, warnings) and updates the
DataSource operational state. Failures record the error and leave previously
valid data untouched (it keeps its original timestamps and becomes stale).
No job ever writes placeholder values when a source fails.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from croppulse.config import config_version, get_settings, science_config
from croppulse.db import utcnow
from croppulse.enums import JobStatus, SourceStatus
from croppulse.ingestion.quality import check_vegetation_composites, check_weather_frame
from croppulse.logging_setup import log
from croppulse.models import DatasetVersion, DataSource, Field, IngestionJob, Observation
from croppulse.sources.base import SourceError, SourceNotConfigured
from croppulse.sources.modis_ornl import LandCoverAdapter, ModisOrnlAdapter
from croppulse.sources.nasa_power import GridCell, NasaPowerAdapter, grid_cell_for

logger = logging.getLogger(__name__)


def _source_state(session: Session, source_id: str) -> DataSource:
    ds = session.get(DataSource, source_id)
    if ds is None:
        ds = DataSource(id=source_id, status=SourceStatus.implemented_untested)
        session.add(ds)
    return ds


def _start(session: Session, source_id: str, job_type: str, target: str | None) -> IngestionJob:
    job = IngestionJob(
        source_id=source_id,
        job_type=job_type,
        target_ref=target,
        status=JobStatus.running,
        config_version=config_version(get_settings().science_config_path),
    )
    session.add(job)
    session.flush()
    return job


def _fail(session: Session, job: IngestionJob, ds: DataSource, exc: Exception) -> None:
    job.status = JobStatus.failed
    job.message = str(exc)[:500]
    job.finished_at = utcnow()
    ds.last_attempt_at = job.finished_at
    ds.last_error = job.message
    ds.status = SourceStatus.not_configured if isinstance(exc, SourceNotConfigured) else SourceStatus.unavailable
    log(logger, logging.WARNING, "ingestion failed", source=job.source_id, job=job.id, error=job.message)


def upsert_observation(session: Session, obs: Observation) -> str:
    """Insert or revise an observation. Returns 'written' | 'unchanged' | 'revised'.

    Idempotent: identical re-ingestion changes nothing. A changed value (provider
    reprocessing) creates revision n+1 and marks the old row not current — history is kept.
    """
    current = session.scalars(
        select(Observation).where(
            Observation.field_id == obs.field_id,
            Observation.source_id == obs.source_id,
            Observation.variable == obs.variable,
            Observation.period_start == obs.period_start,
            Observation.is_current.is_(True),
        )
    ).first()
    if current is None:
        session.add(obs)
        return "written"
    same_value = (current.value is None and obs.value is None) or (
        current.value is not None and obs.value is not None and abs(current.value - obs.value) < 1e-9
    )
    if same_value and current.accepted == obs.accepted and current.boundary_version == obs.boundary_version:
        return "unchanged"
    current.is_current = False
    obs.revision = current.revision + 1
    session.add(obs)
    return "revised"


def ingest_field_vegetation(session: Session, field: Field, adapter: ModisOrnlAdapter | None = None, today: date | None = None) -> IngestionJob:
    cfg = science_config()["vegetation"]
    adapter = adapter or ModisOrnlAdapter()
    ds = _source_state(session, adapter.source_id)
    job = _start(session, adapter.source_id, "field_vegetation", field.id)
    try:
        today = today or datetime.now(UTC).date()
        start = date(today.year - cfg["reference_years"] - 1, 1, 1)
        series = adapter.field_series(
            field.geometry_geojson,
            (field.centroid_lat, field.centroid_lon),
            (field.min_lon, field.min_lat, field.max_lon, field.max_lat),
            start,
            accepted_reliability=set(cfg["accepted_reliability"]),
            min_valid_fraction=cfg["min_valid_pixel_fraction"],
            window_km_min=cfg["fetch_window_km"],
            today=today,
        )
        warnings = list(series.warnings) + check_vegetation_composites(series.composites)
        method = (
            f"mean of quality-accepted pixels; rule={series.selection.rule}; "
            f"selected={len(series.selection.indices)} of {series.selection.total_in_window}; window_km={series.window_km}"
        )
        counts = {"written": 0, "unchanged": 0, "revised": 0}
        now = utcnow()
        for c in series.composites:
            for variable, value in (("NDVI", c.ndvi), ("EVI", c.evi)):
                obs = Observation(
                    field_id=field.id,
                    source_id=adapter.source_id,
                    variable=variable,
                    period_start=c.period_start,
                    period_end=c.period_end,
                    value=value,
                    unit="dimensionless",
                    accepted=c.accepted,
                    rejection_reason=c.rejection_reason,
                    valid_pixel_count=c.valid_pixels,
                    total_pixel_count=c.selected_pixels,
                    valid_fraction=c.valid_fraction,
                    quality_summary={"reliability_counts": c.reliability_counts, "tile": c.tile, "selection_rule": series.selection.rule},
                    aggregation_method=method,
                    boundary_version=field.boundary_version,
                    published_at=c.published_at,
                    retrieved_at=series.retrieved_at,
                    processed_at=now,
                    available_at=now,
                    is_synthetic=series.is_synthetic,
                    raw_ref=";".join(series.raw_refs[:3]) if series.raw_refs else None,
                )
                counts[upsert_observation(session, obs)] += 1
        if series.is_synthetic:
            field.is_synthetic = True  # a field fed by labelled fixtures is a synthetic field
        job.records_written = counts["written"] + counts["revised"]
        job.records_unchanged = counts["unchanged"]
        job.records_rejected = sum(1 for c in series.composites if not c.accepted)
        job.warnings = warnings[:50]
        job.checkpoint = {"last_period_start": series.composites[-1].period_start.isoformat() if series.composites else None, "revised": counts["revised"]}
        job.status = JobStatus.succeeded if not warnings else JobStatus.partial
        job.finished_at = utcnow()
        ds.status = SourceStatus.fixture_only if series.is_synthetic else SourceStatus.live_tested
        ds.last_attempt_at = ds.last_success_at = job.finished_at
        ds.last_error = None
        if series.composites:
            last_end = max(c.period_end for c in series.composites)
            ds.latest_observation_end = last_end
            ds.observed_latency_days = float((today - last_end).days)
        ds.processing_version = "MOD13Q1.061"
    except (SourceError, ValueError) as exc:
        _fail(session, job, ds, exc)
    session.commit()
    return job


def ingest_field_land_cover(session: Session, field: Field, adapter: LandCoverAdapter | None = None) -> IngestionJob:
    adapter = adapter or LandCoverAdapter()
    ds = _source_state(session, adapter.source_id)
    job = _start(session, adapter.source_id, "field_land_cover", field.id)
    try:
        res = adapter.latest(field.centroid_lat, field.centroid_lon)
        now = utcnow()
        obs = Observation(
            field_id=field.id,
            source_id=adapter.source_id,
            variable="LC_Type1",
            period_start=date(res.year, 1, 1),
            period_end=date(res.year, 12, 31),
            value=float(res.lc_type1) if res.lc_type1 is not None else None,
            unit="IGBP class",
            accepted=res.lc_type1 is not None,
            rejection_reason=None if res.lc_type1 is not None else "fill_value",
            aggregation_method="500 m pixel containing field centroid",
            boundary_version=field.boundary_version,
            published_at=res.published_at,
            retrieved_at=res.retrieved_at,
            processed_at=now,
            available_at=now,
            raw_ref=res.raw_ref,
            is_synthetic=res.is_synthetic,
        )
        outcome = upsert_observation(session, obs)
        job.records_written = int(outcome != "unchanged")
        job.records_unchanged = int(outcome == "unchanged")
        job.status = JobStatus.succeeded
        job.finished_at = now
        ds.status = SourceStatus.fixture_only if res.is_synthetic else SourceStatus.live_tested
        ds.last_attempt_at = ds.last_success_at = now
        ds.last_error = None
        ds.processing_version = "MCD12Q1.061"
    except (SourceError, ValueError) as exc:
        _fail(session, job, ds, exc)
    session.commit()
    return job


def weather_path(cell: GridCell) -> Path:
    return get_settings().data_dir / "processed" / "nasa_power" / f"{cell.key}.parquet"


def ingest_weather_cell(session: Session, cell: GridCell, adapter: NasaPowerAdapter | None = None, start: date | None = None) -> IngestionJob:
    cfg = science_config()["weather"]
    adapter = adapter or NasaPowerAdapter()
    ds = _source_state(session, adapter.source_id)
    job = _start(session, adapter.source_id, "weather_cell", cell.key)
    try:
        today = datetime.now(UTC).date()
        start = start or date(today.year - cfg["reference_years"] - 1, 1, 1)
        series = adapter.fetch(cell, start)
        warnings = check_weather_frame(series.frame)
        path = weather_path(cell)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp.parquet")
        frame = series.frame.reset_index()
        frame["date"] = pd.to_datetime(frame["date"])
        frame.to_parquet(tmp, index=False)
        digest = hashlib.sha256(tmp.read_bytes()).hexdigest()
        current = session.scalars(
            select(DatasetVersion).where(DatasetVersion.dataset_key == cell.key, DatasetVersion.is_current.is_(True))
        ).first()
        if current is not None and current.sha256 == digest:
            tmp.unlink()
            job.records_unchanged = len(frame)
        else:
            tmp.replace(path)
            if current is not None:
                current.is_current = False
            session.add(
                DatasetVersion(
                    source_id=adapter.source_id,
                    dataset_key=cell.key,
                    path=str(path.relative_to(get_settings().data_dir)),
                    sha256=digest,
                    row_count=len(frame),
                    coverage_start=series.frame.index.min(),
                    coverage_end=series.last_valid_date,
                    retrieved_at=series.retrieved_at,
                    source_request=series.request_url + " (grid-cell centre; parameters in source_metadata)",
                    source_metadata={
                        "units": series.units,
                        "sources": series.sources,
                        "api_version": series.api_version,
                        "time_standard": series.time_standard,
                        "grid_cell": {"lat": cell.lat, "lon": cell.lon},
                        "raw_ref": series.raw_ref,
                    },
                    is_synthetic=series.is_synthetic,
                )
            )
            job.records_written = len(frame)
        job.warnings = warnings
        # Trailing missing days are the provider's normal latency, reported but not a defect.
        defects = [w for w in warnings if not w.startswith("trailing_missing_days")]
        job.status = JobStatus.succeeded if not defects else JobStatus.partial
        job.finished_at = utcnow()
        ds.status = SourceStatus.fixture_only if series.is_synthetic else SourceStatus.live_tested
        ds.last_attempt_at = ds.last_success_at = job.finished_at
        ds.last_error = None
        ds.latest_observation_end = series.last_valid_date
        ds.observed_latency_days = float((today - series.last_valid_date).days) if series.last_valid_date else None
        ds.processing_version = f"POWER API {series.api_version}"
    except (SourceError, ValueError, OSError) as exc:
        _fail(session, job, ds, exc)
    session.commit()
    return job


def load_weather_frame(session: Session, lat: float, lon: float) -> tuple[pd.DataFrame | None, DatasetVersion | None]:
    cell = grid_cell_for(lat, lon)
    dv = session.scalars(select(DatasetVersion).where(DatasetVersion.dataset_key == cell.key, DatasetVersion.is_current.is_(True))).first()
    if dv is None:
        return None, None
    path = get_settings().data_dir / dv.path
    if not path.exists():
        return None, dv
    frame = pd.read_parquet(path)
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    return frame.set_index("date"), dv


def ingest_field(session: Session, field: Field) -> list[IngestionJob]:
    """Run all field-level ingestion (vegetation, land cover, weather cell)."""
    jobs = [ingest_field_vegetation(session, field), ingest_field_land_cover(session, field)]
    cell = grid_cell_for(field.centroid_lat, field.centroid_lon)
    current = session.scalars(select(DatasetVersion).where(DatasetVersion.dataset_key == cell.key, DatasetVersion.is_current.is_(True))).first()
    # Neighbouring fields share a grid cell: refresh it at most every 12 hours.
    if current is None or (utcnow() - current.retrieved_at).total_seconds() > 12 * 3600:
        jobs.append(ingest_weather_cell(session, cell))
    return jobs
