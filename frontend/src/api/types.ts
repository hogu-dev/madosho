export interface Corpus { id: number; name: string; config: PipelineConfig; }
export interface PipelineConfig {
  corpus: string;
  ingest?: { parser?: string; chunker?: string; embedder?: string;
             store?: unknown; indexes?: string[] };
  query?: unknown[];
}
export interface IngestLogLine { t: number; msg: string; }
export interface IngestProgress {
  phase?: string;
  started_at?: string;
  page_count?: number | null;
  log?: IngestLogLine[];
}
export interface Document {
  id: number; corpus_id: number; filename: string;
  status: "received" | "indexing" | "indexed" | "failed"; error: string | null;
  progress?: IngestProgress;
  selected_pipeline_id?: number | null;   // G: saved effective-pipeline override
  corpora?: CorpusChip[];   // GET /documents/:id (DocumentDetailRead) — the "In corpora" row
}

// One row of the doc page's pipelines list (GET /documents/{id}/pipelines).
export interface DocPipeline {
  id: number;
  name: string;
  slots: Record<string, string | null>;   // {extract, chunk, index} -> tool name
  steps: Record<string, number>;           // {extract, chunk, index} -> per-step rating
  rating: number;                          // summed (advice, not a verdict)
  status: "building" | "indexed" | "failed";
  is_default: boolean;
  effective: boolean;
  created_at?: string;                     // ISO build time; shown on the card, newest sorts first
  progress?: IngestProgress;               // live build feed (phase + rolling log), polled while building
}
// One row of the global Jobs feed (GET /jobs): a pipeline build anywhere in the
// library. Every build is a pipeline, so a document's initial indexing is its
// default pipeline's build (kind="ingest") and the rest are kind="build".
export interface Job {
  kind: "ingest" | "build";
  pipeline_id: number;
  document_id: number;
  document_filename: string;
  name: string;
  status: "building" | "indexed" | "failed";
  error?: string | null;
  progress?: IngestProgress;               // live build feed, polled while building
  created_at?: string | null;              // ISO; build start
}
export interface PipelineCreate {
  name: string; parser?: string; chunker?: string; embedder?: string;
  options?: Record<string, Record<string, unknown>>;   // {slot_kind: {opt: val}}
}
export interface CreatedPipeline {
  id: number; name: string; document_id: number;
  status: string; collection: string; slots: Record<string, string | null>;
}
// The advisory "recommended test" on the compare view (GET .../recommended-pipeline):
// the best tool per slot, assembled into a combo worth building. Advice, not a verdict.
export interface RecommendedPipeline {
  slots: Record<string, string>;        // {extract, chunk, index} -> tool name
  steps: Record<string, number>;        // {extract, chunk, index} -> that tool's rating
  projected_rating: number;             // summed (a suggestion to test, never a guarantee)
  already_built: boolean;               // the winning combo equals an existing pipeline
  matches: string | null;               // that pipeline's name when already_built
}
export interface Chunk { id: string; text: string; position: number; page: number | null; }
export interface Table { content: string; page: number | null; bbox: number[] | null; }
export interface Artifacts { document_id: number; chunks: Chunk[]; tables: Table[]; }
export interface Hit {
  text: string; score: number; page: number | null; citation: string;
  source: string | null; document_id?: number | null; position?: number;
  pipeline?: string; pipeline_id?: number;   // backend returns these; UI links chunks to their pipeline
}
export interface ChatMessage { role: string; content: string; }
export interface QueryResult {
  hits?: Hit[]; answer?: string; citations?: Hit[]; usage?: unknown;
  messages?: ChatMessage[];   // assembled prompt: exact text sent to the model
}
export interface VirtualModel {
  id: number; name: string; corpus_id: number; provider: string; model: string; template: string | null;
}
export interface ComponentInfo {
  name: string;
  license: string | null;
  org: string | null;
  // Hard slot dependencies: {other_slot: [allowed names]}. The chosen component
  // in `other_slot` must be one of those names, else this component can't run.
  // Absent/empty = unconstrained.
  requires?: Record<string, string[]>;
  options_schema?: Record<string, unknown> | null;   // pydantic Options JSON schema
}
export type Components = Record<string, ComponentInfo[]>;

