import { api } from "../client";

beforeEach(() => { vi.restoreAllMocks(); });

test("listCorpora GETs /corpora", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify([{ id: 1, name: "a", config: {} }]), { status: 200 }));
  const out = await api.listCorpora();
  expect(fetchMock).toHaveBeenCalledWith("/api/corpora", expect.objectContaining({ method: "GET" }));
  expect(out[0].name).toBe("a");
});

test("createCorpus POSTs JSON and throws on error status", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ detail: "exists" }), { status: 409 }));
  await expect(api.createCorpus("dup")).rejects.toThrow(/exists/);
});

test("deleteVirtualModel DELETEs and resolves on 204", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(null, { status: 204 }));
  await expect(api.deleteVirtualModel(7)).resolves.toBeUndefined();
  expect(fetchMock).toHaveBeenCalledWith("/api/virtual-models/7", expect.objectContaining({ method: "DELETE" }));
});

test("deleteDocument DELETEs /documents/:id and resolves on 204", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(null, { status: 204 }));
  await expect(api.deleteDocument(5)).resolves.toBeUndefined();
  expect(fetchMock).toHaveBeenCalledWith("/api/documents/5", expect.objectContaining({ method: "DELETE" }));
});

test("query POSTs corpus scope to /query", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ hits: [] }), { status: 200 }));
  await api.query({ corpus: "c", prompt: "hello", llm: "openai:gpt-4o-mini" });
  expect(fetchMock).toHaveBeenCalledWith("/api/query", expect.objectContaining({ method: "POST" }));
  const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
  expect(body).toEqual({ corpus: "c", prompt: "hello", llm: "openai:gpt-4o-mini" });
});

test("query POSTs document scope (document_id, no corpus)", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ hits: [] }), { status: 200 }));
  await api.query({ document_id: 5, prompt: "hi" });
  const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
  expect(body).toEqual({ document_id: 5, prompt: "hi" });
});

test("getDocumentPipelines GETs the per-document list", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify([{ id: 1, name: "d_docling", slots: {}, steps: {},
      rating: 5.5, status: "indexed", is_default: true, effective: true }]), { status: 200 }));
  const out = await api.getDocumentPipelines(5);
  expect(fetchMock).toHaveBeenCalledWith("/api/documents/5/pipelines",
    expect.objectContaining({ method: "GET" }));
  expect(out[0].name).toBe("d_docling");
});

test("setSelectedPipeline PUTs the pipeline id", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ id: 5, selected_pipeline_id: 2 }), { status: 200 }));
  await api.setSelectedPipeline(5, 2);
  expect(fetchMock).toHaveBeenCalledWith("/api/documents/5/selected-pipeline",
    expect.objectContaining({ method: "PUT", body: JSON.stringify({ pipeline_id: 2 }) }));
});

test("createPipeline POSTs a recipe body to the document pipelines path", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ id: 5, name: "alt", document_id: 1,
      status: "building", collection: "c", slots: {} }), { status: 202 }));
  await api.createPipeline(1, { name: "alt", parser: "pypdfium2", chunker: "semantic", embedder: "bge" });
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe("/api/documents/1/pipelines");
  expect(init).toMatchObject({ method: "POST" });
  expect(JSON.parse(init!.body as string)).toEqual(
    { name: "alt", parser: "pypdfium2", chunker: "semantic", embedder: "bge" });
});

test("getRecommendedPipeline GETs the per-document recommendation", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ slots: { extract: "docling", chunk: "late", index: "nomic" },
      steps: { extract: 4, chunk: 3.5, index: 2.5 }, projected_rating: 10,
      already_built: false, matches: null }), { status: 200 }));
  const out = await api.getRecommendedPipeline(5);
  expect(fetchMock).toHaveBeenCalledWith("/api/documents/5/recommended-pipeline",
    expect.objectContaining({ method: "GET" }));
  expect(out?.projected_rating).toBe(10);
});

test("getRecommendedPipeline resolves null when the server has no suggestion", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("null", { status: 200 }));
  expect(await api.getRecommendedPipeline(5)).toBeNull();
});

test("listLibraryDocuments GETs /documents", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify([{ id: 1, filename: "a.pdf", status: "indexed",
      selected_pipeline_id: null, corpora: [{ id: 2, name: "aero" }], rating: 11 }]),
      { status: 200 }));
  const out = await api.listLibraryDocuments();
  expect(fetchMock).toHaveBeenCalledWith("/api/documents", expect.objectContaining({ method: "GET" }));
  expect(out[0].corpora[0].name).toBe("aero");
  expect(out[0].rating).toBe(11);
});

test("createDocument POSTs multipart with file + recipe fields", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ id: 9, filename: "a.pdf", status: "received" }), { status: 202 }));
  const file = new File(["x"], "a.pdf", { type: "application/pdf" });
  await api.createDocument(file, { parser: "docling", embedder: "bge-large" });
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe("/api/documents");
  expect(init).toMatchObject({ method: "POST" });
  expect(init!.body).toBeInstanceOf(FormData);
  const fd = init!.body as FormData;
  expect(fd.get("parser")).toBe("docling");
  expect(fd.get("embedder")).toBe("bge-large");
  expect(fd.get("file")).toBeInstanceOf(File);
});

test("addMembership POSTs to the corpus/document path", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ id: 9, filename: "a.pdf", status: "indexed" }), { status: 200 }));
  await api.addMembership(2, 9);
  expect(fetchMock).toHaveBeenCalledWith("/api/corpora/2/documents/9",
    expect.objectContaining({ method: "POST" }));
});

test("removeMembership DELETEs and resolves on 204", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(null, { status: 204 }));
  await expect(api.removeMembership(2, 9)).resolves.toBeUndefined();
  expect(fetchMock).toHaveBeenCalledWith("/api/corpora/2/documents/9",
    expect.objectContaining({ method: "DELETE" }));
});
