from __future__ import annotations

import difflib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from importlib import import_module
from importlib.metadata import entry_points

from pydantic import ValidationError

from madosho.core.errors import (
    ConfigError, MissingDependencyError, UnknownComponentError,
)
from madosho.core.hooks import Hook, ResolutionContext, load_hooks, run_hooks
from madosho.core.meta import ComponentKind
from madosho.core.protocols import RuntimeContext

COMPONENT_GROUP = "madosho.components"


@dataclass(frozen=True)
class ComponentSpec:
    kind: ComponentKind
    name: str
    target: str                 # "module.path:ClassName", imported lazily
    install_extra: str | None   # madosho extra providing the deps, if any
    # Hard data-flow dependencies on OTHER slots, e.g. the docling-hybrid chunker
    # needs the docling parser's native object. Each entry is (slot_kind,
    # allowed_names): the chosen component in `slot_kind` must be one of
    # `allowed_names`, else the recipe cannot run. This is a structural
    # compatibility fact, NOT a curation/license gate -- ComponentMeta stays the
    # "never a gate" informational card; correctness constraints live here.
    # Tuple-of-tuples (not a dict) so the frozen spec stays hashable.
    requires: tuple[tuple[str, tuple[str, ...]], ...] = ()
    # Resolvable by name but omitted from user-facing menus (e.g. the testing
    # fakes: they exist so docs/examples/tests run without heavy extras, but must
    # never appear as a real choice in the pipeline builder). list_components()
    # filters these out; resolution by name still works.
    hidden: bool = False