export type Source = "static" | "measured" | "human" | "f-empirical" | "rollup";
export interface CubeCell { score: number; source: Source; rationale: string | null; suggestion: string | null; }
export interface PipelineRow {
  name: string;
  pipeline_id: number;
  effective: boolean;
  cells: Record<string, CubeCell>;   // extraction / chunk / embed
  build_total: number;
}
export interface DocGroup {
  document_id: number;
  retrieval: Record<string, CubeCell>;   // keyword / semantic / rerank
  retrieval_total: number;
  pipelines: PipelineRow[];
}
export interface Cube { documents: DocGroup[]; weights: Record<string, number>; }
export interface Comparison {
  document_id: number;
  engine_a: string; text_a: string; engine_b: string; text_b: string;
  verdict: "a" | "b" | "tie" | null;
  judge_verdict: "a" | "b" | "tie" | null; human_verdict: "a" | "b" | "tie" | null;
  judge_rationale: string | null; judge_score: number | null;
  diff: { a: [number, number][]; b: [number, number][] };
  pages?: ComparisonPage[];
}
export interface ComparisonPage {
  page: number; text_a: string; text_b: string;
  diff: { a: [number, number][]; b: [number, number][] };
  change: number;   // total highlighted chars on this page; 0 = no content difference
}
// Extract-stage diff between two of a document's pipelines, read from each
// pipeline's stored artifacts (GET /documents/{id}/pipeline-extract). Same page
// shape as the legacy head-to-head, but engine_a/b are the two pipeline names.
export interface ExtractDiff {
  document_id: number; left_id: number; right_id: number;
  engine_a: string; engine_b: string;
  text_a: string; text_b: string;
  diff: { a: [number, number][]; b: [number, number][] };
  pages: ComparisonPage[];
}
// N-way extract comparison across any number of a document's pipelines
// (GET /documents/{id}/extract-divergence). One column per pipeline; `spans` are
// the char ranges where a column disagrees with >=1 other -- a single "they don't
// all agree here" highlight, no baseline. Column order matches `pipelines`.
export interface ExtractColumn {
  pipeline_id: number; name: string; text: string;
  spans: [number, number][];
}
export interface ExtractDivergencePage {
  page: number; columns: ExtractColumn[]; change: number;
}
export interface ExtractDivergence {
  document_id: number;
  pipelines: { id: number; name: string }[];
  pages: ExtractDivergencePage[];
}
export interface RatingsConfig { trigger: "on-demand" | "on-ingest"; }

export interface EvalRun {
  id: number;
  corpus_id: number;
  status: "pending" | "running" | "done" | "failed" | "cancelled";
  progress: { phase?: string; done?: number; total?: number };
  sampling?: { n_docs?: number; questions_per_doc?: number; llm?: { provider: string; model: string } };
  token_budget?: number | null;
  tokens_spent?: number;
  cost_estimate?: number | null;
  cost_actual?: number | null;
  created_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
  results?: EvalResults | null;
}

export interface EvalResults {
  baseline?: Record<string, number>;
  greedy?: { baseline_score: number; final_score: number; path: GreedyStep[] };
  cells?: { baseline: number; bottleneck: string | null;
            stages: Record<string, { score: number; lift: number; best_label: string; suggestion: string | null }> };
}

export interface GreedyStep {
  stage: string;
  label: string;
  score: number;
  lift: number;
}

export interface EvalLaunch {
  sampling: { n_docs?: number; questions_per_doc?: number;
              llm?: { provider: string; model: string } };
  token_budget?: number | null;
}

export interface Proposal {
  id: number;
  corpus_id: number;
  eval_run_id: number;
  proposed_config: Record<string, unknown>;
  evidence: { baseline: number; projected: number;
              lifts: { stage: string; label: string; lift: number }[];
              cost?: { tokens: number; dollars: number | null } };
  status: "proposed" | "applying" | "applied" | "dismissed";
}

export interface ResearchCitation {
  document_id: number | null;
  pipeline_id: number | null;
  pipeline: string | null;
  position: number | null;
  citation: string;
  source: string | null;
  score: number | null;
  quote: string;
}

export interface ResearchConfig {
  source: "rag" | "whole-text";
  document_ids: number[];
  budget_chars: number;
  max_rounds: number;
  llm: { provider?: string; model?: string };
}

