"""Kernel emits ingest progress through an optional reporter (service injects a
DB-writing one; library/CLI ingest stays silent via the no-op default)."""
import hashlib

from madosho.core.config import MadoshoConfig
from madosho.core.corpus import open_corpus_from_config
from madosho.core.types import SourceFile


class RecordingReporter:
    def __init__(self):
        self.phases: list[str] = []
        self.logs: list[str] = []

    def phase(self, name: str) -> None:
        self.phases.append(name)

    def log(self, message: str) -> None:
        self.logs.append(message)


def _corpus(tmp_path):
    cfg = MadoshoConfig(
        corpus="demo",
        ingest={"parser": "fake-parser", "chunker": "fake-chunker",
                "embedder": "hash-embedder", "store": "fake-store",
                "indexes": ["bm25", "dense"]},
        query=[{"keyword_search": {"k": 10}}, {"fuse": {"method": "rrf"}}],
    )
    return open_corpus_from_config(cfg, data_dir=tmp_path / "state")


def _sourcefile(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("alpha beta gamma\n\ndelta epsilon")
    return SourceFile(path=str(f), mimetype="text/plain",
                      content_hash=hashlib.sha256(f.read_bytes()).hexdigest())


def test_ingest_file_reports_phases_in_pipeline_order(tmp_path):
    reporter = RecordingReporter()
    _corpus(tmp_path).ingest_file(_sourcefile(tmp_path), reporter=reporter)
    # the seams the UI shows, in the order the pipeline crosses them
    assert reporter.phases == ["parsing", "chunking", "embedding", "storing"]


def test_index_document_phases_skip_parsing(tmp_path):
    corpus = _corpus(tmp_path)
    doc = corpus.parse_file(_sourcefile(tmp_path))   # already parsed (F trunk reuse)
    reporter = RecordingReporter()
    corpus.index_document(doc, reporter=reporter)
    assert reporter.phases == ["chunking", "embedding", "storing"]


def test_ingest_file_without_reporter_is_a_silent_noop(tmp_path):
    # the default path (library/CLI) must work unchanged with no reporter
    artifacts = _corpus(tmp_path).ingest_file(_sourcefile(tmp_path))
    assert len(artifacts.chunks) == 2
