"""Prove the madosho browser cookie flow against a running stack. Stdlib only.

Usage:
    MADOSHO_API_KEY=mdsh_... python examples/auth/login.py [base_url]

Posts the key to /auth/login, captures the httpOnly Set-Cookie, then makes an
authenticated GET /corpora carrying only that cookie (no Authorization header) -
the same path the browser takes after the login form.
"""
import argparse
import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.request


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url", nargs="?", default="http://localhost:8000")
    args = parser.parse_args(argv)
    base = args.base_url.rstrip("/")
    key = os.environ.get("MADOSHO_API_KEY") or ""

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    body = json.dumps({"key": key}).encode()
    login = urllib.request.Request(base + "/auth/login", data=body, method="POST",
                                   headers={"Content-Type": "application/json"})
    try:
        with opener.open(login) as resp:
            print("login              :", resp.status, resp.read().decode())
    except urllib.error.HTTPError as e:
        print("login              :", e.code, "(check MADOSHO_API_KEY)")
        return 1
    except urllib.error.URLError as e:
        print("login              : server unreachable -", e.reason)
        return 1

    print("session cookie set :", [c.name for c in jar] or "(none)")

    try:
        with opener.open(base + "/corpora") as resp:        # cookie rides automatically
            print("cookie GET /corpora:", resp.status)
    except urllib.error.HTTPError as e:
        print("cookie GET /corpora:", e.code)
    except urllib.error.URLError as e:
        print("cookie GET /corpora: server unreachable -", e.reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
