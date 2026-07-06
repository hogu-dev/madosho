# backend/madosho_server/extraction.py
"""Extraction head-to-head: convert a document two ways, have a judge that made
neither conversion rate faithfulness, and upgrade the document's Extraction cell
from static to measured.

The judge contract (JSON the vision judge returns):
    {"verdict": "a"|"b"|"tie", "winner_faithfulness": <0-5>,
     "confidence": <0-1>, "rationale": "<text>"}
`winner_faithfulness` IS the measured Extraction score (the best available
extraction's fidelity to the original page).
"""
from __future__ import annotations

import base64
import html
import io
import json
import logging
import re

from madosho_server import db
from madosho_server.filestore import FileStore
from madosho_server.llm import complete, respond
from madosho_server.llm_endpoints import resolve_vision_endpoint
from madosho_server.settings import Settings

logger = logging.getLogger("madosho_server.extraction")

ENGINE_DOCLING = "docling"
ENGINE_VISION = "gemma-12b-vision"
ENGINE_PYPDFIUM = "pypdfium2"


def render_page_images(file_path: str, *, dpi: int = 150,
                       max_pages: int = 10) -> list[tuple[int, bytes]]:
    """Rasterize a PDF's pages to PNG bytes (1-indexed) with pypdfium2.

    dpi drives the render scale (72 dpi == 1.0). Renders at most max_pages pages and
    logs a warning when the document is longer, so a truncated comparison is never
    silent. PDF only; the caller guards on mimetype.
    """
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(file_path)
    try:
        total = len(pdf)
        n = min(total, max_pages)
        if total > max_pages:
            logger.warning("render_page_images: document has %d pages; rendering first "
                           "%d (max_pages=%d)", total, n, max_pages)
        out: list[tuple[int, bytes]] = []
        scale = dpi / 72.0
        for i in range(n):
            page = pdf[i]
            pil = page.render(scale=scale).to_pil()
            buf = io.BytesIO()
            pil.save(buf, format="PNG")
            out.append((i + 1, buf.getvalue()))
        return out
    finally:
        pdf.close()


class VisionEndpointUnavailable(RuntimeError):
    """An extraction comparison was requested but no vision-capable default LLM
    endpoint is configured. Fail loud rather than silently skip the comparison."""


def select_judge(engine_a: str, engine_b: str, judges: list[dict]) -> dict | None:
    """First judge whose engine produced neither conversion; None -> human-only.

    Retained for helper/unit tests. No longer on the production path: the
    registry resolves a single judge endpoint directly."""
    for j in judges:
        if j["engine"] not in (engine_a, engine_b):
            return j
    return None


def verdict_to_score(verdict: dict) -> float:
    """The measured Extraction score = winner faithfulness, clamped to [0, 5]."""
    return max(0.0, min(5.0, float(verdict.get("winner_faithfulness", 0.0) or 0.0)))


def _docling_pages(artifacts: dict) -> dict[int, str]:
    """Group docling block content by source page (provenance.page), in order."""
    artifacts = artifacts or {}
    pages: dict[int, list[str]] = {}
    for b in (artifacts.get("blocks") or []):
        page = ((b.get("provenance") or {}).get("page")) or 1
        content = html.unescape(b.get("content") or "").strip()
        if content:
            pages.setdefault(int(page), []).append(content)
    return {p: "\n\n".join(parts) for p, parts in pages.items()}


def _docling_text(artifacts: dict) -> str:
    """Docling's extraction as readable text for the head-to-head's docling pane.

    Built from the structured BLOCKS (headings + paragraphs + clean table markdown)
    in reading order, NOT the chunk text. Chunks are tuned for retrieval and flatten
    each table into a single line -- exactly the structure a faithfulness judge (or a
    human verdict) needs to see, so we lose the whole point of docling if we hand it
    the chunk view. Blocks keep the table grid intact.

    Falls back to chunk text when an artifact set predates blocks (older documents),
    so existing corpora keep producing a comparison instead of an empty pane.
    """
    artifacts = artifacts or {}
    parts = []
    for b in (artifacts.get("blocks") or []):
        # docling escapes literal pipes inside table cells as &#124; so the markdown
        # stays valid; we render as plain text, so decode the entities back.
        content = html.unescape(b.get("content") or "").strip()
        if content:
            parts.append(content)
    if parts:
        return "\n\n".join(parts)
    return "\n\n".join(c.get("text", "") for c in artifacts.get("chunks", []))


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)

_TRANSCRIBE_INSTRUCTION = (
    "Transcribe this page image faithfully to plain text. Preserve reading order and "
    "table structure. Output only the transcription, no commentary.")


def _parse_verdict(content: str) -> dict:
    """Parse a judge verdict from model output that may be fenced or prose-wrapped.

    Real chat models wrap JSON in ```json fences or surround it with prose; a bare
    json.loads fails on both. Try, in order: a fenced block, the whole string, then
    the first balanced {...} object found in the text. Raise (fail loud) rather than
    fabricate a verdict when nothing parses.
    """
    text = content or ""
    candidates: list[str] = []
    m = _FENCE_RE.search(text)
    if m:
        candidates.append(m.group(1))
    candidates.append(text.strip())
    # first balanced object: scan for matching braces so trailing prose is ignored
    start = text.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start:i + 1])
                    break
    for cand in candidates:
        cand = cand.strip()
        if not cand:
            continue
        try:
            obj = json.loads(cand)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict):
            return obj
    raise ValueError(f"judge returned no parseable JSON object: {content!r:.300}")


