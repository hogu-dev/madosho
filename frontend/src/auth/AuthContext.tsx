import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, setUnauthorizedHandler } from "../api/client";

type Status = "loading" | "open" | "locked";
type State = { status: Status; scope: string | null; name: string | null; authRequired: boolean };
type Ctx = State & { canWrite: boolean; login: (key: string) => Promise<void>; loginPassword: (username: string, password: string) => Promise<void>; logout: () => Promise<void> };

const AuthCtx = createContext<Ctx | null>(null);
export function useAuth(): Ctx {
  const c = useContext(AuthCtx);
  if (!c) throw new Error("useAuth used outside <AuthProvider>");
  return c;
}

const OPEN: State = { status: "open", scope: null, name: null, authRequired: false };

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({ status: "loading", scope: null, name: null, authRequired: false });

  const refresh = useCallback(async () => {
    try {
      const me = await api.me();
      if (me.authenticated)
        setState({ status: "open", scope: me.scope, name: me.name, authRequired: me.auth_required });
      else if (me.auth_required)
        setState({ status: "locked", scope: null, name: null, authRequired: true });
      else setState(OPEN);
    } catch {
      setState(OPEN);   // /auth/me unreachable -> open; the server still enforces, the gate is UX
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {
    // any 401 from an API call (auth just turned on, or the cookie expired) -> re-lock
    setUnauthorizedHandler(() => setState((s) => (s.authRequired ? { ...s, status: "locked" } : s)));
    return () => setUnauthorizedHandler(null);
  }, []);

  const login = useCallback(async (key: string) => { await api.login(key); await refresh(); }, [refresh]);
  const loginPassword = useCallback(async (username: string, password: string) => { await api.loginPassword(username, password); await refresh(); }, [refresh]);
  const logout = useCallback(async () => { await api.logout(); await refresh(); }, [refresh]);

  const canWrite = !state.authRequired || state.scope === "write" || state.scope === "admin";
  return <AuthCtx.Provider value={{ ...state, canWrite, login, loginPassword, logout }}>{children}</AuthCtx.Provider>;
}
