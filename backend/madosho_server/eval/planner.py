# backend/madosho_server/eval/planner.py
"""Build the per-stage candidate sets F will sweep. Each candidate is a patch on
the baseline config the runner can apply. Extraction is E's domain and is not
swept. Component candidates come from the registry, filtered by the same Tier-B
origin + hardware policy the config form uses (D1/D3); keyword/semantic
candidates are retrieval parameter sets, not registry components.

The default parameter sets below are intentionally small and editable in the
launch wizard before a run. Bigger sweeps cost more candidate runs (cheap: embed
+ vector search, no LLM) but the wall-clock still grows, so defaults stay lean."""
from __future__ import annotations

SWEPT_STAGES = ("chunk", "embed", "keyword", "semantic", "rerank")
_BLOCKED_TIERS = {"adversarial", "unknown"}     # tunable: which origin tiers to exclude

# Default query-side parameter sweeps (editable in the wizard).
_KEYWORD_KS = (20, 50)
_SEMANTIC_KS = (50, 100)
_RERANK_TOP_KS = (5, 8, 12)


def _allowed(row: dict) -> bool:
    return (row.get("origin_tier") not in _BLOCKED_TIERS)


def _current_query_op(query: list, name: str) -> dict:
    for step in query:
        if isinstance(step, str) and step == name:
            return {}
        if isinstance(step, dict) and name in step:
            return dict(step[name] or {})
    return {}


def _component_candidates(stage: str, field: str, current: str, rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        name = row["name"]
        if name == current or not _allowed(row):
            continue
        out.append({"stage": stage, "label": f"{field}={name}", "kind": "ingest",
                    "field": field, "ref": name})
    return out


def build_plan(baseline: dict, registry: dict, traits: dict | None = None) -> dict:
    """registry is the components.list_components() shape: {kind: [rows]}.
    traits is reserved for trait-informed pruning (kept simple in v1)."""
    ingest = baseline.get("ingest", {})
    query = baseline.get("query", [])

    def ref_name(v):
        return v if isinstance(v, str) else (next(iter(v)) if isinstance(v, dict) else None)

    plan: dict[str, list[dict]] = {}
    plan["chunk"] = _component_candidates(
        "chunk", "chunker", ref_name(ingest.get("chunker")), registry.get("chunker", []))
    plan["embed"] = _component_candidates(
        "embed", "embedder", ref_name(ingest.get("embedder")), registry.get("embedder", []))

    cur_kw = _current_query_op(query, "keyword_search").get("k", 50)
    plan["keyword"] = [
        {"stage": "keyword", "label": f"keyword k={k}", "kind": "query",
         "op": "keyword_search", "options": {"k": k}}
        for k in _KEYWORD_KS if k != cur_kw]

    cur_sem = _current_query_op(query, "semantic_search").get("k", 50)
    plan["semantic"] = [
        {"stage": "semantic", "label": f"semantic k={k}", "kind": "query",
         "op": "semantic_search", "options": {"k": k}}
        for k in _SEMANTIC_KS if k != cur_sem]

    cur_rr = _current_query_op(query, "rerank")
    rr_model = cur_rr.get("model")
    cur_top = cur_rr.get("top_k", 8)
    plan["rerank"] = []
    for tk in _RERANK_TOP_KS:
        if tk == cur_top:
            continue
        plan["rerank"].append({"stage": "rerank", "label": f"rerank top_k={tk}",
                               "kind": "query", "op": "rerank",
                               "options": {"model": rr_model, "top_k": tk}})
    # alternate reranker models from the registry (keep the baseline top_k)
    for row in registry.get("reranker", []):
        if row["name"] == rr_model or not _allowed(row):
            continue
        plan["rerank"].append({"stage": "rerank", "label": f"reranker={row['name']}",
                               "kind": "query", "op": "rerank",
                               "options": {"model": row["name"], "top_k": cur_top}})
    return plan