def vision_transcribe(doc: "db.Document", provider: str, model: str,
                      settings: Settings, api_flavor: str = "chat") -> list[tuple[int, str]]:
    """Transcribe a document's pages with the resolved vision model by sending each
    page as an actual image. PDF only; non-PDF docs return [] (empty vision pane).
    api_flavor picks the wire shape (Chat Completions vs Responses API).
    Unit tests monkeypatch module-level `complete`/`respond` and stub the PDF.
    """
    if (doc.mimetype or "") != "application/pdf":
        logger.warning("vision_transcribe: %s is not a PDF (%s); skipping vision lane",
                       getattr(doc, "file_uri", "?"), doc.mimetype)
        return []
    store = FileStore(settings.filestore_dir)
    path = store.path_for(doc.file_uri)
    out: list[tuple[int, str]] = []
    for page_no, png in render_page_images(str(path)):
        b64 = base64.b64encode(png).decode("ascii")
        if api_flavor == "responses":
            text = respond([{"role": "user", "content": [
                {"type": "input_text", "text": _TRANSCRIBE_INSTRUCTION},
                {"type": "input_image", "detail": "auto",
                 "image_url": f"data:image/png;base64,{b64}"},
            ]}], provider=provider, model=model, settings=settings).strip()
        else:
            messages = [{"role": "user", "content": [
                {"type": "text", "text": _TRANSCRIBE_INSTRUCTION},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ]}]
            resp = complete(messages=messages, provider=provider, model=model,
                            settings=settings)
            text = (resp.choices[0].message.content or "").strip()
        # strip a stray code fence if the model wrapped the transcription
        m = _FENCE_RE.search(text)
        if m:
            text = m.group(1).strip()
        out.append((page_no, text))
    return out


def judge_call(text_a: str, text_b: str, provider: str, model: str, settings: Settings,
               api_flavor: str = "chat") -> dict:
    """Ask the judge which conversion is more faithful; expect the JSON contract."""
    prompt = ("Two conversions of the same page follow. Decide which is more faithful "
              "to the original and rate the better one's faithfulness 0-5. Reply as JSON "
              '{"verdict":"a"|"b"|"tie","winner_faithfulness":<0-5>,"confidence":<0-1>,'
              '"rationale":"..."}.\n\n--- A ---\n' + text_a + "\n\n--- B ---\n" + text_b)
    if api_flavor == "responses":
        return _parse_verdict(respond(prompt, provider=provider, model=model,
                                      settings=settings))
    resp = complete(messages=[{"role": "user", "content": prompt}],
                    provider=provider, model=model, settings=settings)
    return _parse_verdict(resp.choices[0].message.content)


def run_extraction_comparison(session, document_id: int, settings: Settings, *,
                              vision_transcribe=vision_transcribe, judge_call=judge_call,
                              resolve_vision=resolve_vision_endpoint) -> None:
    """Convert two ways, judge with the registry's default vision endpoint, persist
    comparison + measured cell. Fails loud if no vision endpoint is configured.

    The seams (vision_transcribe, judge_call, resolve_vision) are injectable so
    unit tests drive the logic without the GPU endpoint. Caller commits the session.
    """
    doc = session.get(db.Document, document_id)
    if doc is None:
        logger.warning("run_extraction_comparison: no document %s", document_id)
        return

    resolved = resolve_vision(session, settings)
    if resolved is None:
        raise VisionEndpointUnavailable(
            "extraction comparison needs a vision-capable default LLM endpoint; "
            "none configured (set one in Settings -> LLM Endpoints)")
    provider, model, bound, flavor = resolved

    doc_pages = _docling_pages(doc.artifacts)
    text_a = _docling_text(doc.artifacts)
    vision_pages = vision_transcribe(doc, provider, model, bound, flavor)   # [(page, text)]
    text_b = "\n\n".join(t for _, t in vision_pages)

    engine_b = f"{model} (vision)"
    page_nums = sorted(set(doc_pages) | {n for n, _ in vision_pages})
    vision_map = dict(vision_pages)
    pages = [{"page": n, "text_a": doc_pages.get(n, ""), "text_b": vision_map.get(n, "")}
             for n in page_nums]

    comp = db.ExtractionComparison(document_id=document_id, engine_a=ENGINE_DOCLING,
                                   text_a=text_a, engine_b=engine_b, text_b=text_b,
                                   pages=pages)
    verdict = judge_call(text_a, text_b, provider, model, bound, flavor)
    comp.judge_model = model
    comp.judge_verdict = verdict.get("verdict")
    comp.judge_score = verdict_to_score(verdict)
    comp.judge_confidence = verdict.get("confidence")
    comp.judge_rationale = verdict.get("rationale")
    session.add(comp)

    session.add(db.TechniqueRating(
        document_id=document_id, dimension="extraction",
        candidate_config=f"{ENGINE_DOCLING} vs {engine_b}", score=comp.judge_score,
        source="measured", rationale=comp.judge_rationale, suggestion=None,
        rater_version="head-to-head-v1"))
