from madosho_server.entrypoints import worker_queues


def test_default_is_all_default_queues(monkeypatch):
    monkeypatch.delenv("MADOSHO_WORKER_QUEUES", raising=False)
    assert worker_queues() == ["ingest", "ratings", "eval", "research", "alchemy"]


def test_env_pins_a_subset(monkeypatch):
    monkeypatch.setenv("MADOSHO_WORKER_QUEUES", "research, eval")
    assert worker_queues() == ["research", "eval"]


def test_blank_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("MADOSHO_WORKER_QUEUES", "  ")
    assert worker_queues() == ["ingest", "ratings", "eval", "research", "alchemy"]
