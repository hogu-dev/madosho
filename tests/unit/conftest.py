"""
Unit-test conftest: auth off by default, on when marked authed.

The suite models an open single-operator server by default.  Tests for
authenticated behavior (test_auth_keys, test_web_login, etc.) opt in
explicitly by calling monkeypatch.setenv("MADOSHO_AUTH_ENABLED", "1") inside
their own scope, which overrides the value set here.

Why: MADOSHO_AUTH_ENABLED defaults ON.  All pre-auth
unit tests that hit the API without a key would 401 unless we set the flag off
here.  The single autouse fixture is cleaner than patching every caller.

The fixture is marker-aware: tests decorated with @pytest.mark.authed receive
flag=ON from the fixture itself, so a future authed test that forgets the
in-body setenv cannot silently run open.
"""
import pytest


@pytest.fixture(autouse=True)
def auth_off_by_default(monkeypatch, request):
    """Set auth flag OFF by default; ON when the test carries @pytest.mark.authed.

    Marker-aware so a future authed test that omits the in-body setenv cannot
    silently run against an open server and pass for the wrong reason.
    """
    flag = "1" if request.node.get_closest_marker("authed") else "0"
    monkeypatch.setenv("MADOSHO_AUTH_ENABLED", flag)
