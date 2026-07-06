"""Loads the shipped default autonomous.md (the editable, declarative behaviour file).
Behaviour-as-data: a consumer can override it per run without touching code."""
from __future__ import annotations

import pathlib

_AUTONOMOUS_MD = pathlib.Path(__file__).parent / "autonomous.md"


def load_default_autonomous_md() -> str:
    return _AUTONOMOUS_MD.read_text(encoding="utf-8")
