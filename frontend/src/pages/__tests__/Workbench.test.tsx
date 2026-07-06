import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { describe, it, afterEach } from "vitest";
import { Workbench } from "../Workbench";
import { api } from "../../api/client";

// Workbench now calls useAuth() for canWrite gating; mock it so tests run without a real provider.
vi.mock("../../auth/AuthContext", () => ({ useAuth: () => ({ canWrite: true }) }));

const DOC = { id: 1, filename: "saturnv.pdf", status: "indexed", error: null,
  progress: { page_count: 48 }, selected_pipeline_id: null,
  corpora: [{ id: 7, name: "aerospace" }] };
const PIPES = [
  { id: 10, name: "docling_v2", slots: { extract: "docling", chunk: "semantic", index: "bge-large" },
    steps: { extract: 4, chunk: 3, index: 4 }, rating: 11, status: "indexed",
    is_default: true, effective: true },
  { id: 11, name: "pypdfium2_fast", slots: { extract: "pypdfium2", chunk: "fixed", index: "bge" },
    steps: {}, rating: 0, status: "building", is_default: false, effective: false,
    progress: { phase: "index", log: [{ t: 1, msg: "extract · pypdfium2 · 48 pp" }] } },
];

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "listLlmEndpoints").mockResolvedValue([]);
});

function renderAt(id = "1") {
  return render(
    <MemoryRouter initialEntries={[`/documents/${id}`]}>
      <Routes><Route path="/documents/:documentId" element={<Workbench />} /></Routes>
    </MemoryRouter>);
}

test("renders the document filename as a heading after load", async () => {
  vi.spyOn(api, "getDocument").mockResolvedValue(DOC as any);
  vi.spyOn(api, "getDocumentPipelines").mockResolvedValue(PIPES as any);
  renderAt();
  expect(await screen.findByRole("heading", { name: "saturnv.pdf" })).toBeInTheDocument();
});

test("shows the effective badge, total, and membership chip", async () => {
  vi.spyOn(api, "getDocument").mockResolvedValue(DOC as any);
  vi.spyOn(api, "getDocumentPipelines").mockResolvedValue(PIPES as any);
  renderAt();
  expect(await screen.findByText("docling_v2")).toBeInTheDocument();
  expect(screen.getByText("Effective")).toBeInTheDocument();
  expect(screen.getByText("11/15")).toBeInTheDocument();
  expect(screen.getByText("aerospace")).toBeInTheDocument();
});

test("a building pipeline shows the console line, not a score", async () => {
  vi.spyOn(api, "getDocument").mockResolvedValue(DOC as any);
  vi.spyOn(api, "getDocumentPipelines").mockResolvedValue(PIPES as any);
  renderAt();
  expect(await screen.findByText("pypdfium2_fast")).toBeInTheDocument();
  expect(screen.getByText(/extract · pypdfium2/)).toBeInTheDocument();
});

test("shows an error line when the load fails", async () => {
  vi.spyOn(api, "getDocument").mockRejectedValue(new Error("boom"));
  vi.spyOn(api, "getDocumentPipelines").mockResolvedValue([] as any);
  renderAt();
  expect(await screen.findByText(/boom/i)).toBeInTheDocument();
});

const TWO_INDEXED = [
  { id: 10, name: "docling_v2", slots: { extract: "docling", chunk: "semantic", index: "bge" },
    steps: { extract: 4, chunk: 3, index: 4 }, rating: 11, status: "indexed",
    is_default: true, effective: true },
  { id: 12, name: "pypdfium2_v1", slots: { extract: "pypdfium2", chunk: "fixed", index: "bge" },
    steps: { extract: 3, chunk: 3, index: 3 }, rating: 9, status: "indexed",
    is_default: false, effective: false },
];

