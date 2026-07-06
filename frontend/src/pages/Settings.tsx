// frontend/src/pages/Settings.tsx
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { ApiFlavor, LlmEndpoint, LlmEndpointInput } from "../api/types";
import { Heading, Panel, EmptyState, Button } from "../design/primitives";
import { useAuth } from "../auth/AuthContext";
// Button is used for the submit action; row-level delete/default use plain <button> for compact sizing

const EMPTY: LlmEndpointInput = { name: "", provider: "openai", model: "", api_base: "",
  key_env_var: null, supports_text: true, supports_vision: false, api_flavor: "chat" };

export function Settings() {
  const { canWrite } = useAuth();
  const [rows, setRows] = useState<LlmEndpoint[]>([]);
  const [form, setForm] = useState<LlmEndpointInput>(EMPTY);
  const [error, setError] = useState<string | null>(null);

  const load = () => api.listLlmEndpoints().then(setRows).catch((e) => setError(String(e)));
  useEffect(() => { load(); }, []);

  const set = (k: keyof LlmEndpointInput) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [k]: e.target.value === "" && k === "key_env_var" ? null : e.target.value });

  const setBool = (k: "supports_text" | "supports_vision") =>
    (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.checked });

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try { await api.createLlmEndpoint(form); setForm(EMPTY); load(); }
    catch (err) { setError(String(err)); }
  };

  const fieldStyle: React.CSSProperties = {
    display: "flex", flexDirection: "column", gap: 4, marginBottom: 12,
    fontSize: 13, color: "var(--ink-muted)",
  };
  const inputStyle: React.CSSProperties = {
    marginTop: 2, padding: "7px 10px", border: "1px solid var(--frame-rule)",
    borderRadius: 8, fontSize: 13, background: "#fbf8ef", color: "var(--ink)",
    width: "100%",
  };
  const rowBtn: React.CSSProperties = {
    fontSize: 12, padding: "4px 10px", cursor: "pointer", border: "1px solid var(--frame-rule)",
    borderRadius: 6, background: "transparent", color: "var(--ink)", whiteSpace: "nowrap",
  };
  const chip: React.CSSProperties = {
    fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: "0.06em", textTransform: "uppercase",
    padding: "2px 7px", borderRadius: 4,
  };
  const accentChip: React.CSSProperties = {
    ...chip, background: "rgba(156,121,32,0.2)", color: "#6b521a", fontWeight: 600,
  };
  const capChip: React.CSSProperties = {
    ...chip, background: "rgba(31,23,9,0.06)", color: "var(--ink-muted)",
  };

  return (
    <section style={{ padding: "24px 32px", maxWidth: 860 }}>
      <Heading>Settings</Heading>

      <p style={{ fontSize: 13, color: "var(--ink-muted)", margin: "8px 0 20px" }}>
        Named LLM servers used by the contextual chunker, eval runner, and Scrying Answer.
        Keys are referenced by env-var name; the value lives in .env and never leaves the server.
      </p>

      {error && <p role="alert" style={{ color: "var(--oxblood)", fontSize: 13 }}>{error}</p>}

      <Panel style={{ marginBottom: 24 }}>
        <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase",
          color: "var(--ink-faint)", padding: "0 0 10px", borderBottom: "1px solid var(--frame-rule)",
          marginBottom: 12 }}>
          Registered endpoints
        </div>
        {rows.length > 0 && !rows.some((r) => r.supports_vision) && (
          <p style={{ color: "var(--oxblood)", fontSize: 12.5, margin: "0 0 12px" }}>
            No vision endpoint configured. Extraction comparisons will fail until one is set.
          </p>
        )}
        {rows.length === 0
          ? <EmptyState title="No endpoints" hint="Add one below to enable LLM features." />
          : (
            <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 10 }}>
              {rows.map((r) => (
                <li key={r.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start",
                  gap: 16, padding: "12px 14px", background: "#fbf8ef", borderRadius: 8,
                  border: "1px solid var(--frame-rule)" }}>
                  <div style={{ minWidth: 0, flex: 1, display: "flex", flexDirection: "column", gap: 6 }}>
                    <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
                      <strong style={{ fontSize: 14, color: "var(--ink)" }}>{r.name}</strong>
                      {r.is_default && <span style={accentChip}>default</span>}
                      {r.is_vision_default && <span style={accentChip}>vision default</span>}
                    </div>
                    <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--ink-muted)",
                      wordBreak: "break-all" }}>
                      {r.provider}:{r.model}
                      <span style={{ color: "var(--ink-faint)" }}>{"  ·  "}{r.api_base}</span>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                      {r.supports_text && <span style={capChip}>text</span>}
                      {r.supports_vision && <span style={capChip}>vision</span>}
                      {r.api_flavor === "responses" && <span style={capChip}>responses API</span>}
                      {r.key_env_var && (
                        <span style={{ ...capChip, color: r.key_present ? "var(--ink-faint)" : "var(--oxblood)" }}>
                          {r.key_env_var} · {r.key_present ? "present" : "MISSING"}
                        </span>
                      )}
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 8, flexShrink: 0, flexWrap: "wrap",
                    justifyContent: "flex-end", maxWidth: 240 }}>
                    {r.supports_vision && !r.is_vision_default && (
                      <button style={rowBtn} disabled={!canWrite}
                        onClick={() => api.setVisionDefaultLlmEndpoint(r.id).then(load).catch((e) => setError(String(e)))}>
                        Make vision default
                      </button>
                    )}
                    {!r.is_default && (
                      <button style={rowBtn} disabled={!canWrite}
                        onClick={() => api.setDefaultLlmEndpoint(r.id).then(load).catch((e) => setError(String(e)))}>
                        Make default
                      </button>
                    )}
                    <button style={rowBtn} disabled={!canWrite}
                      onClick={() => api.deleteLlmEndpoint(r.id).then(load).catch((e) => setError(String(e)))}>
                      Delete
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )
        }
      </Panel>

      <Panel>
        <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase",
          color: "var(--ink-faint)", paddingBottom: 10, borderBottom: "1px solid var(--frame-rule)",
          marginBottom: 16 }}>
          Add endpoint
        </div>
        <form onSubmit={submit}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 16px" }}>
            <div style={fieldStyle}>
              <label htmlFor="ep-name">Name</label>
              <input id="ep-name" style={inputStyle} value={form.name} onChange={set("name")}
                placeholder="e.g. gemma4-local" required />
            </div>
            <div style={fieldStyle}>
              <label htmlFor="ep-provider">Provider</label>
              <input id="ep-provider" style={inputStyle} value={form.provider} onChange={set("provider")}
                placeholder="openai" required />
            </div>
            <div style={fieldStyle}>
              <label htmlFor="ep-model">Model</label>
              <input id="ep-model" style={inputStyle} value={form.model} onChange={set("model")}
                placeholder="e.g. gemma-4-e4b" required />
            </div>
            <div style={fieldStyle}>
              <label htmlFor="ep-api-base">API base</label>
              <input id="ep-api-base" style={inputStyle} value={form.api_base} onChange={set("api_base")}
                placeholder="http://host:8081/v1" required />
            </div>
            <div style={fieldStyle}>
              <label htmlFor="ep-key-env-var">Key env var</label>
              <input id="ep-key-env-var" style={inputStyle} value={form.key_env_var ?? ""}
                onChange={set("key_env_var")} placeholder="MADOSHO_LLM_API_KEY (optional)" />
            </div>
            <div style={fieldStyle}>
              <label htmlFor="ep-api-flavor">API flavor</label>
              <select id="ep-api-flavor" style={inputStyle} value={form.api_flavor}
                onChange={(e) => setForm({ ...form, api_flavor: e.target.value as ApiFlavor })}>
                <option value="chat">chat completions (standard)</option>
                <option value="responses">responses API</option>
              </select>
            </div>
          </div>
          <div style={{ display: "flex", gap: 16, marginBottom: 12, fontSize: 13, color: "var(--ink-muted)" }}>
            <label>
              <input type="checkbox" checked={form.supports_text} onChange={setBool("supports_text")} /> text
            </label>
            <label>
              <input type="checkbox" checked={form.supports_vision} onChange={setBool("supports_vision")} /> vision
            </label>
          </div>
          <Button type="submit" disabled={!canWrite}>Add endpoint</Button>
        </form>
      </Panel>
    </section>
  );
}
