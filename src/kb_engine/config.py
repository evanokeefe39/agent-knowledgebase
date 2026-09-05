"""Config loader + validation (fail fast).

Reads the engine ``config.yaml`` (repo root) and every
``corpora/<name>.yaml`` (per-corpus data contract) under
``engine.corpora_dir``, returning typed models.

Enforced contract (docs/productization-plan.md §6.6, §7; Build-1):
  * every corpus declares ``schema.schema_version`` (string);
  * field types come from the locked type vocabulary;
  * field roles come from the locked role vocabulary;
  * type x role compatibility is enforced at load time (fail fast);
  * ``id_field`` resolves to a declared schema field;
  * every source carries the provenance envelope block
    (``source`` / ``media_ref`` / ``timestamp_field``);
  * adapter / transform ids validate against registered sets (only when
    declared);
  * ``${VAR}`` expansion + paths relative to the declaring file;
  * multi-corpus isolation: corpora load independently; a broken corpus is
    reported per-corpus and never prevents the others from loading.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field as dc_field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

import yaml

# ---- Locked vocabularies (docs/productization-plan.md §6.6) -----------------

VALID_TYPES: frozenset[str] = frozenset(
    {
        "text",
        "string",
        "list[text]",
        "list[string]",
        "int",
        "float",
        "bool",
        "datetime",
        "date",
        "url",
        "object",
        "list[object]",
    }
)

VALID_ROLES: frozenset[str] = frozenset(
    {"search", "filter", "facet", "metric", "sort", "passthrough"}
)

METRIC_TYPES: frozenset[str] = frozenset({"int", "float"})
PASSTHROUGH_TYPES: frozenset[str] = frozenset({"object", "list[object]"})

# Registered strategy ids (§12: registered pure primitives only; bespoke
# logic belongs in the per-source adapter, never in these registries).
REGISTERED_ADAPTERS: frozenset[str] = frozenset({"ig_saved", "csv"})
REGISTERED_TRANSFORMS: frozenset[str] = frozenset(
    {
        "identity",
        "coerce_str",
        "coerce_int",
        "coerce_bool",
        "coerce_float",
        "list",
        "template",
        "path_join",
    }
)

_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(Exception):
    """Base error for config loading with file + field + problem context."""


class CorpusConfigError(ConfigError):
    """One corpus declaration failed validation."""

    def __init__(self, corpus: str, path: str, message: str) -> None:
        self.corpus = corpus
        self.path = path
        self.message = message
        super().__init__(f"corpus '{corpus}' ({path}): {message}")


# ---- Path handling ----------------------------------------------------------


def expand_vars(value: str) -> str:
    """Expand ``${VAR}`` from the environment.

    An unset variable is left verbatim (validation of a source location that
    points at a machine-specific export root must not fail a config parse).
    """
    return _VAR_RE.sub(lambda m: os.environ.get(m.group(1), m.group(0)), value)


def resolve_path(value: Any, base_dir: Path) -> Path:
    """Resolve a declared path: ``${VAR}`` expansion, then relative to the
    directory of the file that declared it."""
    if not isinstance(value, str) or not value:
        return Path(value)  # non-path scalar; caller decides
    expanded = expand_vars(value)
    p = Path(expanded)
    return p if p.is_absolute() else (base_dir / p).resolve()


# ---- Corpus models ----------------------------------------------------------


@dataclass(frozen=True)
class FieldSpec:
    name: str
    type: str
    roles: tuple[str, ...] = ()
    weight: float | None = None
    example: Any = None


@dataclass(frozen=True)
class ProvenanceSpec:
    """Envelope contract: where provenance (source, media_ref, timestamp)
    comes from for a source's records."""

    source: str
    media_ref: str
    timestamp_field: str
    extractor_field: str | None = None
    confidence_field: str | None = None


@dataclass(frozen=True)
class SourceSpec:
    name: str
    adapter: str | None
    location: Path | None
    snapshot: str | None
    mapping: Mapping[str, Any]
    provenance: ProvenanceSpec
    dedupe: Mapping[str, Any]
    missing: Mapping[str, Any]


@dataclass(frozen=True)
class CorpusConfig:
    """A validated per-corpus data contract (``corpora/<name>.yaml``)."""

    name: str
    path: Path
    schema_version: str
    id_field: str
    refresh_hash_fields: tuple[str, ...]
    fields: dict[str, FieldSpec]
    sources: tuple[SourceSpec, ...]
    raw: Mapping[str, Any]  # untouched declaration (index/materialize/verify/serve)

    def field(self, name: str) -> FieldSpec | None:
        return self.fields.get(name)