test("Set effective on a non-effective pipeline calls setSelectedPipeline", async () => {
  vi.spyOn(api, "getDocument").mockResolvedValue(DOC as any);
  vi.spyOn(api, "getDocumentPipelines").mockResolvedValue(TWO_INDEXED as any);
  vi.spyOn(api, "listCorpora").mockResolvedValue([] as any);
  const set = vi.spyOn(api, "setSelectedPipeline").mockResolvedValue({ id: 1, selected_pipeline_id: 12 } as any);
  renderAt();
  await screen.findByText("pypdfium2_v1");
  fireEvent.click(screen.getByRole("button", { name: /Set effective/i }));
  await waitFor(() => expect(set).toHaveBeenCalledWith(1, 12));
});

test("removing a corpus chip calls removeMembership", async () => {
  vi.spyOn(api, "getDocument").mockResolvedValue(DOC as any);
  vi.spyOn(api, "getDocumentPipelines").mockResolvedValue(TWO_INDEXED as any);
  vi.spyOn(api, "listCorpora").mockResolvedValue([] as any);
  const rm = vi.spyOn(api, "removeMembership").mockResolvedValue(undefined as any);
  renderAt();
  await screen.findByText("aerospace");
  fireEvent.click(screen.getByRole("button", { name: /Remove from aerospace/i }));
  await waitFor(() => expect(rm).toHaveBeenCalledWith(7, 1));
});

test("Add to corpus adds the picked corpus as a membership", async () => {
  vi.spyOn(api, "getDocument").mockResolvedValue(DOC as any);
  vi.spyOn(api, "getDocumentPipelines").mockResolvedValue(TWO_INDEXED as any);
  vi.spyOn(api, "listCorpora").mockResolvedValue(
    [{ id: 7, name: "aerospace" }, { id: 9, name: "propulsion" }] as any);
  const add = vi.spyOn(api, "addMembership").mockResolvedValue({} as any);
  renderAt();
  await screen.findAllByText("saturnv.pdf"); // appears in both breadcrumb and h1
  // The picker only offers corpora the doc is NOT already in (propulsion, id 9).
  fireEvent.change(await screen.findByLabelText(/Add to corpus/i), { target: { value: "9" } });
  await waitFor(() => expect(add).toHaveBeenCalledWith(9, 1));
});

test("deleting the document confirms, then calls deleteDocument", async () => {
  vi.spyOn(api, "getDocument").mockResolvedValue(DOC as any);
  vi.spyOn(api, "getDocumentPipelines").mockResolvedValue(TWO_INDEXED as any);
  vi.spyOn(api, "listCorpora").mockResolvedValue([] as any);
  const del = vi.spyOn(api, "deleteDocument").mockResolvedValue(undefined as any);
  renderAt();
  await screen.findByText("docling_v2");
  // header Delete is the first Delete button in the DOM (before the pipeline cards')
  fireEvent.click(screen.getAllByRole("button", { name: "Delete" })[0]);
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByText(/Delete this document/i)).toBeInTheDocument();
  expect(del).not.toHaveBeenCalled();                       // not until confirmed
  fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
  await waitFor(() => expect(del).toHaveBeenCalledWith(1));
});

test("deleting a pipeline confirms, then calls deletePipeline with its id", async () => {
  vi.spyOn(api, "getDocument").mockResolvedValue(DOC as any);
  vi.spyOn(api, "getDocumentPipelines").mockResolvedValue(TWO_INDEXED as any);
  vi.spyOn(api, "listCorpora").mockResolvedValue([] as any);
  const del = vi.spyOn(api, "deletePipeline").mockResolvedValue(undefined as any);
  renderAt();
  await screen.findByText("pypdfium2_v1");
  // Cards render newest-first (id desc), so: [0] header Delete, [1] pypdfium2_v1
  // card (id 12, newest), [2] docling_v2 card (id 10).
  fireEvent.click(screen.getAllByRole("button", { name: "Delete" })[1]);
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByText(/Delete this pipeline/i)).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
  await waitFor(() => expect(del).toHaveBeenCalledWith(1, 12));
});

