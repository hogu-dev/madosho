# madosho Auth

madosho's two HTTP planes (control `:8000`, query `:8001`) are gated by per-client
API keys when `MADOSHO_AUTH_ENABLED` is on. The flag defaults ON: a fresh
stack rejects unauthenticated requests (401) and under-scoped write attempts (403).
For an open single-operator dev box, set `MADOSHO_AUTH_ENABLED=0` explicitly.

## Scopes

`read` < `write` < `admin`. A higher scope satisfies any lower requirement.
- `read` - reach all reads (GET on the control plane; everything on the query plane).
- `write` - also reach control-plane writes (POST/PUT/DELETE).
- `admin` - also manage keys and users over HTTP (the `/auth/keys` endpoints and
  the Keys/Users pages).

## Managing keys (host)

Keys are minted on the server box. The value is printed once and only its hash is
stored. In a compose deployment, run the CLI inside the app container:

    docker compose exec app python -m madosho_server.keys_cli create --name ci-uploader --scope write
    docker compose exec app python -m madosho_server.keys_cli list      # name | prefix | scope | ...
    docker compose exec app python -m madosho_server.keys_cli revoke ci-uploader

(With madosho pip-installed on the host, the same commands are available as
`madosho-keys create|list|revoke`.)

Clients read the value from `MADOSHO_API_KEY` (set out-of-band; `.env.example` has the
placeholder). Never paste a key into chat or commit it.

## Managing keys from the browser

The Keys page lets an operator mint, inspect, and revoke keys without a shell session.
The host CLI remains the bootstrap and break-glass path; the browser UI is a convenience
layer on top.

**Step 1 - bootstrap an admin key on the host** (one-time, out-of-band):

    docker compose exec app python -m madosho_server.keys_cli create --name root-admin --scope admin

The raw key is printed once. Copy it somewhere safe (password manager). The server
stores only its hash, so there is no way to recover the value later.

**Step 2 - unlock the Keys page in the browser:**

1. Open the UI and click Keys in the nav.
2. The page shows an unlock form. Paste the admin key into the field and submit.
3. The server validates the key and sets the httpOnly session cookie
   (`madosho_session`). The raw key never touches browser storage; JavaScript cannot
   read the cookie.
4. The page transitions to the key table view.

**Step 3 - manage keys:**

- Mint: fill in a name and scope (read / write / admin), click Create. The new key is
  shown once in a modal. Copy it before closing - the server will never reveal it again.
- List: the table shows name, prefix (first 12 chars), scope, and created/last-used
  dates. The hash is never returned by the API.
- Revoke: click Revoke next to a key. The server refuses to revoke the last remaining
  admin key (returns 409) to prevent locking yourself out.

**Scopes available from the browser:** read, write, admin. An admin key can grant any
scope including admin itself.

**Session scope note:** unlocking the Keys page sets the shared `madosho_session` cookie for
the whole browser tab, elevating that session to the admin scope. Logout (or switching to a
different key via the unlock form) logs out the entire app, not just the Keys page - so an
operator who unlocks keys mid-session should expect to re-authenticate for normal use afterward.

**Break-glass:** if the browser session is lost or the admin key is compromised, mint a
replacement on the host with the keys CLI, then revoke the old one from the Keys page or
from the CLI.

## User accounts (username/password)

Humans log in with a username and password; API keys remain for machines/agents. A
user carries a scope (`read`/`write`/`admin`) exactly like a key, and an `admin` user
can manage both users and keys from the browser.

### Bootstrap the first admin (host, once)

    docker compose exec app python -m madosho_server.users_cli create --name admin --scope admin
    # prompts for the password (getpass) - never an argv flag, never in chat

Or seed it from the environment (compose/secrets): set
`MADOSHO_BOOTSTRAP_ADMIN_USER` and `MADOSHO_BOOTSTRAP_ADMIN_PASSWORD`; on init, if no
active admin user exists, one is created. Idempotent.

### Manage users (host)

    docker compose exec app python -m madosho_server.users_cli list
    docker compose exec app python -m madosho_server.users_cli deactivate --name alice
    docker compose exec app python -m madosho_server.users_cli reset-password --name alice   # prompts

### Manage users (browser)

Log in as an admin, open **Users**: create accounts (username, scope, initial
password), deactivate, or reset a password. The last active admin user cannot be
deactivated (409). Any logged-in user can change their own password.

### Keys vs users

- **Users** = humans, username + password, managed under **Users**.
- **Keys** = machines/agents/CLI, bearer tokens, managed under **Keys**.
- Both issue the same signed `madosho_session` cookie on login and flow through the
  same `read < write < admin` gates. The admin key + the host CLIs remain break-glass.

## Quick proof

    MADOSHO_API_KEY=mdsh_... python examples/auth/probe.py http://madosho-host:8000

(`madosho-host` throughout these docs means the machine running the stack - use
`localhost` when the Docker stack runs on the machine you're typing on, its
hostname or IP when it runs elsewhere.)

## Browser login

The web UI never holds a raw key in JavaScript. Instead it posts the key once and the
server hands back a signed, httpOnly session cookie:

    POST /auth/login   {"key": "mdsh_..."}   -> 200 {scope, name} + Set-Cookie
    GET  /auth/me                            -> {authenticated, auth_required, scope, name}
    POST /auth/logout                        -> clears the cookie

The cookie (`madosho_session`) is httpOnly (page JS cannot read it), SameSite=Strict,
and a 12h sliding window (each authenticated request refreshes it). It carries only the
key id, scope, and expiry - never the raw key - signed (HMAC-SHA256) with
`MADOSHO_SESSION_SECRET`. Set that secret in production so sessions survive a restart and
agree across replicas; unset, the server uses a random per-process secret.

The cookie is `Secure` by default. Browsers accept Secure cookies on `http://localhost`,
so local dev works as-is; for anything remote, run the TLS overlay
(`examples/tls/README.md`) and the Secure cookie works as designed. Dev-only
fallback for plain HTTP: `MADOSHO_COOKIE_INSECURE=1`. Reads and writes both
honor the cookie on either plane.

While `MADOSHO_AUTH_ENABLED` is off, `/auth/me` reports `auth_required: false` and the UI
runs open; once it is on, the UI shows a login and read-scoped keys see a read-only banner.

Quick proof against a running stack:

    MADOSHO_API_KEY=mdsh_... python examples/auth/login.py http://madosho-host:8000

## Pass-through model

Each door uses per-client keys. The two network proxies - the toolserver (`:8088`)
and MCP-over-HTTP - hold no API key of their own. They forward each caller's
incoming `Authorization: Bearer` header to the control/query API, which enforces
THAT caller's scope:

- A read key routed through the toolserver can list corpora (200) but cannot create
  one (403). The API enforced the caller's scope; the toolserver did not inject its
  own key.
- A write key through the same proxy can read and write.
- The CLI and MCP-stdio read `MADOSHO_API_KEY` directly from their own environment
  (no proxy forwarding needed - they are the first caller).

This means the LOCK, not the bind address, makes binding on `0.0.0.0` safe for a
trusted LAN: every call is authenticated at the API by the caller's actual key. For
off-host exposure over untrusted networks, put a TLS-terminating reverse proxy in
front (see `docs/HEADLESS.md` - "Reach the stack from another machine").

Runnable proof: `examples/distributed/proof.py` routes calls through the toolserver
with your key and prints PASS when it sees 403 on a write with a read key (proving
the proxy forwarded YOUR key, not an ambient write key) or PASS when a write key
succeeds end-to-end (also proving forwarding).
