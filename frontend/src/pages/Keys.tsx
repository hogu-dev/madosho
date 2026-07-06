// frontend/src/pages/Keys.tsx
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { ApiKeyRow, MintedKey } from "../api/client";
import { Heading, Panel, EmptyState, Button } from "../design/primitives";
import { useAuth } from "../auth/AuthContext";

export function Keys() {
  const { scope, login, logout } = useAuth();

  // Unlock form (scope == null)
  const [unlockKey, setUnlockKey] = useState("");
  const [unlockError, setUnlockError] = useState<string | null>(null);

  // Key list (scope === "admin")
  const [keys, setKeys] = useState<ApiKeyRow[]>([]);
  const [listError, setListError] = useState<string | null>(null);

  // Mint form
  const [mintName, setMintName] = useState("");
  const [mintScope, setMintScope] = useState<"read" | "write" | "admin">("write");
  const [mintError, setMintError] = useState<string | null>(null);

  // One-time reveal — raw key in transient state only, never logged or stored
  const [minted, setMinted] = useState<MintedKey | null>(null);

  const loadKeys = () => {
    api.listKeys().then(setKeys).catch((e) => setListError(String(e)));
  };

  useEffect(() => {
    if (scope === "admin") { loadKeys(); }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope]);

  const handleUnlock = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await login(unlockKey);
      setUnlockKey("");
      setUnlockError(null);
    } catch (err) {
      setUnlockError(String(err));
    }
  };

  const handleMint = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const result = await api.createKey(mintName, mintScope);
      setMinted(result);
      setMintName("");
      setMintError(null);
      loadKeys();
    } catch (err) {
      setMintError(String(err));
    }
  };

  const handleRevoke = async (name: string) => {
    try {
      await api.revokeKey(name);
      loadKeys();
    } catch (err) {
      setListError(String(err));
    }
  };

  const inputStyle: React.CSSProperties = {
    marginTop: 2, padding: "5px 8px", border: "1px solid var(--frame-rule)",
    borderRadius: 4, fontSize: 13, background: "#fbf8ef", color: "var(--ink)",
    width: "100%",
  };

  const fieldStyle: React.CSSProperties = {
    display: "flex", flexDirection: "column", gap: 4, marginBottom: 12,
    fontSize: 13, color: "var(--ink-muted)",
  };

  // Locked: no session at all — show unlock card
  if (scope === null) {
    return (
      <section style={{ padding: "24px 32px", maxWidth: 480 }}>
        <Heading>Keys</Heading>
        <Panel>
          <p style={{ fontSize: 13, color: "var(--ink-muted)", margin: "0 0 16px" }}>
            Enter an admin key to manage API keys.
          </p>
          {unlockError && <p role="alert" style={{ color: "var(--oxblood)", fontSize: 13 }}>{unlockError}</p>}
          <form onSubmit={handleUnlock}>
            <div style={fieldStyle}>
              <label htmlFor="unlock-key">Admin key</label>
              <input id="unlock-key" type="password" style={inputStyle}
                value={unlockKey} onChange={(e) => setUnlockKey(e.target.value)}
                placeholder="mdsh_..." required />
            </div>
            <Button type="submit">Unlock</Button>
          </form>
        </Panel>
      </section>
    );
  }

  // Non-admin session (read or write scope) — cannot manage keys
  if (scope !== "admin") {
    return (
      <section style={{ padding: "24px 32px", maxWidth: 600 }}>
        <Heading>Keys</Heading>
        <Panel>
          <p style={{ fontSize: 13, color: "var(--ink-muted)", margin: "0 0 16px" }}>
            This key can read/write data but cannot manage keys. Unlock with an admin key.
          </p>
          <Button onClick={logout}>Switch key</Button>
        </Panel>
      </section>
    );
  }

  // Admin scope — full key management
  const activeKeys = keys.filter((k) => !k.revoked_at);

  return (
    <section style={{ padding: "24px 32px", maxWidth: 860 }}>
      <Heading>Keys</Heading>

      <p style={{ fontSize: 13, color: "var(--ink-muted)", margin: "8px 0 20px" }}>
        API keys grant bearer-token access to the madosho HTTP API. Revoked keys take effect immediately.
      </p>

      {/* One-time reveal callout — minted.key lives here and nowhere else */}
      {minted && (
        <div role="status" style={{
          background: "var(--parchment-panel)", border: "2px solid var(--gilt)",
          borderRadius: 6, padding: "16px 20px", marginBottom: 20,
        }}>
          <div style={{ fontWeight: 600, marginBottom: 8, fontFamily: "var(--font-ui)",
            fontSize: 13, color: "var(--ink)" }}>
            Key minted: <strong>{minted.name}</strong> ({minted.scope})
          </div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 13, marginBottom: 4,
            color: "var(--ink)" }}>
            {minted.key}
          </div>
          <div style={{ fontSize: 12, color: "var(--ink-muted)", marginBottom: 12 }}>
            Store this now - it will not be shown again.
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              onClick={() => { navigator.clipboard?.writeText(minted.key).catch(() => {}); }}
              style={{ fontSize: 12, padding: "4px 12px",
                border: "1px solid var(--frame-rule)", borderRadius: 4, cursor: "pointer",
                background: "transparent", color: "var(--ink)" }}>
              Copy
            </button>
            <button
              onClick={() => setMinted(null)}
              style={{ fontSize: 12, padding: "4px 12px",
                border: "1px solid var(--frame-rule)", borderRadius: 4, cursor: "pointer",
                background: "transparent", color: "var(--ink)" }}>
              Dismiss
            </button>
          </div>
        </div>
      )}

      {listError && <p role="alert" style={{ color: "var(--oxblood)", fontSize: 13 }}>{listError}</p>}

      <Panel style={{ marginBottom: 24 }}>
        <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: "0.06em",
          textTransform: "uppercase", color: "var(--ink-faint)",
          padding: "0 0 10px", borderBottom: "1px solid var(--frame-rule)", marginBottom: 12 }}>
          Active keys
        </div>
        {activeKeys.length === 0
          ? <EmptyState title="No active keys" hint="Mint one below." />
          : (
            <ul style={{ margin: 0, padding: 0, listStyle: "none",
              display: "flex", flexDirection: "column", gap: 8 }}>
              {activeKeys.map((k) => (
                <li key={k.name} style={{ display: "flex", alignItems: "center", gap: 8,
                  fontSize: 13, padding: "8px 10px",
                  background: "#fbf8ef", borderRadius: 4,
                  border: "1px solid var(--frame-rule)" }}>
                  <strong style={{ minWidth: 120 }}>{k.name}</strong>
                  <span style={{ fontFamily: "var(--font-mono)", color: "var(--ink-muted)" }}>
                    {k.prefix}...
                  </span>
                  <span style={{ color: "var(--ink-muted)" }}>{k.scope}</span>
                  <span style={{ flex: 1 }} />
                  <button
                    onClick={() => handleRevoke(k.name)}
                    style={{ fontSize: 12, padding: "2px 8px", cursor: "pointer",
                      border: "1px solid var(--frame-rule)", borderRadius: 4,
                      background: "transparent", color: "var(--oxblood)" }}>
                    Revoke
                  </button>
                </li>
              ))}
            </ul>
          )
        }
      </Panel>

      <Panel style={{ marginBottom: 24 }}>
        <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: "0.06em",
          textTransform: "uppercase", color: "var(--ink-faint)",
          paddingBottom: 10, borderBottom: "1px solid var(--frame-rule)", marginBottom: 16 }}>
          Mint new key
        </div>
        {mintError && <p role="alert" style={{ color: "var(--oxblood)", fontSize: 13 }}>{mintError}</p>}
        <form onSubmit={handleMint}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 16px" }}>
            <div style={fieldStyle}>
              <label htmlFor="mint-name">Key name</label>
              <input id="mint-name" style={inputStyle}
                value={mintName} onChange={(e) => setMintName(e.target.value)}
                placeholder="e.g. ci" required />
            </div>
            <div style={fieldStyle}>
              <label htmlFor="mint-scope">Scope</label>
              <select id="mint-scope" style={inputStyle}
                value={mintScope}
                onChange={(e) => setMintScope(e.target.value as "read" | "write" | "admin")}>
                <option value="read">read</option>
                <option value="write">write</option>
                <option value="admin">admin</option>
              </select>
            </div>
          </div>
          <Button type="submit">Create</Button>
        </form>
      </Panel>

      <div>
        <Button variant="ghost" onClick={logout}>Logout</Button>
      </div>
    </section>
  );
}
