import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "../api/client";
import type { Corpus, QueryResult, Hit, Document, LlmEndpoint } from "../api/types";
import { Panel, Heading, Button, SegmentedToggle, RelevanceBar, CodeBlock } from "../design/primitives";

const mono = (size = 11, color = "var(--ink-faint)") =>
  ({ fontFamily: "var(--font-mono)" as const, fontSize: size, color });

// Backend appends a "\n\nSources:\n[1] …" footer to `answer`; strip it so the
// Sources chip row (rendered from `citations`) isn't shown twice.
export function splitSources(answer: string): string {
  return answer.split(/\n+Sources:\n/)[0].trimEnd();
}

// Provider-reported prompt tokens, when present. There is NO local tokenizer,
// so this is the only honest token count — return null when the provider didn't supply it.
export function promptTokens(usage: unknown): number | null {
  if (usage && typeof usage === "object" && "prompt_tokens" in usage) {
    const n = (usage as { prompt_tokens: unknown }).prompt_tokens;
    if (typeof n === "number") return n;
  }
  return null;
}

export function Scrying() {
  const [corpora, setCorpora] = useState<Corpus[]>([]);
  const [corpus, setCorpus] = useState("");
  const [mode, setMode] = useState<"answer" | "retrieval">("answer");
  const [endpoints, setEndpoints] = useState<LlmEndpoint[]>([]);
  const [model, setModel] = useState("");          // an endpoint name
  const [prompt, setPrompt] = useState("");
  const [result, setResult] = useState<QueryResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [params] = useSearchParams();
  const rawDoc = params.get("document");
  const docId = rawDoc && Number.isFinite(Number(rawDoc)) ? Number(rawDoc) : null;
  const [doc, setDoc] = useState<Document | null>(null);
  useEffect(() => {
    if (docId == null) { setDoc(null); return; }
    api.getDocument(docId).then(setDoc).catch(() => setDoc(null));
  }, [docId]);

  useEffect(() => {
    api.listCorpora().then((cs) => { setCorpora(cs); setCorpus((c) => c || cs[0]?.name || ""); })
      .catch(() => setCorpora([]));
    api.listLlmEndpoints().then((eps) => {
      setEndpoints(eps);
      setModel((m) => m || ((eps.find((e) => e.is_default) ?? eps[0])?.name ?? ""));
    }).catch(() => setEndpoints([]));
  }, []);

  // Clear a prior Cast's result when the scope/mode/model controls change, so the
  // displayed answer can never describe a different scope than the controls now show.
  useEffect(() => { setResult(null); }, [corpus, mode, docId, model]);

  const llm = model;
  const canCast = prompt.trim().length > 0 && (docId != null || corpus !== "")
    && (mode === "retrieval" || (llm.length > 0 && endpoints.length > 0)) && !busy;

  const cast = async () => {
    setBusy(true); setError(null);
    try {
      const params: Parameters<typeof api.query>[0] = { prompt: prompt.trim() };
      if (docId != null) params.document_id = docId; else params.corpus = corpus;
      if (mode === "answer") params.llm = llm;
      setResult(await api.query(params));
    } catch (e) { setError(e instanceof Error ? e.message : "Cast failed"); setResult(null); }
    finally { setBusy(false); }
  };

  const chunks: Hit[] = result?.hits ?? result?.citations ?? [];

  return (
    <Panel style={{ padding: "28px 32px", maxWidth: 880 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <Heading level={1} style={{ margin: 0 }}>Scrying</Heading>
        <span style={{ ...mono(11, "var(--gilt)"), letterSpacing: "0.08em", textTransform: "uppercase",
          border: "1px solid var(--frame-rule)", borderRadius: 20, padding: "3px 10px" }}>query console</span>
      </div>
      <p style={{ fontSize: 13.5, color: "var(--ink-muted)", margin: "9px 0 22px", maxWidth: 600,
        lineHeight: 1.55 }}>
        Pose a question to a corpus and draw out a cited answer — or take just the passages it surfaces
        and let your own agent finish the spell.</p>

      {/* COMPOSER */}
      <div style={{ background: "var(--card)", border: "1px solid var(--frame-rule)", borderRadius: 12,
        padding: 18 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap", marginBottom: 14 }}>
          {docId != null ? (
            <span style={{ display: "flex", alignItems: "center", gap: 7 }}>
              <span style={{ ...mono(10, "var(--ink-muted)"), letterSpacing: "0.08em",
                textTransform: "uppercase" }}>Document</span>
              <span style={{ fontSize: 13, fontWeight: 500 }}>{doc?.filename ?? "…"}</span>
            </span>
          ) : (
            <label style={{ display: "flex", alignItems: "center", gap: 7 }}>
              <span style={{ ...mono(10, "var(--ink-muted)"), letterSpacing: "0.08em",
                textTransform: "uppercase" }}>Corpus</span>
              <select aria-label="Corpus" value={corpus} onChange={(e) => setCorpus(e.target.value)}
                style={{ fontSize: 13, fontFamily: "var(--font-ui)", padding: "6px 10px",
                  border: "1px solid var(--frame-rule)", borderRadius: 7,
                  background: "var(--parchment-panel)" }}>
                {corpora.map((c) => <option key={c.id} value={c.name}>{c.name}</option>)}
              </select>
            </label>
          )}

          <SegmentedToggle value={mode} onChange={(v) => setMode(v as "answer" | "retrieval")}
            options={[{ value: "answer", label: "Answer" }, { value: "retrieval", label: "Retrieval only" }]} />

          {mode === "answer" && (
            endpoints.length === 0 ? (
              <span style={{ fontSize: 12.5, color: "var(--oxblood)" }}>
                needs an LLM endpoint — add one in Settings
              </span>
            ) : (
              <label style={{ display: "flex", alignItems: "center", gap: 7 }}>
                <span style={{ ...mono(10, "var(--ink-muted)"), letterSpacing: "0.08em",
                  textTransform: "uppercase" }}>Model</span>
                <select aria-label="Model" value={model} onChange={(e) => setModel(e.target.value)}
                  style={{ fontSize: 13, fontFamily: "var(--font-ui)", padding: "6px 10px",
                    border: "1px solid var(--frame-rule)", borderRadius: 7, background: "var(--parchment-panel)" }}>
                  {endpoints.map((e) => <option key={e.id} value={e.name}>{e.name}</option>)}
                </select>
              </label>
            )
          )}
        </div>

        <textarea aria-label="Question" placeholder="Ask the corpus a question…" value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          style={{ width: "100%", minHeight: 84, resize: "vertical", background: "var(--parchment-panel)",
            border: "1px solid var(--frame-rule)", borderRadius: 9, padding: "13px 14px",
            fontFamily: "var(--font-ui)", fontSize: 14, color: "var(--ink)", lineHeight: 1.5,
            boxSizing: "border-box" }} />

        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 13 }}>
          <span style={mono(11.5, "var(--ink-muted)")}>retrieve k=8 · effective pipelines</span>
          <Button onClick={cast} disabled={!canCast}>{busy ? "Casting…" : "Cast ✦"}</Button>
        </div>
      </div>

      {error && <p style={{ color: "var(--oxblood)", fontSize: 13, marginTop: 16 }}>{error}</p>}

      {result?.answer != null && <AnswerBlock result={result} />}

      {chunks.length > 0 && <SourceChunks chunks={chunks} />}
    </Panel>
  );
}

// Render the model's answer as markdown, styled to the serif answer aesthetic.
// The backend returns markdown (headings, bold, lists); showing it raw looked
// like unrendered syntax.
const serif = { fontFamily: "var(--font-serif)", color: "var(--ink)" } as const;
const mdComponents = {
  p: (p: any) => <p style={{ ...serif, fontSize: 18, lineHeight: 1.6, margin: "0 0 12px" }} {...p} />,
  h1: (p: any) => <h2 style={{ ...serif, fontSize: 21, fontWeight: 700, margin: "18px 0 10px" }} {...p} />,
  h2: (p: any) => <h3 style={{ ...serif, fontSize: 19, fontWeight: 700, margin: "16px 0 9px" }} {...p} />,
  h3: (p: any) => <h4 style={{ ...serif, fontSize: 17, fontWeight: 700, margin: "14px 0 8px" }} {...p} />,
  ul: (p: any) => <ul style={{ ...serif, fontSize: 18, lineHeight: 1.6, margin: "0 0 12px", paddingLeft: 24 }} {...p} />,
  ol: (p: any) => <ol style={{ ...serif, fontSize: 18, lineHeight: 1.6, margin: "0 0 12px", paddingLeft: 24 }} {...p} />,
  li: (p: any) => <li style={{ marginBottom: 5 }} {...p} />,
  strong: (p: any) => <strong style={{ fontWeight: 700 }} {...p} />,
  em: (p: any) => <em style={{ fontStyle: "italic" }} {...p} />,
  a: (p: any) => <a style={{ color: "var(--gilt)" }} {...p} />,
  code: (p: any) => <code style={{ fontFamily: "var(--font-mono)", fontSize: 14,
    background: "rgba(120,95,40,0.10)", borderRadius: 4, padding: "1px 5px" }} {...p} />,
} as const;

function AnswerBlock({ result }: { result: QueryResult }) {
  const [open, setOpen] = useState(false);
  const cites = result.citations ?? [];
  const tokens = promptTokens(result.usage);
  return (
    <div style={{ marginTop: 24 }}>
      <div style={{ ...mono(10, "var(--ink-muted)"), letterSpacing: "0.12em", textTransform: "uppercase",
        marginBottom: 10 }}>Answer</div>
      <div style={{ background: "var(--card)", border: "1px solid var(--frame-rule)", borderRadius: 12,
        padding: 22 }}>
        <div style={{ fontFamily: "var(--font-serif)", color: "var(--ink)" }}>
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
            {splitSources(result.answer ?? "")}
          </ReactMarkdown>
        </div>
        {cites.length > 0 && (
          <div style={{ marginTop: 18, paddingTop: 15, borderTop: "1px solid rgba(120,95,40,0.16)",
            display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <span style={{ ...mono(10, "var(--ink-muted)"), letterSpacing: "0.1em",
              textTransform: "uppercase" }}>Sources</span>
            {cites.map((c, i) => (
              <Link key={i} to={c.document_id != null ? `/documents/${c.document_id}` : "#"}
                style={{ ...mono(11.5, "var(--ink-muted)"), textDecoration: "none",
                  border: "1px solid var(--frame-rule)", borderRadius: 6, padding: "4px 9px" }}>
                <span style={{ color: "var(--gilt)" }}>[{i + 1}]</span>{" "}
                {[c.source, c.page != null ? `p.${c.page}` : null].filter(Boolean).join(" · ")}</Link>
            ))}
          </div>
        )}
      </div>

      {result.messages && result.messages.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div onClick={() => setOpen((v) => !v)} style={{ background: "var(--card)",
            border: "1px solid var(--frame-rule)", borderRadius: 12, padding: "15px 18px",
            display: "flex", alignItems: "center", justifyContent: "space-between", cursor: "pointer" }}>
            <span style={mono(12.5, "var(--ink)")}>
              <span style={{ color: "var(--gilt)" }}>{open ? "▾" : "▸"}</span> Assembled prompt
              <span style={{ color: "var(--ink-muted)" }}> — exact messages sent to the model</span></span>
            {tokens != null && <span style={mono(11, "var(--ink-muted)")}>
              {tokens.toLocaleString("en-US")} tokens</span>}
          </div>
          {open && (
            <div style={{ marginTop: 8 }}>
              <CodeBlock>{result.messages.map((m) => `${m.role}: ${m.content}`).join("\n\n")}</CodeBlock>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function SourceChunks({ chunks }: { chunks: Hit[] }) {
  const top = useMemo(() => Math.max(0, ...chunks.map((c) => c.score)), [chunks]);
  return (
    <div style={{ marginTop: 24 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
        <div style={{ ...mono(10, "var(--ink-muted)"), letterSpacing: "0.12em", textTransform: "uppercase" }}>
          Source chunks · {chunks.length} retrieved</div>
        <div style={mono(11, "var(--ink-muted)")}>score = relative retrieval relevance</div>
      </div>
      {chunks.map((c, i) => (
        <div key={c.pipeline_id != null ? `${c.pipeline_id}:${c.position}:${i}` : i}
          style={{ background: "var(--card)", border: "1px solid var(--frame-rule)", borderRadius: 10,
            padding: "15px 16px", marginBottom: 10 }}>
          <div style={{ display: "flex", alignItems: "flex-start", gap: 14 }}>
            <RelevanceBar value={c.score} max={top} />
            <div style={{ flex: 1 }}>
              <p style={{ fontSize: 13.5, lineHeight: 1.55, margin: 0, color: "var(--ink)" }}>{c.text}</p>
              {c.document_id != null
                ? <Link to={`/documents/${c.document_id}`} style={{ ...mono(11, "var(--gilt)"),
                    textDecoration: "none", marginTop: 9, display: "inline-block" }}>
                    {[c.source, c.pipeline, c.page != null ? `p.${c.page}` : null].filter(Boolean).join(" · ")}</Link>
                : <span style={{ ...mono(11, "var(--ink-faint)"), marginTop: 9, display: "inline-block" }}>
                    {c.citation}</span>}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

export default Scrying;
