# tests/unit/test_executor_settings.py
from madosho_server.settings import Settings


def test_per_queue_executor_override(monkeypatch):
    monkeypatch.setenv("MADOSHO_JOB_EXECUTOR", "inproc")
    monkeypatch.setenv("MADOSHO_JOB_EXECUTOR_RESEARCH", "container")
    s = Settings.from_env()
    assert s.executor_for_queue("ingest") == "inproc"
    assert s.executor_for_queue("research") == "container"


def test_timeout_per_queue_then_global(monkeypatch):
    monkeypatch.setenv("MADOSHO_JOB_TIMEOUT", "600")
    monkeypatch.setenv("MADOSHO_JOB_TIMEOUT_RESEARCH", "3600")
    s = Settings.from_env()
    assert s.job_timeout_for("ingest") == 600
    assert s.job_timeout_for("research") == 3600


def test_limits_per_queue_override(monkeypatch):
    monkeypatch.setenv("MADOSHO_JOB_MEMORY", "2g")
    monkeypatch.setenv("MADOSHO_JOB_GPUS_RESEARCH", "all")
    s = Settings.from_env()
    assert s.job_limits("ingest") == {"cpus": None, "memory": "2g", "gpus": None}
    assert s.job_limits("research")["gpus"] == "all"


def test_container_env_is_an_allowlist_forcing_inproc(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/d")
    monkeypatch.setenv("MADOSHO_LLM_API_KEY", "k")
    monkeypatch.setenv("SOME_SECRET", "leak-me")
    env = Settings.from_env().job_container_env()
    assert env["DATABASE_URL"].startswith("postgresql")
    assert env["MADOSHO_LLM_API_KEY"] == "k"
    assert env["MADOSHO_JOB_EXECUTOR"] == "inproc"   # no recursion in the job container
    assert "SOME_SECRET" not in env                  # not a blind copy


def test_container_env_passes_plane_vars(monkeypatch):
    """The three vars madosho_cli needs to reach the planes must pass through
    to the job container env, so container-mode research can call the API."""
    monkeypatch.setenv("MADOSHO_CONTROL_URL", "http://app:8000")
    monkeypatch.setenv("MADOSHO_QUERY_URL", "http://query:8001")
    monkeypatch.setenv("MADOSHO_API_KEY", "test-service-key")
    env = Settings.from_env().job_container_env()
    assert env["MADOSHO_CONTROL_URL"] == "http://app:8000"
    assert env["MADOSHO_QUERY_URL"] == "http://query:8001"
    assert env["MADOSHO_API_KEY"] == "test-service-key"


def test_mounts_parse_from_env(monkeypatch):
    monkeypatch.setenv("MADOSHO_JOB_MOUNTS",
                       "madosho_filestore:/data/filestore,madosho_hf_cache:/models")
    m = Settings.from_env().job_mounts()
    assert m == {"madosho_filestore": {"bind": "/data/filestore", "mode": "rw"},
                 "madosho_hf_cache": {"bind": "/models", "mode": "rw"}}
