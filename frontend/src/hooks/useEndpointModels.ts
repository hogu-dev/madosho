import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { EndpointModel, LlmEndpoint } from "../api/types";

export interface EndpointModelSelection {
  ep: LlmEndpoint | null;
  endpointName: string;
  setEndpointName: (name: string) => void;
  models: EndpointModel[];
  modelId: string;
  setModelId: (id: string) => void;
  ladder: string[];              // reasoning efforts valid for the current model
  effort: string;                // "" = endpoint default (omit from launch)
  setEffort: (e: string) => void;
}

function fallback(model: string): EndpointModel[] {
  return model ? [{ id: model, reasoning_efforts: [], default_effort: null }] : [];
}

// Shared model/reasoning selection for the launch forms (Alchemy + Research).
// Given the loaded endpoints it tracks the chosen ENDPOINT, fetches that
// endpoint's served MODELS (GET /llm-endpoints/{id}/models — a proxy fans out
// into its many models; a single-model server falls back to its one pinned
// model), tracks the chosen model, and keeps the reasoning EFFORT valid for
// that model (resetting to "" = endpoint default when the picked model's ladder
// does not include the current effort). The two forms render their own dropdowns
// from this state so their layouts stay local.
export function useEndpointModels(endpoints: LlmEndpoint[]): EndpointModelSelection {
  const [endpointName, setEndpointName] = useState("");
  const [models, setModels] = useState<EndpointModel[]>([]);
  const [modelId, setModelId] = useState("");
  const [effort, setEffort] = useState("");

  // Default the endpoint to the registry default (or first) once loaded.
  useEffect(() => {
    if (endpoints.length === 0) return;
    setEndpointName((n) =>
      n || ((endpoints.find((e) => e.is_default) ?? endpoints[0])?.name ?? ""));
  }, [endpoints]);

  const ep = endpoints.find((e) => e.name === endpointName) ?? null;
  const epId = ep?.id ?? null;
  const epModel = ep?.model ?? "";

  // Fetch the chosen endpoint's models; degrade to its pinned model on failure
  // so the form always has at least one selectable model.
  useEffect(() => {
    if (epId == null) { setModels([]); return; }
    let alive = true;
    api.listEndpointModels(epId)
      .then((ms) => { if (alive) setModels(ms.length ? ms : fallback(epModel)); })
      .catch(() => { if (alive) setModels(fallback(epModel)); });
    return () => { alive = false; };
  }, [epId, epModel]);

  // Default the model to the endpoint's pinned one (or first served); keep a
  // still-valid pick across model-list changes.
  useEffect(() => {
    setModelId((m) => {
      if (m && models.some((x) => x.id === m)) return m;
      if (epModel && models.some((x) => x.id === epModel)) return epModel;
      return models[0]?.id ?? "";
    });
  }, [models, epModel]);

  const current = models.find((m) => m.id === modelId) ?? null;
  const ladder = current?.reasoning_efforts ?? [];

  // Drop a now-invalid effort when the model (hence its ladder) changes.
  useEffect(() => {
    setEffort((e) => (e && !ladder.includes(e) ? "" : e));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modelId, models]);

  return { ep, endpointName, setEndpointName, models, modelId, setModelId,
    ladder, effort, setEffort };
}
