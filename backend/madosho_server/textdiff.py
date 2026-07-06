# backend/madosho_server/textdiff.py
"""Word-level disagreement spans between two text conversions, as char offsets.

Tokenizing on words+whitespace (not characters) keeps spans meaningful: a changed
word is one span, not a scatter of single-char diffs. The viewer paints `a`/`b`
spans amber on load, then greens the winning side after a verdict.
"""
from __future__ import annotations

import difflib
import re

_TOKEN = re.compile(r"\S+|\s+")


def _tokens(s: str) -> list[str]:
    return _TOKEN.findall(s)


def _offsets(tokens: list[str]) -> list[int]:
    out, pos = [], 0
    for tok in tokens:
        out.append(pos); pos += len(tok)
    return out


def diff_spans(text_a: str, text_b: str) -> dict:
    ta, tb = _tokens(text_a), _tokens(text_b)
    oa, ob = _offsets(ta), _offsets(tb)
    # Diff only the non-whitespace ("content") tokens. Two conversions of the same
    # page almost always disagree on whitespace -- extra blank lines, re-wrapped
    # lines, different indentation -- and flagging all of that buries the real
    # content differences. By excluding whitespace tokens from the comparison,
    # whitespace-only changes produce no spans. We keep each content token's index
    # back into the full token list so the char offsets still point at the original
    # text for highlighting; a span runs from the first to the last differing
    # content token (any whitespace caught between them just rides along).
    ca = [i for i, t in enumerate(ta) if not t.isspace()]
    cb = [j for j, t in enumerate(tb) if not t.isspace()]
    sm = difflib.SequenceMatcher(a=[ta[i] for i in ca], b=[tb[j] for j in cb],
                                 autojunk=False)
    a_spans, b_spans = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("replace", "delete") and i2 > i1:
            first, last = ca[i1], ca[i2 - 1]
            a_spans.append([oa[first], oa[last] + len(ta[last])])
        if tag in ("replace", "insert") and j2 > j1:
            first, last = cb[j1], cb[j2 - 1]
            b_spans.append([ob[first], ob[last] + len(tb[last])])
    return {"a": a_spans, "b": b_spans}


def _merge_spans(spans: list[list[int]]) -> list[list[int]]:
    """Sort and coalesce overlapping/adjacent [start, end] intervals."""
    if not spans:
        return []
    ordered = sorted(spans)
    out = [list(ordered[0])]
    for s, e in ordered[1:]:
        if s <= out[-1][1]:                 # overlaps or touches the last interval
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def divergence_spans(texts: list[str]) -> list[list[list[int]]]:
    """N-way generalisation of `diff_spans` with a single "they don't all agree
    here" flag per text.

    Returns one span list per input text (same order). A char range is
    highlighted in text i when it differs from AT LEAST ONE other text -- i.e. it
    is NOT identical across every column. This is deliberately symmetric and
    baseline-free: if two texts agree but a third differs, the shared content is
    still flagged in all three, because at that locus the pipelines disagree.

    Why union-of-pairwise instead of a true multi-sequence alignment: MSA is a
    much heavier algorithm, and for the handful of pipelines a user lines up the
    O(N^2) pairwise passes are cheap and let us reuse the exact word-level,
    whitespace-insensitive `diff_spans` machinery the 2-way view already trusts.
    """
    n = len(texts)
    acc: list[list[list[int]]] = [[] for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            d = diff_spans(texts[i], texts[j])
            acc[i].extend(d["a"])           # spans of i that differ from j
            acc[j].extend(d["b"])           # spans of j that differ from i
    return [_merge_spans(s) for s in acc]
