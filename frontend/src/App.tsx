import { RouterProvider } from "react-router-dom";
import { router } from "./router";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { Login } from "./auth/Login";

function Gate() {
  const { status } = useAuth();
  if (status === "loading") return <div style={{ minHeight: "100vh", background: "var(--leather)" }} />;
  if (status === "locked") return <Login />;
  return <RouterProvider router={router} />;
}

export default function App() {
  return <AuthProvider><Gate /></AuthProvider>;
}
