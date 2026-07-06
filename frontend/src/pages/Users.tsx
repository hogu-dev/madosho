// frontend/src/pages/Users.tsx
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { UserRow } from "../api/types";
import { Heading, Panel, EmptyState, Button } from "../design/primitives";
import { useAuth } from "../auth/AuthContext";

export function Users() {
  const { scope } = useAuth();
  const [users, setUsers] = useState<UserRow[]>([]);
  const [listError, setListError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [newScope, setNewScope] = useState<"read" | "write" | "admin">("write");
  const [password, setPassword] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  const load = () => { api.listUsers().then(setUsers).catch((e) => setListError(String(e))); };
  useEffect(() => {
    if (scope === "admin") { load(); }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope]);

  const inputStyle: React.CSSProperties = {
    marginTop: 2, padding: "5px 8px", border: "1px solid var(--frame-rule)",
    borderRadius: 4, fontSize: 13, background: "#fbf8ef", color: "var(--ink)", width: "100%",
  };
  const fieldStyle: React.CSSProperties = {
    display: "flex", flexDirection: "column", gap: 4, marginBottom: 12,
    fontSize: 13, color: "var(--ink-muted)",
  };

  if (scope !== "admin") {
    return (
      <section style={{ padding: "24px 32px", maxWidth: 600 }}>
        <Heading>Users</Heading>
        <Panel><p style={{ fontSize: 13, color: "var(--ink-muted)" }}>
          Only an admin can manage user accounts.
        </p></Panel>
      </section>
    );
  }

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api.createUser(name, newScope, password);
      setName(""); setPassword(""); setFormError(null); load();
    } catch (err) { setFormError(String(err)); }
  };
  const deactivate = async (id: number) => {
    try { await api.deactivateUser(id); load(); } catch (err) { setListError(String(err)); }
  };
  const reset = async (id: number) => {
    const pw = window.prompt("New password for this user:");
    if (!pw) return;
    try { await api.resetUserPassword(id, pw); } catch (err) { setListError(String(err)); }
  };

  const active = users.filter((u) => u.is_active);

  return (
    <section style={{ padding: "24px 32px", maxWidth: 860 }}>
      <Heading>Users</Heading>
      <p style={{ fontSize: 13, color: "var(--ink-muted)", margin: "8px 0 20px" }}>
        User accounts log in with a username and password. Deactivation takes effect immediately.
      </p>
      {listError && <p role="alert" style={{ color: "var(--oxblood)", fontSize: 13 }}>{listError}</p>}

      <Panel style={{ marginBottom: 24 }}>
        <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase",
          color: "var(--ink-faint)", padding: "0 0 10px", borderBottom: "1px solid var(--frame-rule)", marginBottom: 12 }}>
          Active users
        </div>
        {active.length === 0
          ? <EmptyState title="No active users" hint="Create one below." />
          : (
            <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 8 }}>
              {active.map((u) => (
                <li key={u.id} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13,
                  padding: "8px 10px", background: "#fbf8ef", borderRadius: 4, border: "1px solid var(--frame-rule)" }}>
                  <strong style={{ minWidth: 140 }}>{u.username}</strong>
                  <span style={{ color: "var(--ink-muted)" }}>{u.scope}</span>
                  <span style={{ flex: 1 }} />
                  <button onClick={() => reset(u.id)} style={{ fontSize: 12, padding: "2px 8px", cursor: "pointer",
                    border: "1px solid var(--frame-rule)", borderRadius: 4, background: "transparent", color: "var(--ink)" }}>
                    Reset password
                  </button>
                  <button onClick={() => deactivate(u.id)} style={{ fontSize: 12, padding: "2px 8px", cursor: "pointer",
                    border: "1px solid var(--frame-rule)", borderRadius: 4, background: "transparent", color: "var(--oxblood)" }}>
                    Deactivate
                  </button>
                </li>
              ))}
            </ul>
          )}
      </Panel>

      <Panel style={{ marginBottom: 24 }}>
        <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase",
          color: "var(--ink-faint)", paddingBottom: 10, borderBottom: "1px solid var(--frame-rule)", marginBottom: 16 }}>
          Create user
        </div>
        {formError && <p role="alert" style={{ color: "var(--oxblood)", fontSize: 13 }}>{formError}</p>}
        <form onSubmit={create}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 16px" }}>
            <div style={fieldStyle}>
              <label htmlFor="u-name">Username</label>
              <input id="u-name" style={inputStyle} value={name}
                onChange={(e) => setName(e.target.value)} placeholder="e.g. alice" required />
            </div>
            <div style={fieldStyle}>
              <label htmlFor="u-scope">Scope</label>
              <select id="u-scope" style={inputStyle} value={newScope}
                onChange={(e) => setNewScope(e.target.value as "read" | "write" | "admin")}>
                <option value="read">read</option>
                <option value="write">write</option>
                <option value="admin">admin</option>
              </select>
            </div>
          </div>
          <div style={fieldStyle}>
            <label htmlFor="u-pw">Password</label>
            <input id="u-pw" type="password" style={inputStyle} value={password}
              onChange={(e) => setPassword(e.target.value)} placeholder="initial password" required />
          </div>
          <Button type="submit">Create</Button>
        </form>
      </Panel>
    </section>
  );
}
