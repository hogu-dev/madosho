# examples/distributed/

Proves the madosho toolserver pass-through model.

## What it proves

The toolserver (`:8088`) holds no API key of its own. It forwards each caller's
`Authorization: Bearer` header to the madosho control/query API, which enforces
THAT caller's scope.

`proof.py` routes two calls through the toolserver using your `MADOSHO_API_KEY`:

1. **Read** (list-corpora) -- succeeds (200) with any valid key.
2. **Write** (create-corpus) -- result depends on the key's scope:
   - Read key: the API 403s. This is the canonical, unambiguous proof -- a 403 can
     only happen if the proxy forwarded your real read key and the API enforced
     read scope. An ambient write key injected by the toolserver would have made
     this write succeed instead.
   - Write key: the write succeeds (201). This is only CONDITIONAL proof -- a 201
     confirms pass-through only if you KNOW the key is write-scoped. A status code
     cannot tell "your write key was forwarded" apart from "your read key plus an
     injected write key", so a 201 with a read key is the failure mode, not a pass.

**Recommended:** run with a READ-scoped key and expect read 200 + write 403. That is
the clean proof. The write-key path (200 + 201) is a softer, conditional check.

A 401 on either call means the key is missing or invalid.

## How to run

**Start the stack** (auth is on by default):

```
docker compose up
```

**Create a key if needed** (on the host running the stack):

```
madosho-keys create --name demo --scope read
```

Copy the printed key value (it is shown once) and export it:

```
export MADOSHO_API_KEY=mdsh_...
```

**Run the proof** against the local toolserver:

```
python examples/distributed/proof.py
```

**Override the toolserver URL** to reach a remote stack:

```
MADOSHO_TOOLSERVER_URL=http://your-host:8088 python examples/distributed/proof.py
```

For reach-from-another-machine scenarios (overriding the control and query plane
URLs as well), see the "Reach the stack from another machine" section in
`docs/HEADLESS.md`.

## Expected output

With a **read-scoped key**:

```
Toolserver : http://localhost:8088
Key prefix : mdsh_abc123...

Step 1: READ via proxy  (POST /list-corpora)
  -> HTTP 200
  OK: read reached the API (toolserver forwarded the key)

Step 2: WRITE via proxy (POST /create-corpus name='distributed-proof-corpus')
  -> HTTP 403
  OK: read key -> 403 on write (API enforced the caller's scope;
      toolserver did not inject an ambient write key)

PASS: pass-through proven with a READ-scoped key
```

With a **write-scoped key**:

```
Toolserver : http://localhost:8088
Key prefix : mdsh_abc123...

Step 1: READ via proxy  (POST /list-corpora)
  -> HTTP 200
  OK: read reached the API (toolserver forwarded the key)

Step 2: WRITE via proxy (POST /create-corpus name='distributed-proof-corpus')
  -> HTTP 201
  OK: write succeeded through the proxy
  NOTE: this proves pass-through ONLY if your key is write-scoped.
        If your key is READ-scoped, a success here is a FAIL --
        it means the toolserver may have injected an ambient write key.
        For the unambiguous proof, run with a READ key and expect 403.

PASS (write-scoped key): write forwarded through the proxy
```