@dataclass(frozen=True)
class Config:
    """Validated engine/runtime config + all loadable corpora."""

    path: Path
    artifacts_dir: Path
    user_data_dir: Path
    corpora_dir: Path
    default_corpus: str | None
    embedding: Mapping[str, Any]
    verify: Mapping[str, Any]
    corpora: dict[str, CorpusConfig]
    # Per-corpus load errors (multi-corpus isolation): corpus name -> message.
    # Valid corpora are still loaded alongside broken ones.
    errors: dict[str, str]

    def corpus(self, name: str) -> CorpusConfig | None:
        return self.corpora.get(name)


# ---- Corpus validation ------------------------------------------------------


def _fail(corpus: str, path: Path, message: str) -> None:
    raise CorpusConfigError(corpus, str(path), message)


def _validate_field(
    corpus: str, path: Path, name: str, spec: Any
) -> FieldSpec:
    def err(problem: str) -> None:
        _fail(corpus, path, f"field '{name}': {problem}")

    if not isinstance(spec, Mapping):
        err(f"expected a mapping of field attributes, got {type(spec).__name__}")
    ftype = spec.get("type")
    if not isinstance(ftype, str) or ftype not in VALID_TYPES:
        err(
            f"unknown type {ftype!r}; must be one of: "
            + ", ".join(sorted(VALID_TYPES))
        )
    roles_raw = spec.get("role", [])
    if isinstance(roles_raw, str):
        roles_raw = [roles_raw]
    if not isinstance(roles_raw, list):
        err("'role' must be a role string or a list of role strings")
    roles: list[str] = []
    for role in roles_raw:
        if not isinstance(role, str) or role not in VALID_ROLES:
            err(
                f"unknown role {role!r}; must be a subset of: "
                + ", ".join(sorted(VALID_ROLES))
            )
        if role not in roles:
            roles.append(role)
    # Type x role compatibility matrix (fail fast at load).
    if ftype in PASSTHROUGH_TYPES:
        if set(roles) != {"passthrough"}:
            err(
                f"type '{ftype}' is only compatible with role 'passthrough' "
                f"(got: {roles or 'no role'})"
            )
    if "metric" in roles and ftype not in METRIC_TYPES:
        err(f"role 'metric' requires type int or float (got: '{ftype}')")
    if "passthrough" in roles and ftype not in PASSTHROUGH_TYPES:
        err(f"role 'passthrough' requires type object or list[object] (got: '{ftype}')")
    weight = spec.get("weight")
    if weight is not None:
        if "search" not in roles:
            err("'weight' is only valid on role 'search' fields")
        if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight <= 0:
            err(f"'weight' must be a positive number (got: {weight!r})")
    # datetime/date parse validation when an example value is present.
    example = spec.get("example")
    if example is not None and ftype in ("datetime", "date"):
        try:
            datetime.fromisoformat(str(example))
        except ValueError:
            err(f"'example' {example!r} is not a valid ISO-8601 {ftype}")
    return FieldSpec(
        name=name,
        type=ftype,
        roles=tuple(roles),
        weight=weight,
        example=example,
    )


def _validate_transform(
    corpus: str, path: Path, field_name: str, transform: str
) -> None:
    if transform not in REGISTERED_TRANSFORMS:
        _fail(
            corpus,
            path,
            f"field '{field_name}': unknown transform '{transform}'; "
            "must be one of the registered primitives: "
            + ", ".join(sorted(REGISTERED_TRANSFORMS))
            + " (bespoke transforms belong in the per-source adapter)",
        )


def _validate_source(
    corpus: str, path: Path, schema_fields: Mapping[str, Any], raw: Any, idx: int
) -> SourceSpec:
    def err(problem: str) -> None:
        _fail(corpus, path, f"sources[{idx}] '{raw.get('name', idx)}': {problem}")

    if not isinstance(raw, Mapping):
        err(f"expected a mapping, got {type(raw).__name__}")
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        err("'name' must be a non-empty string")

    adapter = raw.get("adapter")
    if adapter is not None and adapter not in REGISTERED_ADAPTERS:
        err(
            f"unknown adapter '{adapter}'; must be one of: "
            + ", ".join(sorted(REGISTERED_ADAPTERS))
        )

    mapping = raw.get("mapping") or {}
    if not isinstance(mapping, Mapping):
        err("'mapping' must be a mapping of schema fields to {from, transform}")
    for target, m in mapping.items():
        if target not in schema_fields:
            err(
                f"mapping target '{target}' is not a declared schema field "
                "(mapping targets are schema fields or envelope slots)"
            )
        if isinstance(m, Mapping) and "transform" in m:
            _validate_transform(corpus, path, target, m["transform"])

    prov_raw = raw.get("provenance")
    if not isinstance(prov_raw, Mapping):
        err("missing 'provenance' block (envelope contract requires "
            "source / media_ref / timestamp_field)")
    for required in ("source", "media_ref", "timestamp_field"):
        if not prov_raw.get(required):
            err(f"'provenance.{required}' is required by the envelope contract")
    provenance = ProvenanceSpec(
        source=str(prov_raw["source"]),
        media_ref=str(prov_raw["media_ref"]),
        timestamp_field=str(prov_raw["timestamp_field"]),
        extractor_field=prov_raw.get("extractor_field"),
        confidence_field=prov_raw.get("confidence_field"),
    )

    location = raw.get("location")
    return SourceSpec(
        name=name,
        adapter=adapter,
        location=resolve_path(location, path.parent.parent) if location else None,
        snapshot=raw.get("snapshot"),
        mapping=dict(mapping),
        provenance=provenance,
        dedupe=raw.get("dedupe") or {},
        missing=raw.get("missing") or {},
    )


