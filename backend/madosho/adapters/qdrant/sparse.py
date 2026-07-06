"""Minimal BM25 sparse encoding for Qdrant's IDF-modified sparse index.

Documents carry the BM25 term-frequency component; the server's Modifier.IDF
supplies the IDF half at query time, so queries are flat 1.0 per unique token.
Token -> dimension index is crc32: stable across processes, 32-bit collisions
are an accepted BM25 trade-off (fastembed's Qdrant/bm25 does the same with
mmh3). Stdlib-only on purpose — keeps the qdrant extra to qdrant-client alone.
"""
from __future__ import annotations

import re
import zlib
from collections import Counter

_TOKEN = re.compile(r"[a-z0-9]+")

K1 = 1.2        # BM25 term-frequency saturation
B = 0.75        # BM25 length normalization
AVG_LEN = 256.0  # assumed average chunk length in tokens (fastembed default)


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def _index(token: str) -> int:
    return zlib.crc32(token.encode("utf-8"))


def encode_document(text: str) -> tuple[list[int], list[float]]:
    toks = _tokens(text)
    if not toks:
        return [], []
    tf_by_index: dict[int, int] = Counter()
    for tok, tf in Counter(toks).items():
        tf_by_index[_index(tok)] += tf   # crc32 collisions merge by summing tf
    norm = K1 * (1 - B + B * len(toks) / AVG_LEN)
    indices = sorted(tf_by_index)
    values = [tf_by_index[i] * (K1 + 1) / (tf_by_index[i] + norm) for i in indices]
    return indices, values


def encode_query(text: str) -> tuple[list[int], list[float]]:
    indices = sorted({_index(t) for t in _tokens(text)})
    return indices, [1.0] * len(indices)
