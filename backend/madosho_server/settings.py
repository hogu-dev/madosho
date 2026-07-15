from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str       # SQLAlchemy form: postgresql+psycopg://...
    qdrant_url: str
    filestore_dir: str
    corpora_dir: str        # kernel per-corpus state (manifest etc.)
    kb_dir: str = "/data/kbs"   # server-owned KB folders (llmkb v1), one per kb-<id>
    llm_api_key: str | None = None
    llm_api_base: str | None = None
    # Index-time LLM (e.g. the contextual chunker situating chunks at build time).
    # No default provider, same posture as the eval golden-set llm: a component
    # that needs it fails clearly when these are unset. Reuses llm_api_* creds.
    index_llm_provider: str | None = None
    index_llm_model: str | None = None
    auth_enabled: bool = True
    session_secret: str | None = None
    cookie_insecure: bool = False
    bootstrap_admin_user: str | None = None
    bootstrap_admin_password: str | None = None
    job_executor: str = "inproc"
    job_image: str = "madosho:local"
    docker_host: str | None = None
    job_network: str | None = None
    query_url: str | None = None   # control plane -> query plane, for KB semantic search proxy

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.environ.get(
                "DATABASE_URL",
                "postgresql+psycopg://madosho:madosho@localhost:5432/madosho"),
            qdrant_url=os.environ.get("QDRANT_URL", "http://localhost:6333"),
            filestore_dir=os.environ.get("FILESTORE_DIR", "/data/filestore"),
            corpora_dir=os.environ.get("CORPORA_DIR", "/data/corpora"),
            kb_dir=os.environ.get("KB_DIR", "/data/kbs"),
            llm_api_key=os.environ.get("MADOSHO_LLM_API_KEY") or None,
            llm_api_base=os.environ.get("MADOSHO_LLM_API_BASE") or None,
            index_llm_provider=os.environ.get("MADOSHO_INDEX_LLM_PROVIDER") or None,
            index_llm_model=os.environ.get("MADOSHO_INDEX_LLM_MODEL") or None,
            auth_enabled=os.environ.get("MADOSHO_AUTH_ENABLED", "").lower()
                         not in {"0", "false", "no"},
            session_secret=os.environ.get("MADOSHO_SESSION_SECRET") or None,
            cookie_insecure=os.environ.get("MADOSHO_COOKIE_INSECURE", "").lower()
                            in {"1", "true", "yes"},
            bootstrap_admin_user=os.environ.get("MADOSHO_BOOTSTRAP_ADMIN_USER") or None,
            bootstrap_admin_password=os.environ.get("MADOSHO_BOOTSTRAP_ADMIN_PASSWORD") or None,
            job_executor=os.environ.get("MADOSHO_JOB_EXECUTOR") or "inproc",
            job_image=os.environ.get("MADOSHO_JOB_IMAGE") or "madosho:local",
            docker_host=os.environ.get("MADOSHO_DOCKER_HOST") or None,
            job_network=os.environ.get("MADOSHO_JOB_NETWORK") or None,
            query_url=os.environ.get("MADOSHO_QUERY_URL") or None,
        )


    _ENV_ALLOWLIST = (
        "DATABASE_URL", "QDRANT_URL", "FILESTORE_DIR", "CORPORA_DIR", "KB_DIR", "HF_HOME",
        "MADOSHO_LLM_API_KEY", "MADOSHO_LLM_API_BASE",
        "MADOSHO_INDEX_LLM_PROVIDER", "MADOSHO_INDEX_LLM_MODEL",
        "MADOSHO_AUTH_ENABLED", "MADOSHO_SESSION_SECRET",
        # The three vars madosho_cli needs to reach + authenticate to the planes.
        # A research job container shells out to madosho_cli, which reads these.
        # MADOSHO_JOB_EXECUTOR is NOT included: job_container_env() force-sets it
        # to "inproc" below to prevent job containers from spawning sub-containers.
        "MADOSHO_CONTROL_URL", "MADOSHO_QUERY_URL", "MADOSHO_API_KEY",
    )

    def executor_for_queue(self, queue: str) -> str:
        return (os.environ.get(f"MADOSHO_JOB_EXECUTOR_{queue.upper()}")
                or self.job_executor or "inproc")

    def job_timeout_for(self, queue: str) -> int | None:
        v = (os.environ.get(f"MADOSHO_JOB_TIMEOUT_{queue.upper()}")
             or os.environ.get("MADOSHO_JOB_TIMEOUT"))
        return int(v) if v else None

    def job_limits(self, queue: str) -> dict:
        def pick(base: str) -> str | None:
            return (os.environ.get(f"MADOSHO_JOB_{base}_{queue.upper()}")
                    or os.environ.get(f"MADOSHO_JOB_{base}") or None)
        return {"cpus": pick("CPUS"), "memory": pick("MEMORY"), "gpus": pick("GPUS")}

    def job_container_env(self) -> dict[str, str]:
        env = {k: os.environ[k] for k in self._ENV_ALLOWLIST if k in os.environ}
        env["MADOSHO_JOB_EXECUTOR"] = "inproc"   # the job container must not recurse
        return env

    def job_mounts(self) -> dict:
        raw = os.environ.get("MADOSHO_JOB_MOUNTS", "")
        out = {}
        for pair in (p.strip() for p in raw.split(",") if p.strip()):
            src, _, dst = pair.partition(":")
            out[src] = {"bind": dst, "mode": "rw"}
        return out


def pg_conninfo(database_url: str) -> str:
    """procrastinate/psycopg want a libpq URL without SQLAlchemy's +driver tag."""
    return database_url.replace("+psycopg", "", 1)