export interface ResearchRun {
  id: number;
  corpus_id: number;
  status: "pending" | "running" | "done" | "failed" | "cancelled";
  progress: { phase?: string };
  prompt: string;
  config: ResearchConfig;
  stop_reason?: string | null;
  error?: string | null;
  created_at?: string | null;
  finished_at?: string | null;
  report_markdown?: string | null;
  citations?: ResearchCitation[];
  run_log?: Record<string, unknown>[];
}

export interface ResearchLaunch {
  prompt: string;
  source: "rag" | "whole-text";
  document_ids: number[];
  budget_chars: number;
  max_rounds: number;
  llm: { provider: string; model: string };
  reasoning_effort?: string;   // omitted -> the endpoint's own default
}

export interface CorpusChip { id: number; name: string; }

// A document in a corpus, with its pipelines and which ones this corpus queries it
// through (GET /corpora/{id}/members). selected_pipeline_ids empty = use the document's
// default; a query fans the doc out across every selected pipeline and RRF-merges them.
// default_pipeline_id is what an empty selection resolves to (highest-rated).
export interface CorpusMemberPipeline {
  id: number; name: string; status: "building" | "indexed" | "failed";
  rating?: number | null; is_default: boolean;
}
export interface CorpusMember {
  document_id: number;
  filename: string;
  status: "received" | "indexing" | "indexed" | "failed";
  selected_pipeline_ids: number[];
  default_pipeline_id?: number | null;
  pipelines: CorpusMemberPipeline[];
}
// A row in the global Documents library (GET /documents). pp/size/pipe-count/
// updated are NOT in this payload — the library table dashes those columns.
export interface LibraryDocument {
  id: number;
  filename: string;
  status: "received" | "indexing" | "indexed" | "failed";
  selected_pipeline_id: number | null;
  corpora: CorpusChip[];
  rating: number | null;   // effective pipeline's summed /15 rating; null until indexed
  error?: string | null;                   // failure reason when status === "failed"
  progress?: IngestProgress;               // live build feed while indexing
}

// Which OpenAI-style surface the server speaks: Chat Completions (default) or
// the newer Responses API (some frontier proxies only take images this way).
export type ApiFlavor = "chat" | "responses";

export interface LlmEndpoint {
  id: number; name: string; provider: string; model: string;
  api_base: string; key_env_var: string | null; is_default: boolean; key_present: boolean;
  supports_text: boolean; supports_vision: boolean; is_vision_default: boolean;
  api_flavor: ApiFlavor;
  context_window_tokens: number | null; source_chars_budget: number | null;
  reasoning_effort: string | null;
}
// A model an endpoint's upstream serves, with the reasoning-effort levels it
// accepts (empty = no effort control beyond the endpoint default). Drives the
// launch forms' model dropdown + the adjacent, per-model Reasoning dropdown.
export interface EndpointModel {
  id: string;
  reasoning_efforts: string[];
  default_effort: string | null;
}

export interface LlmEndpointInput {
  name: string; provider: string; model: string;
  api_base: string; key_env_var: string | null;
  supports_text: boolean; supports_vision: boolean;
  api_flavor: ApiFlavor;
  context_window_tokens: number | null; source_chars_budget: number | null;
  reasoning_effort: string | null;
}

export type AuthMe = {
  authenticated: boolean;
  auth_required: boolean;
  scope: "read" | "write" | "admin" | null;
  name: string | null;
  kind: "key" | "user" | null;
};

export type UserRow = {
  id: number;
  username: string;
  scope: "read" | "write" | "admin";
  is_active: boolean;
  created_at: string | null;
  last_login_at: string | null;
};

// ---- Alchemy: named/versioned autonomous goals over a corpus ----------------
// Goals are created via the CLI (madosho alchemy create); the web UI is a
// viewer with light actions (run / cancel / finalize).

export interface AlchemyGoal {
  id: number;
  name: string;
  corpus_id: number;
  goal_type: string;                       // e.g. living-research | report
  spec: Record<string, unknown>;
  coverage: "search" | "full" | "exhaustive";
  include_generated: boolean;
  created_at: string | null;
}
// POST /alchemy/goals body. spec shape is goal-type specific: living-research
// carries { goal }, report carries { template } (markdown headings) and an
// optional { goal } preamble. The server compiles+validates it (400 on a bad spec).
export interface AlchemyGoalInput {
  name: string;
  corpus_id: number;
  goal_type: string;
  spec: Record<string, unknown>;
  coverage: "search" | "full" | "exhaustive";
  include_generated?: boolean;
}

