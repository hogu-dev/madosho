import logging

import pytest

from madosho.core.errors import ComponentDeniedError
from madosho.core.hooks import (
    Resolution, ResolutionAction, ResolutionContext, load_hooks, run_hooks,
)
from madosho.core.meta import ComponentKind, ComponentMeta, Hardware, OriginTier

META = ComponentMeta(name="x", kind=ComponentKind.STORE, version="0", license="MIT",
                     org="o", org_country="US", origin_tier=OriginTier.US_SRC,
                     hardware=Hardware.CPU)
CTX = ResolutionContext(corpus="c", config_path=None)
LOGGER = logging.getLogger("madosho.test")


def test_no_hooks_is_a_no_op():
    run_hooks([], META, CTX, LOGGER)  # must not raise


def test_allow_and_warn_pass_through(caplog):
    def warn_hook(meta, ctx):
        return Resolution(action=ResolutionAction.WARN, message="heads up")

    with caplog.at_level(logging.WARNING, logger="madosho.test"):
        run_hooks([warn_hook], META, CTX, LOGGER)
    assert "heads up" in caplog.text


def test_deny_raises_with_message():
    def deny_hook(meta, ctx):
        return Resolution(action=ResolutionAction.DENY, message="policy says no")

    with pytest.raises(ComponentDeniedError, match="policy says no"):
        run_hooks([deny_hook], META, CTX, LOGGER)


def test_audit_record_handed_to_hook_sink():
    records = []

    class AuditHook:
        def __call__(self, meta, ctx):
            return Resolution(action=ResolutionAction.ALLOW, audit={"saw": meta.name})
        def sink(self, record):
            records.append(record)

    run_hooks([AuditHook()], META, CTX, LOGGER)
    assert records == [{"saw": "x"}]


def test_load_hooks_reads_entry_points(monkeypatch):
    def fake_hook(meta, ctx):
        return Resolution(action=ResolutionAction.ALLOW)

    class EP:
        name = "fake"
        def load(self):
            return fake_hook

    monkeypatch.setattr("madosho.core.hooks.entry_points", lambda group: [EP()])
    assert load_hooks() == [fake_hook]


def test_load_hooks_fails_hard_on_broken_plugin(monkeypatch):
    from madosho.core.errors import MadoshoError

    class BadEP:
        name = "bad"
        def load(self):
            raise ImportError("missing dep")

    monkeypatch.setattr("madosho.core.hooks.entry_points", lambda group: [BadEP()])
    with pytest.raises(MadoshoError, match="bad"):
        load_hooks()


def test_non_resolution_return_is_a_clear_error():
    from madosho.core.errors import MadoshoError

    def forgetful_hook(meta, ctx):
        return None

    with pytest.raises(MadoshoError, match="forgetful_hook"):
        run_hooks([forgetful_hook], META, CTX, LOGGER)


def test_deny_still_emits_audit_first():
    records = []

    class DenyAuditHook:
        def __call__(self, meta, ctx):
            return Resolution(action=ResolutionAction.DENY, message="no",
                              audit={"denied": meta.name})
        def sink(self, record):
            records.append(record)

    with pytest.raises(ComponentDeniedError):
        run_hooks([DenyAuditHook()], META, CTX, LOGGER)
    assert records == [{"denied": "x"}]