# First-party components. Targets are filled in by later tasks; a spec whose
# module is absent only errors if a config names it.
BUILTINS: list[ComponentSpec] = [
    ComponentSpec(ComponentKind.OPERATOR, "keyword_search", "madosho.operators.keyword_search:KeywordSearch", None),
    ComponentSpec(ComponentKind.OPERATOR, "semantic_search", "madosho.operators.semantic_search:SemanticSearch", None),
    ComponentSpec(ComponentKind.OPERATOR, "fuse", "madosho.operators.fuse:Fuse", None),
    ComponentSpec(ComponentKind.OPERATOR, "rerank", "madosho.operators.rerank:Rerank", None),
    ComponentSpec(ComponentKind.OPERATOR, "chunk_read", "madosho.operators.chunk_read:ChunkRead", None),
    ComponentSpec(ComponentKind.PARSER, "docling", "madosho.adapters.docling.parser:DoclingParser", "docling"),
    ComponentSpec(ComponentKind.PARSER, "pypdfium2", "madosho.adapters.docling.fastlane:PyPdfiumParser", "docling"),
    ComponentSpec(ComponentKind.PARSER, "router", "madosho.adapters.docling.router:RouterParser", "docling"),
    # Vision parser: rasterizes pages and transcribes them with a vision LLM. Uses
    # pypdfium2 (the docling extra) for rendering + Pillow; the model is reached
    # through the injected runtime.vision seam, not a local install.
    ComponentSpec(ComponentKind.PARSER, "vision", "madosho.adapters.vision.parser:VisionParser", "docling"),
    ComponentSpec(ComponentKind.CHUNKER, "docling-hybrid", "madosho.adapters.docling.chunker:DoclingHybridChunker", "docling",
                  # Needs the docling parser's native DoclingDocument. `router` qualifies
                  # because it uses the docling structure lane by default (fast_lane=False);
                  # router+fast_lane can still drop the native, which the runtime raise guards.
                  requires=(("parser", ("docling", "router")),)),
    ComponentSpec(ComponentKind.CHUNKER, "recursive-text", "madosho.adapters.text.chunker:RecursiveTextChunker", None),
    ComponentSpec(ComponentKind.CHUNKER, "contextual", "madosho.adapters.text.contextual_chunker:ContextualChunker", None),
    ComponentSpec(ComponentKind.CHUNKER, "semantic", "madosho.adapters.text.semantic_chunker:SemanticChunker", None),
    ComponentSpec(ComponentKind.EMBEDDER, "granite-embedding-english-r2", "madosho.adapters.st_models.embedder:StEmbedder", "models"),
    ComponentSpec(ComponentKind.EMBEDDER, "all-minilm-l6-v2", "madosho.adapters.st_models.embedder:MiniLmEmbedder", "models"),
    ComponentSpec(ComponentKind.EMBEDDER, "multilingual-e5-large-instruct", "madosho.adapters.st_models.embedder:E5LargeInstructEmbedder", "models"),
    ComponentSpec(ComponentKind.EMBEDDER, "nomic-embed-text-v1.5", "madosho.adapters.st_models.embedder:NomicEmbedTextV15Embedder", "models"),
    # CN_OTH_SRC embedders (bge-base-en-v1.5, qwen3-embedding-0.6b) live in the
    # separate CN/other-source models bundle, discovered via entry points when installed.
    ComponentSpec(ComponentKind.RERANKER, "granite-reranker-english-r2", "madosho.adapters.st_models.reranker:StCrossEncoderReranker", "models"),
    ComponentSpec(ComponentKind.RERANKER, "ms-marco-minilm-l6-v2", "madosho.adapters.st_models.reranker:MsMarcoMiniLmReranker", "models"),
    # CN_OTH_SRC rerankers (bge-reranker-v2-m3, bge-reranker-base) live in the
    # separate CN/other-source models bundle, discovered via entry points when installed.
    ComponentSpec(ComponentKind.RERANKER, "mxbai-rerank-base-v1", "madosho.adapters.st_models.reranker:MxbaiRerankBaseV1Reranker", "models"),
    ComponentSpec(ComponentKind.STORE, "lancedb", "madosho.adapters.lancedb.store:LanceDBStore", "lancedb"),
    ComponentSpec(ComponentKind.STORE, "qdrant", "madosho.adapters.qdrant.store:QdrantStore", "qdrant"),
    # testing fakes are resolvable by name so docs/examples can run without extras,
    # but hidden=True keeps them out of the user-facing pipeline builder menus.
    ComponentSpec(ComponentKind.PARSER, "fake-parser", "madosho.testing.fakes:FakeParser", None, hidden=True),
    ComponentSpec(ComponentKind.CHUNKER, "fake-chunker", "madosho.testing.fakes:FakeChunker", None, hidden=True),
    ComponentSpec(ComponentKind.EMBEDDER, "hash-embedder", "madosho.testing.fakes:HashEmbedder", None, hidden=True),
    ComponentSpec(ComponentKind.STORE, "fake-store", "madosho.testing.fakes:FakeStore", None, hidden=True),
    ComponentSpec(ComponentKind.RERANKER, "fake-reranker", "madosho.testing.fakes:FakeReranker", None, hidden=True),
]


def requirement_errors(selected: Mapping[str, str | None],
                       specs: Iterable[ComponentSpec] = BUILTINS) -> dict[str, str]:
    """Hard compatibility check for a recipe. `selected` maps a slot kind
    ('parser', 'chunker', 'embedder', ...) to the chosen component name. Returns
    {slot_kind: message} for every chosen component whose declared `requires`
    are not met by the other slots; an empty dict means the recipe is valid.

    The error is keyed by the REQUIRING slot (the component that owns the
    dependency), so the UI can flag exactly that box. This is a data-flow
    constraint, never a license/curation gate."""
    by_name = {(s.kind.value, s.name): s for s in specs}
    errors: dict[str, str] = {}
    for slot, name in selected.items():
        if not name:
            continue
        spec = by_name.get((slot, name))
        if spec is None:
            continue                    # plugin/unknown component: nothing to enforce
        for req_slot, allowed in spec.requires:
            if selected.get(req_slot) not in allowed:
                have = selected.get(req_slot)
                allowed_str = " or ".join(allowed)
                errors[slot] = (f"needs {req_slot} = {allowed_str}"
                                + (f" (have: {have})" if have else ""))
    return errors


