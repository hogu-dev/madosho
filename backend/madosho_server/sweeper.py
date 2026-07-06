from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from madosho_server import db

logger = logging.getLogger("madosho_server.sweeper")

_GRACE_SECONDS = 30   # matches ContainerExecutor's stop grace


def sweep_stalled(session, settings, now: datetime | None = None) -> int:
    """Fail rows stuck in a non-terminal state past the build timeout ceiling -
    the backstop for a job container SIGKILLed (or a host that died) before its
    SIGTERM handler could mark the row. Time-based, no container introspection."""
    ceiling = settings.job_timeout_for("ingest")
    if not ceiling:
        return 0
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - timedelta(seconds=ceiling + _GRACE_SECONDS)
    swept = 0
    for doc in session.scalars(select(db.Document).where(
            db.Document.status == "indexing", db.Document.updated_at < cutoff)):
        doc.status = "failed"
        doc.error = "job container did not complete (stalled past timeout; swept)"
        swept += 1
    for p in session.scalars(select(db.Pipeline).where(
            db.Pipeline.status == "building", db.Pipeline.updated_at < cutoff)):
        p.status = "failed"
        p.error = "job container did not complete (stalled past timeout; swept)"
        swept += 1
    if swept:
        session.commit()
        logger.warning("sweeper failed %d stalled row(s)", swept)
    return swept
