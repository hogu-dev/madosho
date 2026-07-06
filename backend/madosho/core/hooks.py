from __future__ import annotations

import logging
from enum import StrEnum
from importlib.metadata import entry_points
from typing import Any, Callable

from pydantic import BaseModel

from madosho.core.errors import ComponentDeniedError, MadoshoError
from madosho.core.meta import ComponentMeta

HOOK_GROUP = "madosho.hooks"


class ResolutionAction(StrEnum):
    ALLOW = "allow"
    WARN = "warn"
    DENY = "deny"


class Resolution(BaseModel):
    action: ResolutionAction = ResolutionAction.ALLOW
    message: str | None = None
    audit: dict[str, Any] | None = None


class ResolutionContext(BaseModel):
    corpus: str
    config_path: str | None = None


Hook = Callable[[ComponentMeta, ResolutionContext], Resolution]


def load_hooks() -> list[Hook]:
    """Fail-hard on a broken hook plugin: a policy hook that cannot load must
    not be silently skipped (that would be fail-open)."""
    hooks = []
    for ep in entry_points(group=HOOK_GROUP):
        try:
            hooks.append(ep.load())
        except Exception as e:
            raise MadoshoError(
                f"resolution hook '{ep.name}' failed to load: {e}") from e
    return hooks


def run_hooks(hooks: list[Hook], meta: ComponentMeta, ctx: ResolutionContext,
              logger: logging.Logger) -> None:
    """Core ships no hooks; with an empty list this is identical to no hook system."""
    for hook in hooks:
        res = hook(meta, ctx)
        if not isinstance(res, Resolution):
            raise MadoshoError(
                f"resolution hook {getattr(hook, '__name__', hook)!r} returned "
                f"{type(res).__name__}, expected Resolution")
        # audit is emitted before a DENY verdict so denials always leave a trail
        if res.audit is not None and hasattr(hook, "sink"):
            hook.sink(res.audit)
        if res.action == ResolutionAction.DENY:
            raise ComponentDeniedError(
                f"component '{meta.name}' denied by resolution hook: {res.message}")
        if res.action == ResolutionAction.WARN:
            logger.warning("hook warning for component '%s': %s", meta.name, res.message)
