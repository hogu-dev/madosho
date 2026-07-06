from __future__ import annotations

import logging
from typing import Callable, Protocol

logger = logging.getLogger("madosho_server.executor")


class JobTerminated(Exception):
    """Raised inside a job container when it receives SIGTERM (docker stop). It
    is an Exception subclass on purpose: the task impls already wrap their work
    in `except Exception` and mark the target row failed + drop the partial
    collection, so a graceful stop reuses that path with no extra code."""


class JobExecutor(Protocol):
    def run(self, name: str, kwargs: dict) -> None: ...


class InProcessExecutor:
    """Backend A: run the job impl in this process (today's behavior)."""

    def __init__(self, impls: dict[str, Callable]):
        self._impls = impls

    def run(self, name: str, kwargs: dict) -> None:
        self._impls[name](**kwargs)


def resolve_executor(queue: str, settings, impls: dict[str, Callable],
                     client=None) -> JobExecutor:
    """Pick the backend for `queue`. Defaults to in-process; only `container`
    selects the container backend (Task 5 fills in ContainerExecutor)."""
    if settings.executor_for_queue(queue) == "container":
        from madosho_server.executor_container import ContainerExecutor
        return ContainerExecutor(settings, queue, client=client)
    return InProcessExecutor(impls)
