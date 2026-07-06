import pytest

from madosho_server.executor_container import ContainerExecutor
from madosho_server.settings import Settings


class FakeContainer:
    def __init__(self, status_code=0, raise_on_wait=None):
        self._status = status_code
        self._raise = raise_on_wait
        self.stopped = False
        self.removed = False

    def wait(self, timeout=None):
        if self._raise:
            raise self._raise
        return {"StatusCode": self._status}

    def stop(self, timeout=None):
        self.stopped = True

    def remove(self, force=False):
        self.removed = True


class FakeContainers:
    def __init__(self, container):
        self._c = container
        self.run_kwargs = None

    def run(self, **kwargs):
        self.run_kwargs = kwargs
        return self._c


class FakeClient:
    def __init__(self, container):
        self.containers = FakeContainers(container)


def _settings(monkeypatch):
    monkeypatch.setenv("MADOSHO_JOB_EXECUTOR", "container")
    monkeypatch.setenv("MADOSHO_JOB_TIMEOUT", "600")
    monkeypatch.setenv("MADOSHO_JOB_MOUNTS", "madosho_filestore:/data/filestore")
    return Settings.from_env()


def test_spawns_with_run_job_command_and_reaps(monkeypatch):
    c = FakeContainer(status_code=0)
    client = FakeClient(c)
    ContainerExecutor(_settings(monkeypatch), "ingest", client=client).run(
        "ingest_document", {"document_id": 42})
    kw = client.containers.run_kwargs
    assert kw["image"] == "madosho:local"
    assert kw["command"] == ["madosho-run-job", "ingest_document", '{"document_id": 42}']
    assert kw["detach"] is True
    assert kw["environment"]["MADOSHO_JOB_EXECUTOR"] == "inproc"
    assert kw["volumes"] == {"madosho_filestore": {"bind": "/data/filestore", "mode": "rw"}}
    assert c.removed is True


def test_nonzero_exit_raises_and_reaps(monkeypatch):
    c = FakeContainer(status_code=1)
    with pytest.raises(RuntimeError):
        ContainerExecutor(_settings(monkeypatch), "ingest", client=FakeClient(c)).run(
            "ingest_document", {"document_id": 42})
    assert c.removed is True


def test_timeout_stops_then_raises(monkeypatch):
    class FakeTimeout(Exception):
        pass

    c = FakeContainer(raise_on_wait=FakeTimeout())
    ex = ContainerExecutor(_settings(monkeypatch), "ingest", client=FakeClient(c))
    monkeypatch.setattr(ex, "_timeout_errors", (FakeTimeout,))
    with pytest.raises(TimeoutError):
        ex.run("ingest_document", {"document_id": 42})
    assert c.stopped is True
    assert c.removed is True
