import types

from alchemy.render import render_report


def _sr(**kw):
    base = dict(key="k", title="", content="", filled=False, note="")
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_render_titled_report():
    out = render_report("Vuln report", [
        _sr(key="summary", title="Summary", content="All clear.", filled=True),
        _sr(key="june", title="June incidents", content="Two found.", filled=True),
    ])
    assert out.startswith("# Vuln report\n")
    assert "## Summary\n\nAll clear." in out
    assert "## June incidents\n\nTwo found." in out
    assert out.index("Summary") < out.index("June incidents")


def test_render_untitled_report_has_no_h1():
    out = render_report("", [_sr(key="a", title="A", content="x", filled=True)])
    assert not out.startswith("# ")
    assert "## A" in out


def test_render_unfilled_section_states_shortfall():
    out = render_report("T", [
        _sr(key="a", title="A", content="done", filled=True),
        _sr(key="b", title="B", note="skipped: llm call cap"),
    ])
    assert "## B\n\n_(not filled: skipped: llm call cap)_" in out


def test_render_untitled_section_uses_key_as_heading():
    out = render_report("", [_sr(key="body", content="c", filled=True)])
    assert "## body" in out
