"""Scheduled job entry point: ingest + assess every active field, then deliver notifications.

Intended for cron / a scheduler (docs/OPERATIONS.md). Idempotent and restartable: each
source job records its own status; a failed source leaves previous data untouched.
"""

import argparse
import logging

from croppulse.alerting.engine import deliver_pending
from croppulse.db import get_sessionmaker
from croppulse.ingestion.jobs import ingest_field
from croppulse.logging_setup import configure_logging, log
from croppulse.models import Field
from croppulse.risk.service import run_assessment
from sqlalchemy import select

logger = logging.getLogger("croppulse.scheduler")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--assess-only", action="store_true")
    ap.add_argument("--deliver-only", action="store_true")
    args = ap.parse_args()
    configure_logging("INFO")
    s = get_sessionmaker()()
    if not args.deliver_only:
        fields = s.scalars(
            select(Field).where(
                Field.deleted_at.is_(None), Field.is_synthetic.is_(False)
            )
        ).all()
        for f in fields:
            if not args.assess_only:
                jobs = ingest_field(s, f)
                log(
                    logger,
                    logging.INFO,
                    "field ingested",
                    field=f.id,
                    jobs={j.source_id: j.status for j in jobs},
                )
            ra, decision, _ = run_assessment(s, f)
            log(
                logger,
                logging.INFO,
                "field assessed",
                field=f.id,
                state=ra.state,
                alert=decision.outcome,
            )
    log(logger, logging.INFO, "notifications", **deliver_pending(s))
