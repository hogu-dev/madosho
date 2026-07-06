import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { UploadModal } from "../UploadModal";
import { api } from "../../api/client";

const COMPONENTS = {
  parser: [{ name: "docling", license: "MIT", org: null }],
  chunker: [{ name: "semantic", license: null, org: null }],
  embedder: [{ name: "bge-large", license: "Apache-2.0", org: null }],
  reranker: [],
};

// catalog with a hard slot dependency: docling-hybrid needs the docling parser
const COMPONENTS_DEP = {
  parser: [{ name: "docling", license: null, org: null },
           { name: "pymupdf", license: null, org: null }],
  chunker: [{ name: "docling-hybrid", license: null, org: null,
              requires: { parser: ["docling"] } },
            { name: "recursive-text", license: null, org: null }],
  embedder: [{ name: "bge-large", license: null, org: null }],
  reranker: [],
};

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "components").mockResolvedValue(COMPONENTS as any);
  vi.spyOn(api, "listLlmEndpoints").mockResolvedValue([]);
});

function pdf(name = "a.pdf") { return new File(["x"], name, { type: "application/pdf" }); }
function png(name = "scan.png") { return new File(["x"], name, { type: "image/png" }); }

// catalog offering the vision extractor + a vision-capable endpoint
const COMPONENTS_VISION = {
  parser: [{ name: "docling", license: null, org: null },
           { name: "vision", license: null, org: null }],
  chunker: [{ name: "recursive-text", license: null, org: null }],
  embedder: [{ name: "bge-large", license: null, org: null }],
  reranker: [],
};

test("shows the title and loads the recipe selects when open", async () => {
  render(<UploadModal open onClose={() => {}} onUploaded={() => {}} />);
  expect(screen.getByText("Upload & index")).toBeInTheDocument();
  expect(await screen.findByRole("option", { name: "docling" })).toBeInTheDocument();
});

test("an unsupported file (e.g. .zip) shows the unsupported message and is excluded from the count", async () => {
  render(<UploadModal open onClose={() => {}} onUploaded={() => {}} />);
  await screen.findByRole("option", { name: "docling" });
  const input = screen.getByTestId("upload-input");
  // .docx/.md/.html are now supported (docling text lane); a .zip is genuinely not
  fireEvent.change(input, { target: { files: [new File(["x"], "bundle.zip",
    { type: "application/zip" })] } });
  expect(screen.getByText(/Unsupported format/i)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Upload & index 0 files/i })).toBeDisabled();
});

test("office/text documents (docx, md) are accepted through the default docling lane", async () => {
  render(<UploadModal open onClose={() => {}} onUploaded={() => {}} />);
  await screen.findByRole("option", { name: "docling" });
  const input = screen.getByTestId("upload-input");
  fireEvent.change(input, { target: { files: [
    new File(["x"], "report.docx", { type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" }),
    new File(["x"], "notes.md", { type: "text/markdown" })] } });
  expect(screen.queryByText(/Unsupported format/i)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Upload & index 2 files/i })).not.toBeDisabled();
});

test("uploads each valid PDF then calls onUploaded and onClose", async () => {
  const onUploaded = vi.fn(), onClose = vi.fn();
  const create = vi.spyOn(api, "createDocument").mockResolvedValue({ id: 1 } as any);
  render(<UploadModal open onClose={onClose} onUploaded={onUploaded} />);
  await screen.findByRole("option", { name: "docling" });
  fireEvent.change(screen.getByTestId("upload-input"),
    { target: { files: [pdf("a.pdf"), pdf("b.pdf")] } });
  fireEvent.click(screen.getByRole("button", { name: /Upload & index 2 files/i }));
  await waitFor(() => expect(create).toHaveBeenCalledTimes(2));
  expect(onUploaded).toHaveBeenCalled();
  expect(onClose).toHaveBeenCalled();
});

test("an image needs the vision extractor: blocked on docling, allowed on vision", async () => {
  vi.spyOn(api, "components").mockResolvedValue(COMPONENTS_VISION as any);
  vi.spyOn(api, "listLlmEndpoints").mockResolvedValue([
    { id: 1, name: "vgpu", supports_vision: true, is_vision_default: true } as any]);
  render(<UploadModal open onClose={() => {}} onUploaded={() => {}} />);
  await screen.findByRole("option", { name: "vision" });
  fireEvent.change(screen.getByTestId("upload-input"), { target: { files: [png()] } });
  // default parser is docling -> image/parser mismatch -> blocked with guidance
  expect(screen.getByText(/pick the Vision extractor/i)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Upload & index 1 file/i })).toBeDisabled();
  // switch the extractor to vision -> mismatch resolved, upload enabled
  fireEvent.change(screen.getByLabelText("Extract"), { target: { value: "vision" } });
  expect(screen.queryByText(/pick the Vision extractor/i)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Upload & index 1 file/i })).toBeEnabled();
});

test("an incompatible recipe flags the Extract slot and disables the upload button", async () => {
  vi.spyOn(api, "components").mockResolvedValue(COMPONENTS_DEP as any);
  render(<UploadModal open onClose={() => {}} onUploaded={() => {}} />);
  // opens on the canonical docling + docling-hybrid stack (valid)
  await screen.findByRole("option", { name: "docling-hybrid" });
  fireEvent.change(screen.getByTestId("upload-input"), { target: { files: [pdf("a.pdf")] } });
  expect(screen.getByRole("button", { name: /Upload & index 1 file/i })).toBeEnabled();

  // switch the parser to pymupdf -> docling-hybrid can't run -> BOTH boxes flag
  fireEvent.change(screen.getByLabelText("Extract"), { target: { value: "pymupdf" } });
  const alerts = screen.getAllByRole("alert").map((a) => a.textContent).join(" | ");
  expect(alerts).toMatch(/Chunk needs docling.*extract/i);              // the chunk box
  expect(alerts).toMatch(/Extract needs docling.*docling-hybrid/i);     // the extract box
  expect(screen.getByRole("button", { name: /Upload & index 1 file/i })).toBeDisabled();

  // resolve it by putting the parser back to docling -> re-enabled, no alert
  fireEvent.change(screen.getByLabelText("Extract"), { target: { value: "docling" } });
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Upload & index 1 file/i })).toBeEnabled();
});
