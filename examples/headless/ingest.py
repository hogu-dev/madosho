"""Headless document ingest via base64.

Usage:
    MADOSHO_API_KEY=mdsh_... python examples/headless/ingest.py [control_url] [query_url]

Demonstrates the full headless write flow: create corpus, ingest base64,
poll until indexed, then query. Stdlib only.
"""
import argparse
import base64
import json
import os
import sys
import time
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
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"error": body}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("control_url", nargs="?", default="http://localhost:8000")
    parser.add_argument("query_url", nargs="?", default="http://localhost:8001")
    args = parser.parse_args(argv)
    control = args.control_url.rstrip("/")
    query = args.query_url.rstrip("/")
    key = os.environ.get("MADOSHO_API_KEY")

    print("Step 1: create corpus 'headless-demo'")
    status, resp = call(control, "POST", "/corpora", key=key,
                        body={"name": "headless-demo"})
    if status not in (200, 201, 202):
        print(f"  ERROR: {status} {resp}")
        return 1
    corpus_id = resp["id"]
    print(f"  OK: corpus id={corpus_id}")

    print("\nStep 2: base64-encode a tiny document")
    doc_text = "This is a demo document about madosho.\nIt demonstrates headless ingest."
    content_b64 = base64.b64encode(doc_text.encode()).decode()
    print(f"  OK: {len(doc_text)} bytes -> {len(content_b64)} chars base64")

    print("\nStep 3: POST /documents/ingest with base64 + corpus")
    status, resp = call(control, "POST", "/documents/ingest", key=key,
                        body={"filename": "demo.txt", "content_b64": content_b64,
                              "corpus": "headless-demo"})
    if status not in (200, 201, 202):
        print(f"  ERROR: {status} {resp}")
        return 1
    doc_id = resp["id"]
    print(f"  OK: document id={doc_id}, status={resp.get('status', 'unknown')}")

    print("\nStep 4: poll GET /documents/{id} until indexed or failed")
    start = time.monotonic()
    timeout = 120
    interval = 2
    while True:
        elapsed = time.monotonic() - start
        if elapsed > timeout:
            print(f"  ERROR: timeout after {timeout}s")
            return 1
        status, resp = call(control, "GET", f"/documents/{doc_id}", key=key)
        if status != 200:
            print(f"  ERROR: {status} {resp}")
            return 1
        doc_status = resp.get("status")
        print(f"  {elapsed:.1f}s: status={doc_status}")
        if doc_status == "indexed":
            print(f"  OK: document indexed")
            break
        elif doc_status == "failed":
            error = resp.get("error")
            print(f"  ERROR: document failed: {error}")
            return 1
        time.sleep(interval)

    print(f"\nStep 5: POST {query}/query to search the indexed document")
    status, resp = call(query, "POST", "/query", key=key,
                        body={"prompt": "madosho demo", "corpus": "headless-demo"})
    if status not in (200, 201, 202):
        print(f"  ERROR: {status} {resp}")
        return 1
    hits = resp.get("hits", [])
    print(f"  OK: got {len(hits)} hit(s)")
    for i, h in enumerate(hits, 1):
        print(f"    {i}. score={h.get('score'):.2f} snippet={h.get('text', '')[:60]}")

    print("\nHeadless ingest complete!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
