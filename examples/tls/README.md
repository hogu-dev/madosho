# TLS for madosho - the Caddy overlay

An opt-in compose overlay that adds HTTPS to every madosho door. Clients that
connect through the HTTPS ports stop sending API keys and login cookies as
cleartext, and the browser accepts the Secure session cookie without
`MADOSHO_COOKIE_INSECURE=1`.

The overlay is purely additive: the plain-HTTP ports keep working exactly as
before, so nothing breaks and you can move clients over one at a time. Nothing
in madosho itself changes - a Caddy container terminates TLS and forwards to
the same services over the internal compose network.

**Warning - HTTP stays open.** Anything still talking to the plain-HTTP ports
(8000/8001/8080/8088) sends keys and cookies unencrypted across the network.
That is fine on a trusted LAN or VPN; over anything wider, point every remote
client at the HTTPS ports - and consider closing plain HTTP entirely (last
section below).

## Start it

```bash
MADOSHO_TLS_HOST=my-server docker compose -f compose.yaml -f compose.tls.yaml up
```

`MADOSHO_TLS_HOST` is the hostname or IP clients will use to reach the machine
(also settable in `.env`). Caddy issues its certificate for exactly that name -
if you connect by a different name, the certificate won't match. Default:
`localhost`.

| HTTPS port | Door | Plain-HTTP twin (still open) |
|------------|-----------------------------|-------|
| 8443 | web workbench | 8080 |
| 8444 | control plane | 8000 |
| 8445 | query plane | 8001 |
| 8446 | toolserver | 8088 |

Browsers only need 8443 - the workbench proxies its own `/api/*` calls
internally. Ports 8444-8446 are for programmatic clients (CLI, MCP, agents,
Open WebUI); they never appear in a human-facing URL.

**Want the workbench at plain `https://my-server`, no port?** Add one line to
the caddy service's ports in `compose.tls.yaml`:

```yaml
      - "443:8443"    # workbench also on the default HTTPS port
```

Same listener, same certificate - the URL just loses its port. Not on by
default so the overlay never fights another service already using 443 on
your machine.

## Certificates - three modes

### 1. Self-signed via Caddy's local CA (default, zero setup)

Out of the box the Caddyfile sets `local_certs`: Caddy signs certificates with
its own local certificate authority. No public domain needed; works for bare
IPs and LAN hostnames. Clients trust the CA's root certificate once instead of
clicking through warnings:

```bash
docker compose -f compose.yaml -f compose.tls.yaml cp \
    caddy:/data/caddy/pki/authorities/local/root.crt madosho-ca.crt
```

Copy `madosho-ca.crt` to each client machine, then:

- **Browser / OS:** import it as a trusted root certificate authority
  (Windows: certmgr; macOS: Keychain Access; Linux: your distro's
  `update-ca-certificates` flow).
- **madosho's Python clients** (CLI, MCP server, example scripts - they use
  the Python standard library):

  ```bash
  export SSL_CERT_FILE=/path/to/madosho-ca.crt
  ```

Skipping the trust step still gives you encryption, just with certificate
errors: `curl -k` works for a quick poke, but don't run real clients with
verification off.

### 2. Bring your own certificates

Already have a cert (company CA, wildcard cert, mkcert)? Put `cert.pem` and
`key.pem` in `examples/tls/certs/`, uncomment the `./examples/tls/certs:/certs:ro`
volume in `compose.tls.yaml`, and in the Caddyfile remove `local_certs` and add
one line inside each site block:

```
https://{$MADOSHO_TLS_HOST}:8443 {
	tls /certs/cert.pem /certs/key.pem
	reverse_proxy ui:8080
}
```

Renewal is yours: replace the files and `docker compose restart caddy`.

### 3. Public domain via Let's Encrypt (cloud VM)

If the machine has a real domain pointing at it, let Caddy fetch
publicly-trusted certificates automatically. Edit the Caddyfile:

1. Remove the `local_certs` line.
2. Replace the four site addresses with subdomains on the default port, e.g.:

   ```
   https://madosho.example.com        { reverse_proxy ui:8080 }
   https://api.madosho.example.com    { reverse_proxy app:8000 }
   https://query.madosho.example.com  { reverse_proxy query:8001 }
   https://tools.madosho.example.com  { reverse_proxy toolserver:8088 }
   ```

3. In `compose.tls.yaml`, publish `"80:80"` and `"443:443"` on the caddy
   service (Let's Encrypt validates the domain over those ports).

Certificates renew automatically; no trust step needed on clients.

## Point clients at the HTTPS ports

Exactly like plain HTTP, with `https://` and the new ports:

```bash
export MADOSHO_CONTROL_URL=https://my-server:8444
export MADOSHO_QUERY_URL=https://my-server:8445
export MADOSHO_API_KEY=mdsh_...
```

The workbench lives at `https://my-server:8443`. The login cookie is Secure by
default and works as designed over HTTPS - leave `MADOSHO_COOKIE_INSECURE`
unset.

## Optional: close plain HTTP (HTTPS-only)

If every client speaks HTTPS, bind the plain-HTTP ports to loopback so they
stay usable on the stack machine but disappear from the network. Add a small
override of your own (e.g. `compose.https-only.yaml`) and include it last:

```yaml
services:
  app:
    ports: !override ["127.0.0.1:8000:8000"]
  query:
    ports: !override ["127.0.0.1:8001:8001"]
  toolserver:
    ports: !override ["127.0.0.1:8088:8088"]
  ui:
    ports: !override ["127.0.0.1:8080:8080"]
```

```bash
docker compose -f compose.yaml -f compose.tls.yaml -f compose.https-only.yaml up
```

(A host firewall blocking 8000/8001/8080/8088 from outside achieves the same.)

## Notes

- Caddy stores its CA and certificates in the `caddy_data` volume; they
  survive restarts. Deleting the volume mints a NEW root CA, so clients
  would need to re-trust it.
- The optional Open WebUI profile is not proxied by this overlay; if you use
  it remotely, front it the same way (one more site block) or keep it local.