class Registry:
    def __init__(self, specs: list[ComponentSpec] | None = None,
                 hooks: list[Hook] | None = None):
        self._specs: dict[tuple[ComponentKind, str], ComponentSpec] = {
            (s.kind, s.name): s for s in (BUILTINS if specs is None else specs)}
        self.hooks: list[Hook] = load_hooks() if hooks is None else hooks

    def discover_entry_points(self) -> None:
        for ep in entry_points(group=COMPONENT_GROUP):
            kind_str, _, name = ep.name.partition(".")
            try:
                kind = ComponentKind(kind_str)
            except ValueError:
                continue  # not ours to police; ignore malformed names
            if not name:
                continue  # malformed "<kind>." entry point
            self._specs.setdefault((kind, name), ComponentSpec(
                kind=kind, name=name, target=ep.value, install_extra=None))

    def names(self, kind: ComponentKind) -> list[str]:
        return sorted(n for k, n in self._specs if k == kind)

    def spec(self, kind: ComponentKind, name: str) -> ComponentSpec:
        try:
            return self._specs[(kind, name)]
        except KeyError:
            close = difflib.get_close_matches(name, self.names(kind), n=3)
            hint = f" Did you mean: {', '.join(close)}?" if close else ""
            raise UnknownComponentError(
                f"unknown {kind.value} '{name}'."
                f"{hint} Installed {kind.value}s: {', '.join(self.names(kind))}") from None

    def load_class(self, kind: ComponentKind, name: str) -> type:
        spec = self.spec(kind, name)
        module_path, _, cls_name = spec.target.partition(":")
        try:
            module = import_module(module_path)
        except ImportError as e:
            fix = (f'pip install "madosho[{spec.install_extra}]"' if spec.install_extra
                   else f"reinstall the package providing '{name}'")
            raise MissingDependencyError(
                f"{kind.value} '{name}' is registered but its dependencies are "
                f"missing ({e}). Fix: {fix}") from e
        try:
            return getattr(module, cls_name)
        except AttributeError:
            raise ConfigError(
                f"{kind.value} '{name}' has a broken target '{spec.target}': "
                f"module '{module_path}' has no attribute '{cls_name}'") from None

    def resolve(self, kind: ComponentKind, name: str, options: dict,
                runtime: RuntimeContext, ctx: ResolutionContext):
        # NOTE: importing the module (load_class) necessarily precedes the hook
        # gate — META lives on the class, so hooks cannot see metadata without
        # the import. Hooks gate instantiation/use, not import side effects.
        cls = self.load_class(kind, name)
        meta = getattr(cls, "META", None)
        opts_model = getattr(cls, "Options", None)
        if meta is None or opts_model is None:
            raise ConfigError(
                f"{kind.value} '{name}' ({cls.__module__}.{cls.__qualname__}) is "
                f"malformed: components must define META and a nested Options model")
        run_hooks(self.hooks, meta, ctx, runtime.logger)
        # pydantic v2 silently ignores unknown keys by default; a typo'd option
        # must be a config error (spec §10 fail-fast), so check explicitly.
        # The allowed-key set includes validation aliases, and a component may
        # opt out of the check entirely with model_config extra="allow".
        if opts_model.model_config.get("extra") != "allow":
            allowed = set()
            for fname, f in opts_model.model_fields.items():
                allowed.add(fname)
                if isinstance(f.alias, str):
                    allowed.add(f.alias)
                if isinstance(f.validation_alias, str):
                    allowed.add(f.validation_alias)
            unknown = set(options) - allowed
            if unknown:
                raise ConfigError(
                    f"unknown option(s) for {kind.value} '{name}': {sorted(unknown)}. "
                    f"Valid options: {sorted(allowed)}")
        try:
            opts = opts_model(**options)
        except ValidationError as e:
            raise ConfigError(f"invalid options for {kind.value} '{name}': {e}") from e
        return cls(options=opts, runtime=runtime)
