import { useAuth } from "./AuthContext";

export function ReadOnlyBanner() {
  const { authRequired, canWrite } = useAuth();
  if (!authRequired || canWrite) return null;
  return (
    <div role="status" style={{ background: "var(--oxblood)", color: "#f6e9cf",
      fontFamily: "var(--font-ui)", fontSize: 12.5, padding: "5px 24px", textAlign: "center" }}>
      Read-only session - this key cannot modify data. Sign in with a write key to make changes.
    </div>
  );
}
