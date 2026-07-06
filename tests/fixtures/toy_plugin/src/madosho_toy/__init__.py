"""Minimal third-party adapter: proves entry-point discovery with no core changes."""
import hashlib

from pydantic import BaseModel

from madosho.core.meta import ComponentKind, ComponentMeta, Hardware, OriginTier
from madosho.core.protocols import ComponentBase
from madosho.core.types import Block, BlockKind, Document, Provenance, SourceFile


class ToyParser(ComponentBase):
    META = ComponentMeta(name="toy", kind=ComponentKind.PARSER, version="0.1.0",
                         license="MIT", org="toyco", org_country="US",
                         origin_tier=OriginTier.US_SRC, hardware=Hardware.CPU)

    class Options(BaseModel):
        pass

    def __init__(self, options=None, runtime=None):
        self.options = options or self.Options()
        self.runtime = runtime

    def supports(self, file: SourceFile) -> bool:
        return file.path.endswith(".toy")

    def parse(self, file: SourceFile) -> Document:
        prov = Provenance(source=file.path, page=1)
        return Document(doc_id=hashlib.sha256(file.path.encode()).hexdigest()[:16],
                        source=file,
                        blocks=[Block(kind=BlockKind.TEXT, content="toy content",
                                      provenance=prov)])
