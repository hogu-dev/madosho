from __future__ import annotations

import json
import logging

logger = logging.getLogger("madosho_server.executor")

_STOP_GRACE_SECONDS = 30   # SIGTERM grace before docker escalates to SIGKILL


def _docker_client(docker_host: str | None):
    import docker   # lazy: only container mode needs docker-py
    if docker_host:
        return docker.DockerClient(base_url=docker_host)
    return docker.from_env()


class ContainerExecutor:
    """Backend B: run one job in its own container, resource-capped and
    hard-killed on timeout. Reaps the container on every exit path."""

    def __init__(self, settings, queue: str, client=None):
        self._settings = settings
        self._queue = queue
        self._client = client
        # Overridable in tests; real value set lazily once docker-py is imported.
        self._timeout_errors: tuple = ()

    def _client_or_make(self):
        if self._client is None:
            self._client = _docker_client(self._settings.docker_host)
            import requests.exceptions as rexc
            self._timeout_errors = (rexc.ReadTimeout, rexc.ConnectionError)
        return self._client

    def _resource_kwargs(self) -> dict:
        limits = self._settings.job_limits(self._queue)
        kw: dict = {}
        if limits["cpus"]:
            kw["nano_cpus"] = int(float(limits["cpus"]) * 1_000_000_000)
        if limits["memory"]:
            kw["mem_limit"] = limits["memory"]
        if limits["gpus"]:
            import docker
            count = -1 if limits["gpus"] in ("all", "-1") else int(limits["gpus"])
            kw["device_requests"] = [
                docker.types.DeviceRequest(count=count, capabilities=[["gpu"]])]
        return kw

    def run(self, name: str, kwargs: dict) -> None:
        client = self._client_or_make()
        timeout = self._settings.job_timeout_for(self._queue)
        container = client.containers.run(
            image=self._settings.job_image,
            command=["madosho-run-job", name, json.dumps(kwargs)],
            environment=self._settings.job_container_env(),
            volumes=self._settings.job_mounts(),
            network=self._settings.job_network,
            detach=True,
            stop_signal="SIGTERM",
            **self._resource_kwargs(),
        )
        try:
            result = container.wait(timeout=timeout)
            code = result.get("StatusCode", 0)
            if code != 0:
                raise RuntimeError(f"job {name} container exited with {code}")
        except self._timeout_errors:
            logger.warning("job %s exceeded %ss; stopping container", name, timeout)
            try:
                container.stop(timeout=_STOP_GRACE_SECONDS)
            except Exception:
                logger.exception("failed to stop timed-out job %s", name)
            raise TimeoutError(f"job {name} exceeded {timeout}s")
        finally:
            try:
                container.remove(force=True)
            except Exception:
                logger.exception("failed to reap job container for %s", name)
