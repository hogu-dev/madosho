import { useEffect, useState, type FormEvent } from "react";
import { useAuth } from "./AuthContext";
import { Heading, Panel, Button } from "../design/primitives";

export function Login() {
  const { login, loginPassword } = useAuth();
  useEffect(() => {
    // The router is unmounted while locked, but the browser URL still points at
    // whatever protected route we were on (e.g. /users) when the session ended.
    // Reset it to root so a fresh sign-in lands on home (/documents) instead of
    // remounting that old page. Covers every sign-out path and session expiry.
    if (window.location.pathname !== "/") window.history.replaceState(null, "", "/");
  }, []);
  const [mode, setMode] = useState<"password" | "key">("password");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [key, setKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "password") await loginPassword(username, password);
      else await login(key);
    } catch {
      setError(mode === "password" ? "Invalid username or password." : "That key was not accepted.");
    } finally {
      setBusy(false);
    }
  };

  const inputStyle: React.CSSProperties = {
    width: "100%", padding: "8px 10px", marginBottom: 12, boxSizing: "border-box",
    border: "1px solid var(--frame-rule)", borderRadius: 6,
  };

  return (
    <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", background: "var(--leather)" }}>
      <Panel style={{ width: 360 }}>
        <Heading>madosho</Heading>
        <form onSubmit={submit}>
          {mode === "password" ? (
            <>
              <input aria-label="Username" autoFocus value={username}
                onChange={(e) => setUsername(e.target.value)} placeholder="username" style={inputStyle} />
              <input aria-label="Password" type="password" value={password}
                onChange={(e) => setPassword(e.target.value)} placeholder="password" style={inputStyle} />
            </>
          ) : (
            <input aria-label="API key" type="password" autoFocus value={key}
              onChange={(e) => setKey(e.target.value)} placeholder="mdsh_..."
              style={{ ...inputStyle, fontFamily: "var(--font-mono)" }} />
          )}
          {error && <p role="alert" style={{ color: "var(--oxblood)", fontSize: 13, margin: "0 0 10px" }}>{error}</p>}
          <Button type="submit" disabled={busy || (mode === "password" ? !username || !password : !key)}>
            {mode === "password" ? "Sign in" : "Unlock"}
          </Button>
        </form>
        <button type="button" onClick={() => { setError(null); setMode(mode === "password" ? "key" : "password"); }}
          style={{ marginTop: 12, background: "none", border: "none", cursor: "pointer",
            color: "var(--crumb-link)", fontSize: 12, padding: 0 }}>
          {mode === "password" ? "Use an API key instead" : "Use a username and password"}
        </button>
      </Panel>
    </div>
  );
}
