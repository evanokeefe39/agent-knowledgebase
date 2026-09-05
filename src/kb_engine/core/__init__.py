"""kb_engine.core — thin typed contract scaffold (plan §7).

``records`` / ``provenance`` carry the universal envelope; ``contracts``
declares the strategy Protocols strategies register against. No corpus
semantics here, no wiring of the legacy ``kb/`` code.
"""

from kb_engine.core.contracts import RankedHit
from kb_engine.core.provenance import Provenance
from kb_engine.core.records import CanonicalRecord

__all__ = ["CanonicalRecord", "Provenance", "RankedHit"]
