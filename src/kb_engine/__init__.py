"""kb_engine — generic, declarative, multi-corpus knowledge-base engine.

Core code contains zero reference to any particular corpus's semantics
(docs/productization-plan.md §1/§7). Corpus specifics live in declared
config: ``config.yaml`` (engine/runtime) + ``corpora/<name>.yaml``
(per-corpus data contract), loaded by :mod:`kb_engine.config`.
"""

from kb_engine.config import Config, ConfigError, CorpusConfig, load

__all__ = ["Config", "ConfigError", "CorpusConfig", "load"]