def _parse_corpus(name: str, path: Path, raw: Any) -> CorpusConfig:
    def err(problem: str) -> None:
        _fail(name, path, problem)

    if not isinstance(raw, Mapping):
        err(f"expected a top-level mapping, got {type(raw).__name__}")
    schema = raw.get("schema")
    if not isinstance(schema, Mapping):
        err("missing 'schema' block")
    schema_version = schema.get("schema_version")
    if not isinstance(schema_version, str) or not schema_version:
        err("'schema.schema_version' must be a non-empty string")
    fields_raw = schema.get("fields")
    if not isinstance(fields_raw, Mapping) or not fields_raw:
        err("'schema.fields' must be a non-empty mapping")

    fields: dict[str, FieldSpec] = {}
    for fname, fspec in fields_raw.items():
        fs = _validate_field(name, path, fname, fspec)
        fields[fname] = fs

    id_field = schema.get("id_field")
    if not isinstance(id_field, str) or not id_field:
        err("'schema.id_field' must be a non-empty string")
    if id_field not in fields:
        err(
            f"'schema.id_field' '{id_field}' does not resolve to a declared "
            "schema field"
        )

    refresh = schema.get("refresh_hash_fields") or []
    if not isinstance(refresh, list):
        err("'schema.refresh_hash_fields' must be a list of field names")
    for rf in refresh:
        if rf not in fields:
            err(f"'schema.refresh_hash_fields' entry '{rf}' is not a declared field")

    sources_raw = raw.get("sources") or []
    if not isinstance(sources_raw, list):
        err("'sources' must be a list of source declarations")
    sources = tuple(
        _validate_source(name, path, fields, s, i) for i, s in enumerate(sources_raw)
    )

    return CorpusConfig(
        name=name,
        path=path,
        schema_version=schema_version,
        id_field=id_field,
        refresh_hash_fields=tuple(refresh),
        fields=fields,
        sources=sources,
        raw=raw,
    )


# ---- Loader -----------------------------------------------------------------


def _load_yaml(path: Path) -> Any:
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc


def load(config_path: str | Path = "config.yaml") -> Config:
    """Load the engine config and every declared corpus.

    Multi-corpus isolation: each ``corpora/<name>.yaml`` is parsed and
    validated independently; a broken corpus is recorded in
    :attr:`Config.errors` (per-corpus) and does NOT prevent the remaining
    corpora from loading. Raises :class:`ConfigError` only when the engine
    ``config.yaml`` itself is unreadable/invalid.
    """
    path = Path(config_path).resolve()
    raw = _load_yaml(path)
    if not isinstance(raw, Mapping):
        raise ConfigError(f"{path}: expected a top-level mapping")
    engine = raw.get("engine")
    if not isinstance(engine, Mapping):
        raise ConfigError(f"{path}: missing 'engine' block")
    base_dir = path.parent

    corpora_dir = resolve_path(engine.get("corpora_dir", "corpora"), base_dir)
    artifacts_dir = resolve_path(engine.get("artifacts_dir", "artifacts"), base_dir)
    user_data_dir = resolve_path(engine.get("user_data_dir", "user_data"), base_dir)
    default_corpus = engine.get("default_corpus")

    corpora: dict[str, CorpusConfig] = {}
    errors: dict[str, str] = {}
    for corpus_file in sorted(corpora_dir.glob("*.yaml")):
        cname = corpus_file.stem
        try:
            corpora[cname] = _parse_corpus(cname, corpus_file, _load_yaml(corpus_file))
        except ConfigError as exc:
            errors[cname] = str(exc)

    return Config(
        path=path,
        artifacts_dir=artifacts_dir,
        user_data_dir=user_data_dir,
        corpora_dir=corpora_dir,
        default_corpus=default_corpus,
        embedding=raw.get("embedding") or {},
        verify=raw.get("verify") or {},
        corpora=corpora,
        errors=errors,
    )