test("pipelines render newest-first (highest id at the top)", async () => {
  vi.spyOn(api, "getDocument").mockResolvedValue(DOC as any);
  vi.spyOn(api, "getDocumentPipelines").mockResolvedValue(TWO_INDEXED as any);
  vi.spyOn(api, "listCorpora").mockResolvedValue([] as any);
  renderAt();
  const newest = await screen.findByText("pypdfium2_v1");    // id 12
  const oldest = screen.getByText("docling_v2");             // id 10
  // newest (id 12) precedes the older card (id 10) in the DOM
  expect(newest.compareDocumentPosition(oldest) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

test("a pipeline shows its created date when the API provides one", async () => {
  vi.spyOn(api, "getDocument").mockResolvedValue(DOC as any);
  vi.spyOn(api, "getDocumentPipelines").mockResolvedValue(
    [{ id: 20, name: "dated_v1", slots: { extract: "docling", chunk: "semantic", index: "bge" },
       steps: { extract: 3, chunk: 3, index: 3 }, rating: 9, status: "indexed",
       is_default: false, effective: false, created_at: "2026-06-30T12:00:00" }] as any);
  vi.spyOn(api, "listCorpora").mockResolvedValue([] as any);
  renderAt();
  expect(await screen.findByText(/^Created .*2026/)).toBeInTheDocument();
});

const COMPONENTS = {
  parser: [{ name: "docling", license: null, org: null }, { name: "pypdfium2", license: null, org: null }],
  chunker: [{ name: "semantic", license: null, org: null }],
  embedder: [{ name: "bge-large", license: null, org: null }],
  reranker: [],
};

test("the recommended banner shows the suggested tools when one is returned", async () => {
  vi.spyOn(api, "getDocument").mockResolvedValue(DOC as any);
  vi.spyOn(api, "getDocumentPipelines").mockResolvedValue(TWO_INDEXED as any);
  vi.spyOn(api, "listCorpora").mockResolvedValue([] as any);
  vi.spyOn(api, "components").mockResolvedValue(COMPONENTS as any);
  vi.spyOn(api, "getRecommendedPipeline").mockResolvedValue(
    { slots: { extract: "docling", chunk: "semantic", index: "bge-large" },
      steps: { extract: 4, chunk: 4, index: 4 }, projected_rating: 12,
      already_built: false, matches: null } as any);
  renderAt();
  expect(await screen.findByText(/Recommended/i)).toBeInTheDocument();
  expect(screen.getByText(/12\s*\/\s*15/)).toBeInTheDocument();
});

test("Open in Scrying link carries the document id", async () => {
  vi.spyOn(api, "getDocument").mockResolvedValue(DOC as any);
  vi.spyOn(api, "getDocumentPipelines").mockResolvedValue(PIPES as any);
  renderAt("1");
  const link = await screen.findByRole("link", { name: /Open in Scrying/ });
  expect(link).toHaveAttribute("href", "/scrying?document=1");
});

test("+ New pipeline auto-fills a name from the doc + extractor, syncing on swap", async () => {
  vi.spyOn(api, "getDocument").mockResolvedValue(DOC as any);
  vi.spyOn(api, "getDocumentPipelines").mockResolvedValue(TWO_INDEXED as any);
  vi.spyOn(api, "listCorpora").mockResolvedValue([] as any);
  vi.spyOn(api, "components").mockResolvedValue(COMPONENTS as any);
  vi.spyOn(api, "getRecommendedPipeline").mockResolvedValue(null as any);
  renderAt();
  await screen.findAllByText("saturnv.pdf");
  fireEvent.click(screen.getByRole("button", { name: /\+ New pipeline/i }));
  const input = await screen.findByLabelText(/Pipeline name/i) as HTMLInputElement;
  // default extractor is docling -> <stem>_<parser>, no collision with existing names
  await waitFor(() => expect(input.value).toBe("saturnv_docling"));
  // swapping the extractor re-suggests while the name is still auto-filled
  fireEvent.change(screen.getByLabelText("Extract"), { target: { value: "pypdfium2" } });
  await waitFor(() => expect(input.value).toBe("saturnv_pypdfium2"));
  // but once the user types, the suggestion never clobbers it
  fireEvent.change(input, { target: { value: "my_run" } });
  fireEvent.change(screen.getByLabelText("Extract"), { target: { value: "docling" } });
  expect(input.value).toBe("my_run");
});

test("+ New pipeline reveals the form and submits a recipe", async () => {
  vi.spyOn(api, "getDocument").mockResolvedValue(DOC as any);
  vi.spyOn(api, "getDocumentPipelines").mockResolvedValue(TWO_INDEXED as any);
  vi.spyOn(api, "listCorpora").mockResolvedValue([] as any);
  vi.spyOn(api, "components").mockResolvedValue(COMPONENTS as any);
  vi.spyOn(api, "getRecommendedPipeline").mockResolvedValue(null as any);
  const create = vi.spyOn(api, "createPipeline").mockResolvedValue({ id: 99 } as any);
  renderAt();
  await screen.findAllByText("saturnv.pdf");
  fireEvent.click(screen.getByRole("button", { name: /\+ New pipeline/i }));
  fireEvent.change(await screen.findByLabelText(/Pipeline name/i), { target: { value: "alt_fast" } });
  fireEvent.click(screen.getByRole("button", { name: /^Build$/i }));
  await waitFor(() => expect(create).toHaveBeenCalledWith(1,
    expect.objectContaining({ name: "alt_fast", parser: "docling" })));
});

const COMPONENTS_DEP = {
  parser: [{ name: "docling", license: null, org: null }, { name: "pypdfium2", license: null, org: null }],
  chunker: [{ name: "docling-hybrid", license: null, org: null, requires: { parser: ["docling"] } },
            { name: "recursive-text", license: null, org: null }],
  embedder: [{ name: "bge-large", license: null, org: null }],
  reranker: [],
};

test("+ New pipeline flags the Extract slot and disables Build until resolved", async () => {
  vi.spyOn(api, "getDocument").mockResolvedValue(DOC as any);
  vi.spyOn(api, "getDocumentPipelines").mockResolvedValue(TWO_INDEXED as any);
  vi.spyOn(api, "listCorpora").mockResolvedValue([] as any);
  vi.spyOn(api, "components").mockResolvedValue(COMPONENTS_DEP as any);
  vi.spyOn(api, "getRecommendedPipeline").mockResolvedValue(null as any);
  renderAt();
  await screen.findAllByText("saturnv.pdf");
  fireEvent.click(screen.getByRole("button", { name: /\+ New pipeline/i }));
  fireEvent.change(await screen.findByLabelText(/Pipeline name/i), { target: { value: "alt" } });
  // opens on docling + docling-hybrid -> valid -> Build enabled
  expect(screen.getByRole("button", { name: /^Build$/i })).toBeEnabled();
  // switch parser to pypdfium2 -> docling-hybrid can't run -> BOTH boxes flag
  fireEvent.change(screen.getByLabelText("Extract"), { target: { value: "pypdfium2" } });
  const alerts = screen.getAllByRole("alert").map((a) => a.textContent).join(" | ");
  expect(alerts).toMatch(/Chunk needs docling.*extract/i);
  expect(alerts).toMatch(/Extract needs docling.*docling-hybrid/i);
  expect(screen.getByRole("button", { name: /^Build$/i })).toBeDisabled();
  // pick a parser-agnostic chunker -> requirement gone -> clears
  fireEvent.change(screen.getByLabelText("Chunk"), { target: { value: "recursive-text" } });
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /^Build$/i })).toBeEnabled();
});

