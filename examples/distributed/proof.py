"""Prove the madosho toolserver pass-through model against a running stack.

Usage:
    MADOSHO_API_KEY=mdsh_... python examples/distributed/proof.py

What this proves:
    The toolserver (:8088) holds no API key of its own. It forwards each caller's
    Authorization: Bearer header to the madosho control/query API, which enforces
    THAT caller's scope. This script routes two calls through the toolserver using
    your MADOSHO_API_KEY:

      READ  via proxy: POST :8088/list-corpora  -> 200 (any valid key works)
      WRITE via proxy: POST :8088/create-corpus -> 403 (read key enforced by API)
                                              OR -> 201 (write key, also proves forwarding)

    RECOMMENDED: run this with a READ-scoped key (expect read 200 + write 403). That
    403 is the canonical, unambiguous proof: it can only happen if the proxy forwarded
    the caller's real read key and the API enforced read scope. If the toolserver had
    injected its own ambient write key, the write would have succeeded (201) even with
    a read-only caller key -- that is the exact failure this script guards against.

    A write key getting 201 is only CONDITIONAL proof: a status code cannot tell
    "caller's write key forwarded" apart from "caller's read key + injected write key",
    so a 201 is a pass only when you KNOW the key is write-scoped. Run with a read key
    for the clean proof.

    A 401 on any call means the key is missing or invalid.

Env:
    MADOSHO_API_KEY         - required: the caller's API key (value stays in env only)
    MADOSHO_TOOLSERVER_URL  - optional: default http://localhost:8088

Stdlib only.
"""
import json
import os
import sys
import urllib.error
import urllib.request


def _call(base, path, key, body=None):
    """POST to base+path with the caller's bearer key. Returns the HTTP status code.

    Returns the upstream HTTP status on success or HTTPError.  Prints a clean
    message and exits non-zero on URLError (stack unreachable) so the proof gives
    a useful diagnostic rather than a raw traceback.
    """
    data = json.dumps(body).encode() if body is not None else b"{}"
    req = urllib.request.Request(base + path, data=data, method="POST")
    req.add_header("Authorization", "Bearer " + key)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except urllib.error.URLError as e:
        print(f"FAIL: could not reach {base}{path}: {e.reason}")
        print("      Is the stack up? (docker compose ps; check :8088)")
        sys.exit(1)


def main():
    key = os.environ.get("MADOSHO_API_KEY", "")
    if not key:
        print("FAIL: MADOSHO_API_KEY is not set")
        print("      Set it to your API key and retry:")
        print("      MADOSHO_API_KEY=mdsh_... python examples/distributed/proof.py")
        return 1

    proxy = os.environ.get("MADOSHO_TOOLSERVER_URL", "http://localhost:8088").rstrip("/")

    print(f"Toolserver : {proxy}")
    print(f"Key prefix : {key[:12]}...")
    print()

    # ------------------------------------------------------------------
    # Step 1: READ through the proxy.
    #
    # list-corpora is a read operation on the control plane. The toolserver
    # receives the POST, strips the body, and calls the control plane's
    # GET /corpora -- forwarding the caller's bearer header. Any valid key
    # (read or write scope) should get 200 back.
    # ------------------------------------------------------------------
    print("Step 1: READ via proxy  (POST /list-corpora)")
    read_status = _call(proxy, "/list-corpora", key, body={})
    print(f"  -> HTTP {read_status}")

    if read_status == 401:
        print("FAIL: 401 on read -- key is missing or invalid")
        print("      Mint a key: madosho-keys create --name test --scope read")
        return 1

    if read_status == 200:
        print("  OK: read reached the API (toolserver forwarded the key)")
    else:
        print(f"FAIL: expected 200 on read, got {read_status} -- check stack logs")
        return 1

    print()

    # ------------------------------------------------------------------
    # Step 2: WRITE through the proxy.
    #
    # create-corpus is a write operation (POST /corpora on the control plane).
    # The toolserver has no ambient key of its own; it forwards the caller's
    # bearer. The control plane then enforces THAT caller's scope:
    #
    #   403 -> the API received a READ key and rejected the write. The
    #          toolserver did NOT inject its own write key. This is the clean
    #          proof of pass-through with a read-scoped caller key.
    #
    #   201 -> the API allowed the create. This is CONDITIONAL proof: it confirms
    #          pass-through only if the caller's key is actually write-scoped. A
    #          status code cannot distinguish "caller's write key forwarded" from
    #          "caller's READ key + toolserver injected an ambient write key" -- so
    #          a 201 with a read key is the failure mode, not a pass.
    #
    # The failure this script guards against: if the toolserver injected its
    # own write key, a caller with a read key would still see 201 here -- the
    # toolserver's write key would have bypassed the caller's scope restriction.
    # That is why the READ-key -> 403 path is the canonical, unambiguous proof.
    # ------------------------------------------------------------------
    corpus_name = "distributed-proof-corpus"
    print(f"Step 2: WRITE via proxy (POST /create-corpus name={corpus_name!r})")
    write_status = _call(proxy, "/create-corpus", key, body={"name": corpus_name})
    print(f"  -> HTTP {write_status}")

    if write_status == 401:
        print("FAIL: 401 on write -- key became invalid between steps (unexpected)")
        return 1

    if write_status == 403:
        # The API saw the caller's read key and blocked the write.
        # The toolserver did not substitute a write key.
        print("  OK: read key -> 403 on write (API enforced the caller's scope;")
        print("      toolserver did not inject an ambient write key)")
        print()
        print("PASS: pass-through proven with a READ-scoped key")
        print("      Re-run with a write key to confirm writes also pass through.")
        return 0

    # 200/201 are the success codes for create-corpus (the control plane returns
    # 201 Created; 200 is accepted defensively in case a variant returns it). 202
    # would only appear if create were ever made async; accepted here so the proof
    # does not spuriously fail on a deployment that deferred the create.
    if write_status in (200, 201, 202):
        # CONDITIONAL proof. A success here is only meaningful if the caller's key
        # is actually WRITE-scoped. The script cannot tell from the status code
        # alone whether this 201 means "caller's write key forwarded correctly" or
        # "caller's READ key + the toolserver injected an ambient write key" -- the
        # exact regression this script exists to catch. So we cannot declare an
        # unambiguous PASS here; we report a conditional pass and tell the user how
        # to get the clean proof.
        print("  OK: write succeeded through the proxy")
        print("  NOTE: this proves pass-through ONLY if your key is write-scoped.")
        print("        If your key is READ-scoped, a success here is a FAIL --")
        print("        it means the toolserver may have injected an ambient write key.")
        print("        For the unambiguous proof, run with a READ key and expect 403.")
        print()
        print("PASS (write-scoped key): write forwarded through the proxy")
        return 0

    print(f"FAIL: unexpected status {write_status} on write -- check stack logs")
    return 1


if __name__ == "__main__":
    sys.exit(main())
