from madosho_server import tasks
from madosho_server.entrypoints import worker_queues


def test_run_alchemy_task_registered():
    assert "run_alchemy" in tasks._IMPLS
    assert tasks.run_alchemy.name == "run_alchemy"


def test_alchemy_queue_in_default_worker_set(monkeypatch):
    monkeypatch.delenv("MADOSHO_WORKER_QUEUES", raising=False)
    assert "alchemy" in worker_queues()
