from __future__ import annotations

import argparse
import sys

import madosho
from madosho.core.errors import MadoshoError
from madosho.core.meta import ComponentKind
from madosho.core.registry import Registry


def _cmd_ingest(args) -> int:
    report = madosho.open(args.config).ingest()
    print(f"processed: {report.processed}  skipped: {report.skipped}  "
          f"failed: {report.failed}  ({report.seconds:.1f}s)")
    for err in report.errors:
        print(f"  FAILED {err.path}: {err.error}")
    return 0   # fail-soft (spec §10): per-file errors are reported, not fatal


def _cmd_query(args) -> int:
    hits = madosho.open(args.config).query(args.text)
    for i, h in enumerate(hits, 1):
        print(f"[{i}] {h.citation}  (score {h.score:.3f}, via {h.source_index})")
        print(f"    {h.text}\n")
    return 0


def _cmd_components_list(args) -> int:
    registry = Registry()
    registry.discover_entry_points()
    show_hidden = getattr(args, "all", False)
    rows = []
    for kind in ComponentKind:
        for name in registry.names(kind):
            # Hidden specs are the in-memory testing fakes: resolvable by name so
            # examples/tests run without extras, but never a real user choice. The
            # web /components form filters them the same way (madosho_server
            # components.py); --all surfaces them for debugging.
            if not show_hidden and registry.spec(kind, name).hidden:
                continue
            try:
                meta = registry.load_class(kind, name).META
                rows.append((kind.value, name, meta.license, meta.org,
                             meta.origin_tier.value, meta.hardware.value,
                             meta.install_extra or "-"))
            except MadoshoError:
                rows.append((kind.value, name, "?", "?", "?", "?", "not installed"))
    widths = [max(len(r[i]) for r in rows + [_HEADER]) for i in range(len(_HEADER))]
    for row in [_HEADER] + rows:
        print("  ".join(cell.ljust(w) for cell, w in zip(row, widths)))
    return 0


_HEADER = ("kind", "name", "license", "org", "origin", "hardware", "extra")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="madosho",
                                     description="Composable RAG pipelines")
    parser.add_argument("--config", default="madosho.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ingest", help="ingest the corpus source folder")
    q = sub.add_parser("query", help="query the corpus")
    q.add_argument("text")
    comp = sub.add_parser("components", help="inspect installed components")
    comp_sub = comp.add_subparsers(dest="subcommand", required=True)
    comp_list = comp_sub.add_parser("list", help="list components with license/origin columns")
    comp_list.add_argument("--all", action="store_true",
                           help="include hidden testing fakes (fake-*, hash-embedder)")

    args = parser.parse_args(argv)
    try:
        if args.command == "ingest":
            return _cmd_ingest(args)
        if args.command == "query":
            return _cmd_query(args)
        if args.command == "components":
            return _cmd_components_list(args)
    except MadoshoError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
