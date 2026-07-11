import { createBrowserRouter, Navigate } from "react-router-dom";
import { Shell } from "./Shell";
import { Documents } from "./pages/Documents";
import { Jobs } from "./pages/Jobs";
import { Corpora } from "./pages/Corpora";
import { CorpusDetail } from "./pages/CorpusDetail";
import { NotFound } from "./pages/NotFound";
import { Workbench } from "./pages/Workbench";
import { Scrying } from "./pages/Scrying";
import { Compare } from "./pages/Compare";
import { Quality } from "./pages/Quality";
import { EvalRun } from "./pages/EvalRun";
import { Research } from "./pages/Research";
import { ResearchRun } from "./pages/ResearchRun";
import { Alchemy } from "./pages/Alchemy";
import { AlchemyGoalDetail } from "./pages/AlchemyGoalDetail";
import { AlchemyRunView } from "./pages/AlchemyRunView";
import { Settings } from "./pages/Settings";
import { Keys } from "./pages/Keys";
import { Users } from "./pages/Users";

export const routes = [
  { path: "/", element: <Shell />, children: [
    { index: true, element: <Navigate to="/documents" replace /> },
    { path: "documents", element: <Documents /> },
    { path: "documents/:documentId", element: <Workbench /> },
    { path: "jobs", element: <Jobs /> },
    { path: "corpora", element: <Corpora /> },
    { path: "corpora/:corpusId", element: <CorpusDetail /> },
    { path: "scrying", element: <Scrying /> },
    { path: "compare", element: <Compare /> },
    { path: "quality", element: <Quality /> },
    { path: "quality/eval/:runId", element: <EvalRun /> },
    { path: "research", element: <Research /> },
    { path: "research/:runId", element: <ResearchRun /> },
    { path: "alchemy", element: <Alchemy /> },
    { path: "alchemy/:goalRef", element: <AlchemyGoalDetail /> },
    { path: "alchemy/:goalRef/runs/:version", element: <AlchemyRunView /> },
    { path: "settings", element: <Settings /> },
    { path: "keys", element: <Keys /> },
    { path: "users", element: <Users /> },
    { path: "*", element: <NotFound /> },
  ] },
];

export const router = createBrowserRouter(routes);
