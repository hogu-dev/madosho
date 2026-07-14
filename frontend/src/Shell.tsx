import { Outlet, useLocation } from "react-router-dom";
import { Frame, Breadcrumbs } from "./design/Frame";
import { ReadOnlyBanner } from "./auth/ReadOnlyBanner";

const CRUMB: Record<string, string> = {
  documents: "Documents", corpora: "Corpora", "knowledge-bases": "Knowledge bases", scrying: "Scrying",
  quality: "Quality", research: "Research", alchemy: "Alchemy",
  settings: "Settings", keys: "Keys", users: "Users",
};

export function Shell() {
  const { pathname } = useLocation();
  const seg = pathname.split("/").filter(Boolean)[0] ?? "documents";
  const label = CRUMB[seg] ?? "Documents";
  return (
    <Frame topbar={<Breadcrumbs items={[{ label }]} />}>
      <ReadOnlyBanner />
      <Outlet />
    </Frame>
  );
}
