import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not installed")
def test_compose_file_is_valid():
    # `docker compose config` parses + validates compose.yaml without starting anything
    result = subprocess.run(["docker", "compose", "-f", str(ROOT / "compose.yaml"), "config"],
                            capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    assert "version" not in result.stdout.splitlines()[0].lower()  # no obsolete version key


def _services(profile=None):
    cmd = ["docker", "compose", "-f", str(ROOT / "compose.yaml")]
    if profile:
        cmd += ["--profile", profile]
    cmd += ["config", "--services"]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    return set(result.stdout.split())


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not installed")
def test_toolserver_service_is_default():
    services = _services()
    assert "toolserver" in services
    # Open WebUI is profile-gated: NOT up on a bare `docker compose up`
    assert "open-webui" not in services


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not installed")
def test_open_webui_behind_frontend_profile():
    assert "open-webui" in _services(profile="frontend")


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not installed")
def test_tls_overlay_is_additive():
    # The TLS overlay must merge cleanly, add Caddy's four HTTPS ports, and
    # leave every plain-HTTP door published exactly as before (HTTPS is opt-in
    # per client; closing HTTP is the user's own override, not the overlay's).
    import yaml

    cmd = ["docker", "compose",
           "-f", str(ROOT / "compose.yaml"),
           "-f", str(ROOT / "compose.tls.yaml"),
           "config"]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    services = yaml.safe_load(result.stdout)["services"]

    caddy_published = {str(p["published"]) for p in services["caddy"]["ports"]}
    assert {"8443", "8444", "8445", "8446"} <= caddy_published

    doors = {"app": "8000", "query": "8001", "toolserver": "8088", "ui": "8080"}
    for svc, port in doors.items():
        published = {str(p["published"]) for p in services[svc]["ports"]}
        assert port in published, f"{svc}: plain-HTTP port {port} must stay open"
