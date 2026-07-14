import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { ImportKbModal } from "../ImportKbModal";
import { api } from "../../api/client";

vi.mock("../../api/client", () => ({ api: { listCorpora: vi.fn(), importKb: vi.fn() } }));

function withRelPath(file: File, rel: string): File {
  Object.defineProperty(file, "webkitRelativePath", { value: rel, configurable: true });
  return file;
}

beforeEach(() => {
  vi.clearAllMocks();
  (api.listCorpora as any).mockResolvedValue([{ id: 1, name: "rag-notes", config: {} }]);
  (api.importKb as any).mockResolvedValue({ id: 7, filename: "demo-kb.md", status: "received" });
});

describe("ImportKbModal", () => {
  it("import is disabled until a KB is chosen", () => {
    render(<ImportKbModal open onClose={() => {}} onImported={() => {}} />);
    expect(screen.getByRole("button", { name: "Import KB" })).toBeDisabled();
  });

  it("zip mode sends the archive and the chosen corpus", async () => {
    const onImported = vi.fn();
    render(<ImportKbModal open onClose={() => {}} onImported={onImported} />);
    fireEvent.click(screen.getByRole("button", { name: "Zip file" }));
    const zip = new File([new Uint8Array([1, 2, 3])], "kb.zip", { type: "application/zip" });
    fireEvent.change(screen.getByTestId("kb-zip-input"), { target: { files: [zip] } });
    await screen.findByRole("option", { name: "rag-notes" });
    fireEvent.change(screen.getByLabelText("Add to corpus"), { target: { value: "rag-notes" } });
    fireEvent.click(screen.getByRole("button", { name: "Import KB" }));
    await waitFor(() => expect(api.importKb).toHaveBeenCalled());
    const arg = (api.importKb as any).mock.calls.at(-1)[0];
    expect(arg.archive).toBe(zip);
    expect(arg.corpus).toBe("rag-notes");
    expect(onImported).toHaveBeenCalled();
  });

  it("folder mode sends only KB files with their relative paths (junk filtered)", async () => {
    render(<ImportKbModal open onClose={() => {}} onImported={() => {}} />);
    const files = [
      withRelPath(new File(["name: demo-kb\nformat: 1\n"], "kb.yaml"), "demo-kb/kb.yaml"),
      withRelPath(new File(["# Index"], "index.md"), "demo-kb/wiki/index.md"),
      withRelPath(new File(["x"], "search.db"), "demo-kb/.llmkb/search.db"),   // not a KB file
    ];
    fireEvent.change(screen.getByTestId("kb-folder-input"), { target: { files } });
    fireEvent.click(screen.getByRole("button", { name: "Import KB" }));
    await waitFor(() => expect(api.importKb).toHaveBeenCalled());
    const paths = ((api.importKb as any).mock.calls.at(-1)[0].folder as { path: string }[])
      .map((x) => x.path);
    expect(paths).toEqual(["demo-kb/kb.yaml", "demo-kb/wiki/index.md"]);   // search.db dropped
  });

  it("a folder with no kb.yaml is rejected before submit", async () => {
    render(<ImportKbModal open onClose={() => {}} onImported={() => {}} />);
    const files = [withRelPath(new File(["# Index"], "index.md"), "notes/wiki/index.md")];
    fireEvent.change(screen.getByTestId("kb-folder-input"), { target: { files } });
    expect(screen.getByRole("alert").textContent).toMatch(/no kb\.yaml/i);
    expect(screen.getByRole("button", { name: "Import KB" })).toBeDisabled();
    expect(api.importKb).not.toHaveBeenCalled();
  });
});
