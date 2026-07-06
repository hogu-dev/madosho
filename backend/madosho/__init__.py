from madosho.core.corpus import (  # noqa: A001 - deliberate builtin shadow, spec §8
    Corpus, open_corpus as open, open_corpus_from_config,
)

__version__ = "0.1.0"
__all__ = ["open", "open_corpus_from_config", "Corpus", "__version__"]
