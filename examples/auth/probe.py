"""Probe the madosho auth lock against a running stack.

Usage:
    MADOSHO_API_KEY=mdsh_... python examples/auth/probe.py [base_url]

With the flag on, expect: /health open (200), no key -> 401, a read key reads
(200) but cannot write (403), a write key writes (201). Stdlib only.

Admin key round-trip: set MADOSHO_ADMIN_KEY to an admin-scoped key to also
prove the browser cookie path for /auth/keys.  The section prints STATUS CODES
ONLY -- the raw key value is never printed.

    MADOSHO_API_KEY=mdsh_... MADOSHO_ADMIN_KEY=mdsh_... python examples/auth/probe.py
"""
import argparse
import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.request


def call(base, method, path, key=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    if key:
        req.add_header("Authorization", "Bearer " + key)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


def probe_admin_cookie_roundtrip(base, admin_key):
    """POST /auth/login with an admin key, then GET /auth/keys via the cookie.

    Prints STATUS CODES ONLY.  The raw admin key value is never printed.
    """
    print()
    print("-- admin key cookie round-trip --")
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    body = json.dumps({"key": admin_key}).encode()
    login_req = urllib.request.Request(
        base + "/auth/login", data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with opener.open(login_req) as resp:
            login_status = resp.status
    except urllib.error.HTTPError as e:
        login_status = e.code

    print("POST /auth/login   :", login_status)
    print("cookie names set   :", [c.name for c in jar] or "(none)")

    try:
        with opener.open(base + "/auth/keys") as resp:
            keys_status = resp.status
    except urllib.error.HTTPError as e:
        keys_status = e.code

    print("GET  /auth/keys    :", keys_status)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url", nargs="?", default="http://localhost:8000")
    args = parser.parse_args(argv)
    base = args.base_url.rstrip("/")
    key = os.environ.get("MADOSHO_API_KEY")

    print("health (open)      :", call(base, "GET", "/health"))
    print("no key   GET       :", call(base, "GET", "/corpora"))
    print("with key GET       :", call(base, "GET", "/corpora", key=key))
    print("with key POST      :", call(base, "POST", "/corpora", key=key,
                                        body={"name": "probe-corpus"}))

    admin_key = os.environ.get("MADOSHO_ADMIN_KEY")
    if admin_key:
        probe_admin_cookie_roundtrip(base, admin_key)
    else:
        print()
        print("(set MADOSHO_ADMIN_KEY to also run the admin cookie round-trip)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
