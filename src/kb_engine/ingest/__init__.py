"""kb_engine.ingest — generic ingest seam (plan §6.1, Build-3).

``SourceAdapter`` (adapters.py) -> ``Mapper`` (mappers.py) ->
``DedupePolicy`` (dedupe.py) -> ``IngestPipeline`` (pipeline.py), plus the
closed registry of pure parametric transforms (transforms.py).
"""

from kb_engine.ingest.adapters import ADAPTERS, AdapterError, IgSavedAdapter, make_adapter
from kb_engine.ingest.dedupe import DedupeError, RecordDedupe
from kb_engine.ingest.mappers import (
    EnvelopeFailure,
    MappingError,
    RecordMapper,
    content_hash,
)
from kb_engine.ingest.pipeline import (
    Gap,
    IngestPipeline,
    IngestResult,
    PipelineError,
)
from kb_engine.ingest.transforms import (
    TRANSFORMS,
    TransformError,
    apply_transform,
    registered_transforms,
)

__all__ = [
    "ADAPTERS",
    "AdapterError",
    "EnvelopeFailure",
    "Gap",
    "IgSavedAdapter",
    "IngestPipeline",
    "IngestResult",
    "MappingError",
    "PipelineError",
    "RecordDedupe",
    "RecordMapper",
    "TRANSFORMS",
    "TransformError",
    "apply_transform",
    "content_hash",
    "ingest",
    "make_adapter",
    "registered_transforms",
]
