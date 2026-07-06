import shutil

import pytest

from madosho_server.executor_container import ContainerExecutor
from madosho_server.settings import Settings

pytestmark = pytest.mark.slow


@pytest.fixture
def docker_available():
    if shutil.which("docker") is None:
        pytest.skip("docker not available")


def test_short_job_runs_in_a_real_container(monkeypatch, docker_available):
    # Uses madosho:local's `madosho-run-job` with a built-in no-op task the impl
    # registry exposes for smoke tests; assert it exits 0 (no raise).
    monkeypatch.setenv("MADOSHO_JOB_EXECUTOR", "container")
    monkeypatch.setenv("MADOSHO_JOB_TIMEOUT", "120")
    ex = ContainerExecutor(Settings.from_env(), "ingest")
    ex.run("noop", {})   # see tasks.py _noop_impl


def test_timed_out_job_is_hard_killed(monkeypatch, docker_available):
    monkeypatch.setenv("MADOSHO_JOB_EXECUTOR", "container")
    monkeypatch.setenv("MADOSHO_JOB_TIMEOUT", "2")
    ex = ContainerExecutor(Settings.from_env(), "ingest")
    with pytest.raises(TimeoutError):
        ex.run("sleep_forever", {})   # see tasks.py _sleep_forever_impl
