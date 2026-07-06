"""Ingest progress feed for the UI.

The kernel calls an IngestReporter at each pipeline seam (parse -> chunk ->
embed -> store). `DbIngestReporter` is the worker's implementation: it writes
the current phase plus a short rolling log into the document row's `progress`
column, which the web UI polls. Because docling's parse is a single multi-minute
blocking call that emits nothing of its own, a background heartbeat thread keeps
the log moving so the user can see the worker is alive, not stuck.

The reporter owns the `progress` column exclusively. The worker's main session
writes only status/artifacts (other columns), so the two never clobber each
other even though they run in separate transactions.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

from madosho_server import db

logger = logging.getLogger("madosho_server.progress")


def count_pdf_pages(path, mimetype: str | None) -> int | None:
    """Best-effort page count for UI context ("250-page document"). Uses
    pypdfium2 (already present as docling's PDF backend); never raises -- a
    missing/corrupt file or non-PDF just yields None and the UI omits it."""
    if "pdf" not in (mimetype or "").lower():
        return None
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(str(path))
        try:
            return len(pdf)
        finally:
            pdf.close()
    except Exception:
        logger.debug("count_pdf_pages failed for %s", path, exc_info=True)
        return None


class DbIngestReporter:
    """IngestReporter that publishes progress to a row's `progress` column.

    Targets the `Document` row by default (the original-ingest feed); pass
    `model=db.Pipeline` to drive a pipeline-build console off the same machinery
    (the kernel calls the same phase/log seams either way). Use as a context
    manager around the kernel's ingest call: entering starts a heartbeat thread
    and publishes the initial state; exiting stops the thread. All public methods
    are thread-safe (phase/log run on the worker thread; the heartbeat runs on its
    own), each serialized through a lock and a short-lived DB session so concurrent
    threads never share a Session.

    The reporter owns the `progress` column exclusively; the worker's main session
    writes only other columns (status/artifacts), and SQLAlchemy's column-level
    dirty tracking keeps the two non-overlapping UPDATEs from clobbering each other.
    """

    MAX_LOG_LINES = 200

    def __init__(self, session_factory, row_id: int, *,
                 page_count: int | None = None, heartbeat_seconds: float = 15.0,
                 clock=time.monotonic, model=db.Document):
        self._session_factory = session_factory
        self._row_id = row_id
        self._model = model
        self._heartbeat_seconds = heartbeat_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = clock()
        self._progress = {
            "phase": "starting",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "page_count": page_count,
            "log": [],
        }

    # -- context manager: heartbeat lifecycle ------------------------------
    def __enter__(self) -> "DbIngestReporter":
        with self._lock:
            self._publish_locked()
        self._thread = threading.Thread(
            target=self._run, name=f"ingest-heartbeat-{self._row_id}", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> bool:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        return False   # never suppress: the worker owns failure bookkeeping

    def _run(self) -> None:
        # Event.wait returns True once stop is set, False on timeout -> beat.
        while not self._stop.wait(self._heartbeat_seconds):
            self._beat()

    def _beat(self) -> None:
        with self._lock:
            elapsed = int(self._clock() - self._started)
            self._append_locked(f"still working ({self._progress['phase']}) - {elapsed}s elapsed")
            self._publish_locked()

    # -- IngestReporter protocol -------------------------------------------
    def phase(self, name: str) -> None:
        with self._lock:
            self._progress["phase"] = name
            self._append_locked(name)
            self._publish_locked()

    def log(self, message: str) -> None:
        with self._lock:
            self._append_locked(message)
            self._publish_locked()

    # -- internals (caller must hold self._lock) ---------------------------
    def _append_locked(self, msg: str) -> None:
        log = self._progress["log"]
        log.append({"t": int(self._clock() - self._started), "msg": msg})
        if len(log) > self.MAX_LOG_LINES:    # keep the newest, drop the oldest
            del log[: len(log) - self.MAX_LOG_LINES]

    def _publish_locked(self) -> None:
        # fresh dict each write so SQLAlchemy sees the JSON column as changed
        snapshot = {**self._progress, "log": list(self._progress["log"])}
        try:
            with self._session_factory() as session:
                row = session.get(self._model, self._row_id)
                if row is not None:
                    row.progress = snapshot
                    session.commit()
        except Exception:   # progress is cosmetic: never let it fail an ingest
            logger.warning("failed to publish ingest progress for %s %s",
                           self._model.__name__, self._row_id, exc_info=True)
