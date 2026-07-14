import type { AlchemyGoal, AlchemyGoalInput, AlchemyRun, AlchemyRunLaunch, AlchemyRunSummary, Artifacts, AuthMe, Comparison, Components, Corpus, CorpusMember, CreatedPipeline, Cube, DocPipeline, Document, EndpointModel, EvalLaunch, EvalRun, ExtractDiff, ExtractDivergence, Job, Kb, KbDetail, KbPage, KbPageSummary, LibraryDocument, LlmEndpoint, LlmEndpointInput, PipelineConfig, PipelineCreate, Proposal, QueryResult, RatingsConfig, RecommendedPipeline, ResearchLaunch, ResearchRun, UserRow, VirtualModel } from "./types";

export type ApiKeyRow = {
  name: string; prefix: string; scope: "read" | "write" | "admin";
  created_at: string | null; last_used_at: string | null; revoked_at: string | null;
};
export type MintedKey = { name: string; prefix: string; scope: string; key: string };

// SPA and backend share one origin; the API lives under /api/* so backend paths
// never collide with the app's own client-side routes (/corpora/:id, /documents/:id).
const API = "/api";

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: (() => void) | null) { onUnauthorized = fn; }

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${url}`, { method: "GET", credentials: "include", ...init });
  if (res.status === 401) onUnauthorized?.();        // session expired / auth turned on -> re-lock
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch { /* non-JSON body */ }
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.status === 204 ? (undefined as T) : await res.json();
}

const json = (body: unknown): RequestInit => ({
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});

export const api = {
  listCorpora: () => req<Corpus[]>("/corpora"),
  createCorpus: (name: string) => req<Corpus>("/corpora", json({ name })),
  updateConfig: (id: number, config: PipelineConfig) =>
    req<Corpus>(`/corpora/${id}/config`, { ...json({ config }), method: "PUT" }),
  rebuild: (id: number) => req<{ rebuilding: number }>(`/corpora/${id}/rebuild`, { method: "POST" }),

  listDocuments: (corpusId: number) => req<Document[]>(`/corpora/${corpusId}/documents`),
  getDocument: (id: number) => req<Document>(`/documents/${id}`),
  deleteDocument: (id: number) => req<void>(`/documents/${id}`, { method: "DELETE" }),
  rebuildDocument: (id: number) => req<{ status: string }>(`/documents/${id}/rebuild`, { method: "POST" }),
  reconfigureDocument: (id: number,
    recipe: { parser?: string; chunker?: string; embedder?: string;
              options?: Record<string, Record<string, unknown>> }) =>
    req<{ status: string }>(`/documents/${id}/reconfigure`, json(recipe)),
  uploadDocument: (corpusId: number, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return req<Document>(`/corpora/${corpusId}/documents`, { method: "POST", body: fd });
  },
  listLibraryDocuments: () => req<LibraryDocument[]>("/documents"),
  // Import a whole llmkb KB as one document. Delivered EITHER as a zip
  // (archive) OR as the folder's files (each with its relative path, e.g. from a
  // directory picker); the server packs it. Optional corpus adds membership.
  importKb: (opts: { archive?: File; folder?: { file: File; path: string }[]; corpus?: string }) => {
    const fd = new FormData();
    if (opts.archive) fd.append("archive", opts.archive);
    for (const { file, path } of opts.folder ?? []) {
      fd.append("files", file);
      fd.append("paths", path);
    }
    if (opts.corpus) fd.append("corpus", opts.corpus);
    return req<Document>("/documents/import-kb", { method: "POST", body: fd });
  },
  listJobs: () => req<Job[]>("/jobs"),
  createDocument: (file: File,
    recipe?: { parser?: string; chunker?: string; embedder?: string; name?: string;
               options?: Record<string, Record<string, unknown>> }) => {
    const fd = new FormData();
    fd.append("file", file);
    if (recipe?.parser) fd.append("parser", recipe.parser);
    if (recipe?.chunker) fd.append("chunker", recipe.chunker);
    if (recipe?.embedder) fd.append("embedder", recipe.embedder);
    if (recipe?.name) fd.append("name", recipe.name);
    if (recipe?.options && Object.keys(recipe.options).length)
      fd.append("options", JSON.stringify(recipe.options));
    return req<Document>("/documents", { method: "POST", body: fd });
  },
  addMembership: (corpusId: number, documentId: number) =>
    req<Document>(`/corpora/${corpusId}/documents/${documentId}`, { method: "POST" }),
  removeMembership: (corpusId: number, documentId: number) =>
    req<void>(`/corpora/${corpusId}/documents/${documentId}`, { method: "DELETE" }),
  listCorpusMembers: (corpusId: number) =>
    req<CorpusMember[]>(`/corpora/${corpusId}/members`),
  setCorpusDocumentPipelines: (corpusId: number, documentId: number, pipelineIds: number[]) =>
    req<void>(`/corpora/${corpusId}/documents/${documentId}/pipelines`,
      { ...json({ pipeline_ids: pipelineIds }), method: "PUT" }),
  getArtifacts: (id: number) => req<Artifacts>(`/documents/${id}/artifacts`),
  // a specific pipeline's OWN chunks/tables, so a pipeline row drills into its
  // own output rather than the document's original ingest.
  getPipelineArtifacts: (pipelineId: number) => req<Artifacts>(`/pipelines/${pipelineId}/artifacts`),
  fileUrl: (id: number) => `${API}/documents/${id}/file`,
  getDocumentPipelines: (id: number) => req<DocPipeline[]>(`/documents/${id}/pipelines`),
  deletePipeline: (docId: number, pipelineId: number) =>
    req<void>(`/documents/${docId}/pipelines/${pipelineId}`, { method: "DELETE" }),
  setSelectedPipeline: (id: number, pipelineId: number | null) =>
    req<{ id: number; selected_pipeline_id: number | null }>(
      `/documents/${id}/selected-pipeline`, { ...json({ pipeline_id: pipelineId }), method: "PUT" }),
  createPipeline: (id: number, body: PipelineCreate) =>
    req<CreatedPipeline>(`/documents/${id}/pipelines`, json(body)),
  getRecommendedPipeline: (id: number) =>
    req<RecommendedPipeline | null>(`/documents/${id}/recommended-pipeline`),

  components: () => req<Components>("/components"),

  listVirtualModels: () => req<VirtualModel[]>("/virtual-models"),
  createVirtualModel: (b: Omit<VirtualModel, "id">) => req<VirtualModel>("/virtual-models", json(b)),
  deleteVirtualModel: (id: number) => req<void>(`/virtual-models/${id}`, { method: "DELETE" }),

  listLlmEndpoints: () => req<LlmEndpoint[]>("/llm-endpoints"),
  listEndpointModels: (id: number) => req<EndpointModel[]>(`/llm-endpoints/${id}/models`),
  createLlmEndpoint: (body: LlmEndpointInput) => req<LlmEndpoint>("/llm-endpoints", json(body)),
  updateLlmEndpoint: (id: number, body: LlmEndpointInput) =>
    req<LlmEndpoint>(`/llm-endpoints/${id}`, { ...json(body), method: "PUT" }),
  deleteLlmEndpoint: (id: number) => req<void>(`/llm-endpoints/${id}`, { method: "DELETE" }),
  setDefaultLlmEndpoint: (id: number) =>
    req<LlmEndpoint>(`/llm-endpoints/${id}/default`, { method: "PUT" }),
  setVisionDefaultLlmEndpoint: (id: number) =>
    req<LlmEndpoint>(`/llm-endpoints/${id}/vision-default`, { method: "PUT" }),

  query: (params: { corpus?: string; document_id?: number; prompt: string;
    llm?: string; pipelines?: string[] }) =>
    req<QueryResult>("/query", json(params)),

  getRatings: (corpusId: number) => req<Cube>(`/corpora/${corpusId}/ratings`),
  runRatings: (corpusId: number) =>
    req<{ running: number }>(`/corpora/${corpusId}/ratings/run`, { method: "POST" }),
  getRatingsConfig: (corpusId: number) => req<RatingsConfig>(`/corpora/${corpusId}/ratings/config`),
  setRatingsConfig: (corpusId: number, c: RatingsConfig) =>
    req<RatingsConfig>(`/corpora/${corpusId}/ratings/config`, { ...json(c), method: "PUT" }),
  // Legacy docling-vs-vision faithfulness head-to-head, dormant:
  // the compare page no longer renders it, but the endpoints stay until vision
  // becomes a real extract tool. postVerdict is still exercised by ratings tests.
  getComparison: (documentId: number) => req<Comparison>(`/documents/${documentId}/comparison`),
  postVerdict: (documentId: number, verdict: "a" | "b" | "tie") =>
    req<{ verdict: string }>(`/documents/${documentId}/comparison/verdict`, json({ verdict })),
  // Extract-stage diff between two of a document's pipelines, from stored artifacts.
  getPipelineExtractDiff: (documentId: number, left: number, right: number) =>
    req<ExtractDiff>(`/documents/${documentId}/pipeline-extract?left=${left}&right=${right}`),
  // N-way extract comparison across any number of a document's pipelines.
  getExtractDivergence: (documentId: number, ids: number[]) =>
    req<ExtractDivergence>(
      `/documents/${documentId}/extract-divergence?${ids.map((i) => `ids=${i}`).join("&")}`),

  launchResearch: (corpusId: number, body: ResearchLaunch) =>
    req<ResearchRun>(`/corpora/${corpusId}/research`, json(body)),
  listResearch: (corpusId: number) =>
    req<ResearchRun[]>(`/corpora/${corpusId}/research`),
  getResearch: (corpusId: number, runId: number) =>
    req<ResearchRun>(`/corpora/${corpusId}/research/${runId}`),

  launchEval: (corpusId: number, body: EvalLaunch) =>
    req<EvalRun>(`/corpora/${corpusId}/evals`, json(body)),
  listEvals: (corpusId: number) => req<EvalRun[]>(`/corpora/${corpusId}/evals`),
  getEval: (runId: number) => req<EvalRun>(`/evals/${runId}`),
  cancelEval: (runId: number) =>
    req<{ status: string }>(`/evals/${runId}/cancel`, { method: "POST" }),
  cancelResearch: (runId: number) =>
    req<{ status: string }>(`/research/${runId}/cancel`, { method: "POST" }),
  getProposal: (corpusId: number): Promise<Proposal | null> =>
    req<Proposal>(`/corpora/${corpusId}/proposal`).catch(() => null),
  dismissProposal: (proposalId: number) =>
    req<{ status: string }>(`/proposals/${proposalId}/dismiss`, { method: "POST" }),

  // Alchemy: goals are created from the CLI or the Alchemy page's New-goal form;
  // the UI also runs and views them.
  listAlchemyGoals: () => req<AlchemyGoal[]>("/alchemy/goals"),
  createAlchemyGoal: (body: AlchemyGoalInput) => req<AlchemyGoal>("/alchemy/goals", json(body)),
  getAlchemyGoal: (ref: number | string) => req<AlchemyGoal>(`/alchemy/goals/${ref}`),
  listAlchemyRuns: (ref: number | string) =>
    req<AlchemyRunSummary[]>(`/alchemy/goals/${ref}/runs`),
  getAlchemyRun: (ref: number | string, version: number) =>
    req<AlchemyRun>(`/alchemy/goals/${ref}/runs/${version}`),
  launchAlchemyRun: (ref: number | string, body: AlchemyRunLaunch) =>
    req<AlchemyRun>(`/alchemy/goals/${ref}/runs`, json(body)),
  // Cancel takes the run's DB id (AlchemyRunSummary.id), NOT the version number.
  cancelAlchemyRun: (runId: number) =>
    req<{ status: string }>(`/alchemy/runs/${runId}/cancel`, { method: "POST" }),
  finalizeAlchemyRun: (ref: number | string, version: number, ingest = false) =>
    req<AlchemyRun>(`/alchemy/goals/${ref}/finalize`, json({ version, ingest })),

  login: (key: string) => req<{ scope: string; name: string }>("/auth/login", json({ key })),
  loginPassword: (username: string, password: string) =>
    req<{ scope: string; name: string; kind: string }>("/auth/login", json({ username, password })),
  logout: () => req<{ ok: boolean }>("/auth/logout", { method: "POST" }),
  me: () => req<AuthMe>("/auth/me"),
  listUsers: () => req<UserRow[]>("/auth/users"),
  createUser: (username: string, scope: string, password: string) =>
    req<UserRow>("/auth/users", json({ username, scope, password })),
  deactivateUser: (id: number) =>
    req<void>(`/auth/users/${id}`, { method: "DELETE" }),
  resetUserPassword: (id: number, newPassword: string) =>
    req<void>(`/auth/users/${id}/password`, json({ new_password: newPassword })),
  changeMyPassword: (currentPassword: string, newPassword: string) =>
    req<void>("/auth/me/password", json({ current_password: currentPassword, new_password: newPassword })),

  listKeys: () => req<ApiKeyRow[]>("/auth/keys"),
  createKey: (name: string, scope: string) =>
    req<MintedKey>("/auth/keys", json({ name, scope })),
  revokeKey: (name: string) =>
    req<void>(`/auth/keys/${encodeURIComponent(name)}`, { method: "DELETE" }),

  listKbs: () => req<Kb[]>("/kbs"),
  createKb: (corpusId: number, name: string) =>
    req<Kb>(`/corpora/${corpusId}/kbs`, json({ name })),
  getKb: (id: number) => req<KbDetail>(`/kbs/${id}`),
  deleteKb: (id: number) => req<void>(`/kbs/${id}`, { method: "DELETE" }),
  getKbPage: (id: number, slug: string) => req<KbPage>(`/kbs/${id}/pages/${slug}`),
  addKbPage: (id: number, body: {
    type: string; title: string; description?: string;
    tags?: string[]; sources?: string[]; body?: string;
  }) => req<KbPage>(`/kbs/${id}/pages`, json(body)),
  editKbPage: (id: number, slug: string, body: {
    description?: string; tags?: string[]; sources?: string[]; body?: string;
  }) => req<KbPage>(`/kbs/${id}/pages/${slug}`, { ...json(body), method: "PUT" }),
  searchKb: (id: number, q: string) =>
    req<KbPageSummary[]>(`/kbs/${id}/search?q=${encodeURIComponent(q)}`),
  importKbWorkspace: (corpusId: number,
    opts: { archive?: File; folder?: { file: File; path: string }[]; name?: string }) => {
    const fd = new FormData();
    if (opts.archive) fd.append("archive", opts.archive);
    for (const { file, path } of opts.folder ?? []) {
      fd.append("files", file); fd.append("paths", path);
    }
    if (opts.name) fd.append("name", opts.name);
    return req<Kb>(`/corpora/${corpusId}/kbs/import`, { method: "POST", body: fd });
  },
};