export interface AlchemyUsage {
  llm_calls?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
}

export type AlchemyRunStatus = "pending" | "running" | "done" | "failed" | "cancelled";

// One row of a goal's runs table (GET /alchemy/goals/{ref}/runs, version desc).
export interface AlchemyRunSummary {
  id: number;                              // DB run id -- cancel takes THIS, not the version
  goal_id: number;
  version: number;
  status: AlchemyRunStatus;
  coverage: string;
  guidance: string | null;
  based_on_version: number | null;
  stop_reason: string | null;              // final|round_cap|no_tools_used|cancelled|failed|call_cap
  usage: AlchemyUsage | null;
  is_final: boolean;
  ingested_document_id: number | null;     // set once a draft is ingested back
  error: string | null;
  created_at: string | null;
  finished_at: string | null;
}

export interface AlchemySectionConfidence {
  level: "low" | "medium" | "high";
  self_grade?: number | null;
  distinct_docs?: number;
  citations?: number;
  coverage_complete?: boolean;
}

export interface AlchemySection {
  key: string;
  title: string;
  content: string;
  filled: boolean;
  note?: string | null;                    // why a section stayed unfilled
  confidence?: AlchemySectionConfidence | null;
  stop_reason?: string | null;
  llm_calls?: number;
}

// Coverage ledger: which corpus docs the run consulted and how.
export interface AlchemyLedger {
  mode: string;
  total_docs: number | null;   // null when the corpus doc list could not be resolved

  consulted: Record<string, "search" | "forced" | "read">;
  from_prior: number[];
  unconsulted: number[];
  failures: Record<string, string>;
  complete: boolean | null;   // null in search mode: coverage-complete is not a promise it makes
  shortfall?: string | null;               // honest-shortfall note when coverage fell short
  summary?: string | null;
}

export interface AlchemyCitation {
  document_id: number | null;
  pipeline_id: number | null;
  pipeline: string | null;
  position: number | null;
  citation: string;
  source: string | null;
  score: number | null;
  quote: string;
}

// Full run payload (single-run GET / launch / finalize responses).
// One row of the research loop's activity trace. A `tool_call` is an agent/tool
// the model invoked (search, get-doc, ...) with its args + result; an `llm` row
// marks a model turn (whether it called tools, and how much text it produced -
// the verbatim prose is not stored, only the final draft is). Alchemy tags each
// entry with the report `section` it belongs to.
export interface AlchemyLogEntry {
  round?: number;
  section?: string;
  kind?: "llm" | "tool_call";
  name?: string;                      // tool_call: the agent/tool name
  args?: Record<string, unknown>;     // tool_call: its arguments (e.g. the query)
  ok?: boolean;
  error?: string | null;
  chars?: number;                     // tool_call: result size fed to the model
  note?: string | null;               // e.g. "truncated to fit context budget"
  has_tool_calls?: boolean;           // llm turn: did it call tools this round
  text_chars?: number;                // llm turn: chars of prose it produced
  text?: string;                      // llm turn: bounded preview of that prose
}
export interface AlchemyRun extends AlchemyRunSummary {
  draft_markdown: string | null;
  citations: AlchemyCitation[] | null;
  run_log: AlchemyLogEntry[] | null;
  sections: AlchemySection[] | null;
  ledger: AlchemyLedger | null;
  artifact_counts: Record<string, number> | null;
  progress: { phase?: string } | null;
}

export interface AlchemyRunLaunch {
  coverage?: "search" | "full" | "exhaustive";   // omitted = the goal's own coverage
  guidance?: string;
  based_on_version?: number;
  fresh_coverage?: boolean;
  llm: { provider: string; model: string };
  budget_chars?: number;
  max_rounds?: number;
  max_llm_calls?: number;
  concurrency?: number;   // 1-8; a parallel stage-E slice adds it server-side (default 1)
  reasoning_effort?: string;   // omitted -> the endpoint's own default
}

export type Kb = {
  id: number; name: string; slug: string;
  corpus_id: number; corpus_name: string;
};
export type KbPageSummary = {
  type: string; title: string; slug: string; description: string;
};
export type KbDetail = Kb & { index_markdown: string; pages: KbPageSummary[] };
export type KbPage = {
  type: string; title: string; slug: string; description: string;
  tags: string[]; timestamp: string; sources: unknown[]; body: string;
};
