import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { SaveToKbModal } from "../SaveToKbModal";
import { api } from "../../api/client";

vi.mock("../../api/client", () => ({
  api: { listKbs: vi.fn(), saveKbPage: vi.fn() },
}));

beforeEach(() => {
  vi.restoreAllMocks();
  (api.listKbs as any).mockResolvedValue([
    { id: 3, name: "Notes", slug: "notes", corpus_id: 1, corpus_name: "c1" },
    { id: 4, name: "Other", slug: "other", corpus_id: 2, corpus_name: "c2" },
  ]);
});

const open = () => render(
  <SaveToKbModal open onClose={() => {}} corpusId={1}
    defaultTitle="Photosynthesis" body={"# Report\n\nfindings"} />);

describe("SaveToKbModal", () => {
  it("defaults to a new KB named after the run and saves by name", async () => {
    const save = (api.saveKbPage as any).mockResolvedValue(
      { kb_id: 9, kb_name: "Photosynthesis", corpus_id: 1, slug: "photosynthesis",
        action: "created", created_kb: true });
    open();
    // title + new-KB name both prefill from defaultTitle
    await waitFor(() =>
      expect((screen.getByLabelText("KB name") as HTMLInputElement).value)
        .toBe("Photosynthesis"));
    fireEvent.click(screen.getByRole("button", { name: /save to kb/i }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][0]).toBe(1);                       // corpusId
    expect(save.mock.calls[0][1]).toMatchObject({
      kb_name: "Photosynthesis", title: "Photosynthesis", body: "# Report\n\nfindings" });
    expect(await screen.findByRole("status")).toHaveTextContent(/Saved page/i);
  });

  it("existing-KB mode only lists KBs from this corpus and saves by id", async () => {
    const save = (api.saveKbPage as any).mockResolvedValue(
      { kb_id: 3, kb_name: "Notes", corpus_id: 1, slug: "photosynthesis",
        action: "updated", created_kb: false });
    open();
    fireEvent.click(screen.getByRole("button", { name: /existing kb/i }));
    const select = await screen.findByLabelText("Knowledge base");
    // corpus 2's "Other" KB must not be offered
    expect(screen.queryByText("Other")).not.toBeInTheDocument();
    fireEvent.change(select, { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: /save to kb/i }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][1]).toMatchObject({ kb_id: 3 });
  });
});
