"""Source adapters (plan §6.1): the sole OCP extension point for novel
formats. Adapters do IO and yield raw items in a declared shape; they never
run core logic. Bespoke derivation that is not expressible as a pure
transform primitive lives here (plan §12).

``ig_saved`` reads a scrape-repo-style dir tree::

    <location>/<dataset>/<post_dir>/post_metadata.json   (+ analysis.json,
                                                          + media files)

and yields raw items shaped exactly like the ``corpora/uiux.yaml`` mapping
``from`` paths::

    {"metadata": {...}, "analysis": {...}, "media": [...],
     "resources": [...], "resources_text": "name — purpose\n...",
     "dataset_post_dir": "<snapshot>/<dataset>/<post_dir>",
     "extraction_status": "ok" | "pending"}

``resources`` / ``resources_text`` are adapter-stamped (declared passthrough +
search fields with no mapping entry) only when ``analysis.resources`` exists.

``dataset_post_dir`` is the ``media_ref`` pointer (only stamped when media
bytes exist); ``extraction_status`` is presence-derived (analysis.json
present and non-empty -> ``ok``, else ``pending``) — bespoke, hence in the
adapter. Location always comes from config; nothing is hardcoded.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from kb_engine.config import SourceSpec

__all__ = ["AdapterError", "IgSavedAdapter", "ADAPTERS", "make_adapter"]


class AdapterError(RuntimeError):
    """The adapter cannot read its declared location / an item is malformed."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise AdapterError(f"cannot read {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise AdapterError(f"{path} must contain a JSON object")
    return payload

def normalize_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize an ``analysis.json`` payload to the flat shape the corpus
    mapping declares (``analysis.summary`` etc.).

    Schema-v2 scrape files nest the enrichment under a top-level
    ``analysis`` object; the flat shape is the declared raw-item contract,
    so the adapter unwraps it, carrying any top-level sibling keys
    (``analysed_at``, ``schema_version``, ...) that the inner object does
    not already define. Flat payloads (v1) pass through unchanged.
    """
    inner = payload.get("analysis")
    if not isinstance(inner, dict):
        return payload
    normalized = dict(inner)
    for key, value in payload.items():
        if key != "analysis" and key not in normalized:
            normalized[key] = value
    return normalized


def flatten_concepts(concepts: Any) -> Any:
    """Flatten ``{term, explanation}`` concept objects to searchable text
    entries (``"term: explanation"``), the representation the previous
    engine indexed. String entries and other values pass through.
    """
    if not isinstance(concepts, list):
        return concepts
    flat: list[Any] = []
    for entry in concepts:
        if (
            isinstance(entry, dict)
            and isinstance(entry.get("term"), str)
            and isinstance(entry.get("explanation"), str)
        ):
            flat.append(f"{entry['term']}: {entry['explanation']}")
        else:
            flat.append(entry)
    return flat


def flatten_resources(resources: Any) -> str | None:
    """Flatten ``{name, purpose, ...}`` resource objects to one searchable
    text blob (``"name — purpose"`` per line), the representation the
    previous engine indexed. Non-dict entries contribute nothing; returns
    ``None`` when nothing flattens (absence, not empty string).
    """
    if not isinstance(resources, list):
        return None
    lines: list[str] = []
    for entry in resources:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") or ""
        purpose = entry.get("purpose") or ""
        if name or purpose:
            lines.append(f"{name} — {purpose}".strip(" —"))
    return "\n".join(lines) if lines else None



class IgSavedAdapter:
    """Reads ``<location>/<dataset>/<post_dir>/`` trees into raw items."""

    def __init__(self, spec: SourceSpec) -> None:
        if spec.location is None:
            raise AdapterError(
                f"source '{spec.name}': ig_saved requires a declared location"
            )
        self.location = Path(spec.location)
        self.snapshot = spec.snapshot or ""
        if not self.location.is_dir():
            raise AdapterError(
                f"source '{spec.name}': location does not exist: {self.location}"
            )

    def load(self) -> Iterator[dict[str, Any]]:
        for dataset_dir in sorted(p for p in self.location.iterdir() if p.is_dir()):
            for post_dir in sorted(p for p in dataset_dir.iterdir() if p.is_dir()):
                metadata_path = post_dir / "post_metadata.json"
                if not metadata_path.is_file():
                    continue  # not a scraped post dir
                analysis_path = post_dir / "analysis.json"
                analysis: dict[str, Any] = {}
                if analysis_path.is_file():
                    analysis = normalize_analysis(_read_json(analysis_path))
                media = sorted(
                    p.name
                    for p in post_dir.iterdir()
                    if p.is_file() and p.suffix.lower() != ".json"
                )
                ref = (
                    f"{self.snapshot}/{dataset_dir.name}/{post_dir.name}"
                    if media
                    else ""
                )
                item = {
                    "metadata": _read_json(metadata_path),
                    "analysis": analysis,
                    "media": media,
                    "dataset_post_dir": ref,
                    "extraction_status": "ok" if analysis else "pending",
                }
                if "concepts" in analysis:
                    item["analysis"] = {
                        **analysis,
                        "concepts": flatten_concepts(analysis["concepts"]),
                    }
                # `resources` is a passthrough field with no mapping entry:
                # the adapter stamps the verbatim objects plus the flattened
                # search text (declared field `resources_text`) the mapper
                # resolves as adapter-provided top-level keys.
                resources = analysis.get("resources")
                if isinstance(resources, list):
                    item["resources"] = resources
                    item["resources_text"] = flatten_resources(resources)
                yield item


ADAPTERS: dict[str, Callable[[SourceSpec], Any]] = {
    "ig_saved": IgSavedAdapter,
}


def make_adapter(
    spec: SourceSpec,
    registry: Mapping[str, Callable[[SourceSpec], Any]] | None = None,
) -> Any:
    """Build the declared source's adapter from the registry (fail fast on
    an unregistered id)."""
    reg = registry if registry is not None else ADAPTERS
    factory = reg.get(spec.adapter or "")
    if factory is None:
        raise AdapterError(
            f"source '{spec.name}': unknown adapter id {spec.adapter!r}"
        )
    return factory(spec)