const DOC_OPTS = { id: 1, filename: "f.pdf", status: "indexed", error: null, corpora: [] };
const COMPONENTS_WITH_SCHEMA = {
  parser: [
    { name: "docling", options_schema: { properties: {
      ocr: { type: "boolean", default: false },
      ocr_engine: { type: "string", enum: ["tesseract", "rapidocr", "easyocr"],
        default: "tesseract" } } } },
  ],
  embedder: [{ name: "granite-embedding-english-r2" }],
  chunker: [
    { name: "semantic", options_schema: { properties: {
      breakpoint_percentile: { type: "number", default: 95, minimum: 0, maximum: 100 },
      max_chars: { type: "integer", default: 2000, minimum: 1 } } } },
  ],
};

describe("Workbench options", () => {
  afterEach(() => vi.restoreAllMocks());

  function mockSchemaApis() {
    vi.spyOn(api, "getDocument").mockResolvedValue(DOC_OPTS as any);
    vi.spyOn(api, "getDocumentPipelines").mockResolvedValue([] as any);
    vi.spyOn(api, "listCorpora").mockResolvedValue([] as any);
    vi.spyOn(api, "getRecommendedPipeline").mockResolvedValue(null as any);
    vi.spyOn(api, "listLlmEndpoints").mockResolvedValue([] as any);
    vi.spyOn(api, "components").mockResolvedValue(COMPONENTS_WITH_SCHEMA as any);
    return vi.spyOn(api, "createPipeline").mockResolvedValue({} as any);
  }

  it("renders chunker option inputs from the schema and sends only changed values", async () => {
    const create = mockSchemaApis();

    render(<MemoryRouter initialEntries={["/documents/1"]}>
      <Routes><Route path="/documents/:documentId" element={<Workbench />} /></Routes>
    </MemoryRouter>);

    fireEvent.click(await screen.findByText("+ New pipeline"));
    // the schema-driven field appears, pre-filled with the default
    const field = await screen.findByLabelText("breakpoint_percentile");
    expect((field as HTMLInputElement).value).toBe("95");
    fireEvent.change(field, { target: { value: "90" } });
    fireEvent.change(screen.getByLabelText("Pipeline name"), { target: { value: "sem-90" } });
    fireEvent.click(screen.getByText("Build"));
    await waitFor(() => expect(create).toHaveBeenCalled());
    const [, body] = create.mock.calls[0];
    expect((body as any).options.chunker).toEqual({ breakpoint_percentile: 90 });   // max_chars unchanged -> absent
  });

  it("renders an enum option as a select and sends it only when changed", async () => {
    const create = mockSchemaApis();

    render(<MemoryRouter initialEntries={["/documents/1"]}>
      <Routes><Route path="/documents/:documentId" element={<Workbench />} /></Routes>
    </MemoryRouter>);

    fireEvent.click(await screen.findByText("+ New pipeline"));
    // the enum field renders as a select pre-set to the schema default
    const select = await screen.findByLabelText("ocr_engine");
    expect(select.tagName).toBe("SELECT");
    expect((select as HTMLSelectElement).value).toBe("tesseract");
    expect(within(select as HTMLElement).getAllByRole("option").map((o) => (o as HTMLOptionElement).value))
      .toEqual(["tesseract", "rapidocr", "easyocr"]);
    // pick a non-default engine + turn ocr on -> both land in options.parser
    fireEvent.change(select, { target: { value: "rapidocr" } });
    fireEvent.click(screen.getByLabelText("ocr"));
    fireEvent.change(screen.getByLabelText("Pipeline name"), { target: { value: "ocr-rapid" } });
    fireEvent.click(screen.getByText("Build"));
    await waitFor(() => expect(create).toHaveBeenCalled());
    const [, body] = create.mock.calls[0];
    expect((body as any).options.parser).toEqual({ ocr: true, ocr_engine: "rapidocr" });
  });

  it("clearing a numeric input falls back to the default, not NaN", async () => {
    const create = mockSchemaApis();

    render(<MemoryRouter initialEntries={["/documents/1"]}>
      <Routes><Route path="/documents/:documentId" element={<Workbench />} /></Routes>
    </MemoryRouter>);

    fireEvent.click(await screen.findByText("+ New pipeline"));
    const field = await screen.findByLabelText("breakpoint_percentile");
    // user clears the field -> parseFloat("") is NaN; the guard must restore the default
    fireEvent.change(field, { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("Pipeline name"), { target: { value: "sem-default" } });
    fireEvent.click(screen.getByText("Build"));
    await waitFor(() => expect(create).toHaveBeenCalled());
    const [, body] = create.mock.calls[0];
    // value equals the default again -> changedOptions drops it -> no chunker override, no NaN/null
    const chunkerOpts = (body as any).options.chunker;
    expect(chunkerOpts === undefined || !("breakpoint_percentile" in chunkerOpts)).toBe(true);
  });
});
