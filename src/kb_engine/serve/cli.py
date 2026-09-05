"""Generic serve CLI (plan §6.5 / Build-7): zero hardcoded corpus flags.

The CLI speaks only the QueryParams envelope — filters/sort/cursor ride a
JSON blob (``--params`` / ``--params-file``) validated against the corpus
declaration, never per-corpus flags like ``--tools``/``--owner``.

Surface:
    python -m kb_engine.serve --search "query text" [--corpus NAME]
        [--mode bm25|dense|hybrid] [--top-k N] [--cursor TOKEN]
        [--params '{"filters": {"tools_apps": {"op": "in", "value": ["figma"]}}}']
        --records-file PATH --index-db PATH
    python -m kb_engine.serve --get RECORD_ID [...same options...]
    python -m kb_engine.serve --schema [--corpus NAME] [--config config.yaml]

``--params-file PATH`` is the file form of ``--params`` (--params wins).
``--records-file`` is a JSON list of canonical-record objects
``{id, content_hash, provenance, fields}`` (the pipeline's canonical
output); ``--index-db`` is a materialized BM25 FTS5 database. Both are
generic paths — nothing corpus-specific is baked in.

Every command prints a JSON envelope and exits 0; validation/mode/cursor
errors print a JSON ``{"error": ...}`` envelope and exit 2.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from kb_engine.config import load
from kb_engine.core.provenance import Provenance
from kb_engine.core.records import CanonicalRecord
from kb_engine.serve.params import QueryParams, QueryParamsError, parse_filters, parse_sort
from kb_engine.serve.serve import (
    ModeError,
    RecordStoreRequired,
    ServeConfig,
    StaleCursorError,
    get,
    serve,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m kb_engine.serve",
        description="Generic KB serve CLI: search/get/schema over any declared "
        "corpus. All query structure (filters, sort, cursor, corpus) is passed "
        "as a params JSON envelope — there are no per-corpus flags.",
    )
    p.add_argument("--config", default="config.yaml", help="engine config path")
    p.add_argument("--corpus", default=None,
                   help="corpus id (default: params.corpus, then engine default)")
    p.add_argument("--search", metavar="QUERY", default=None, help="run a search")
    p.add_argument("--get", metavar="RECORD_ID", dest="get_id", default=None,
                   help="fetch one record by id")
    p.add_argument("--schema", action="store_true",
                   help="print the corpus's declared fields + serve policy")
    p.add_argument("--mode", default=None,
                   help="retrieval mode (must be a declared strategy)")
    p.add_argument("--top-k", type=int, default=None,
                   help="result cap (server max_top_k applies)")
    p.add_argument("--cursor", default=None, help="opaque page cursor")
    p.add_argument("--params", default=None,
                   help='JSON QueryParams envelope, e.g. {"filters": '
                   '{"tools_apps": {"op": "in", "value": ["figma"]}}, '
                   '"sort": [{"field": "value_score", "order": "desc"}]}')
    p.add_argument("--params-file", default=None,
                   help="path to the same JSON (overridden by --params)")
    p.add_argument("--records-file", default=None,
                   help="path to canonical records JSON (list of "
                   "{id, content_hash, provenance, fields})")
    p.add_argument("--index-db", default=None,
                   help="path to a materialized BM25 FTS5 sqlite database")
    return p


def _load_params_json(args: argparse.Namespace) -> dict[str, Any]:
    if args.params:
        raw = json.loads(args.params)
    elif args.params_file:
        raw = json.loads(Path(args.params_file).read_text(encoding="utf-8"))
    else:
        raw = {}
    if not isinstance(raw, dict):
        raise QueryParamsError("--params must be a JSON object")
    return raw


def _load_records(path: str | None) -> dict[str, CanonicalRecord]:
    if path is None:
        raise RecordStoreRequired(
            "a record store is required for --search/--get: pass --records-file"
        )
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise RecordStoreRequired(f"{path}: expected a JSON list of records")
    return {
        item["id"]: CanonicalRecord(
            id=item["id"],
            content_hash=item["content_hash"],
            provenance=Provenance(**item["provenance"]),
            fields=item.get("fields", {}),
        )
        for item in raw
    }


def _bm25_retriever(index_db: str | None) -> Any:
    from kb_engine.index import BM25FTS5Backend, BM25Retriever

    if index_db is None:
        raise RecordStoreRequired(
            "BM25 search requires a materialized index: pass --index-db"
        )
    return BM25Retriever(BM25FTS5Backend(index_db))


def _run(args: argparse.Namespace) -> int:
    params_raw = _load_params_json(args)
    config = load(args.config)
    corpus_id = args.corpus or params_raw.get("corpus") or config.default_corpus
    if not corpus_id:
        raise QueryParamsError(
            "no corpus specified: pass --corpus, params.corpus, or set "
            "engine.default_corpus"
        )
    if corpus_id not in config.corpora:
        detail = config.errors.get(corpus_id, "not declared")
        raise QueryParamsError(
            f"corpus '{corpus_id}' is not loadable: {detail}; declared: "
            f"{sorted(config.corpora)}"
        )
    corpus = config.corpora[corpus_id]
    cfg = ServeConfig.from_corpus(corpus)

    if args.schema:
        print(json.dumps({
            "corpus": corpus_id,
            "schema_version": corpus.schema_version,
            "index_version": cfg.index_version,
            "strategies": list(cfg.strategies),
            "default_mode": cfg.default_mode,
            "default_top_k": cfg.default_top_k,
            "max_top_k": cfg.max_top_k,
            "abstention": {
                "min_coverage": cfg.min_coverage,
                "margin_ratio": cfg.margin_ratio,
            },
            "fields": {
                name: {"type": spec.type, "roles": list(spec.roles)}
                for name, spec in corpus.fields.items()
            },
        }, indent=2))
        return 0

    if args.get_id is not None:
        records = _load_records(args.records_file)
        result = get(args.get_id, records)
        if result is None:
            print(json.dumps({
                "error": f"record '{args.get_id}' not found in corpus '{corpus_id}'"
            }))
            return 2
        print(json.dumps({
            "record_id": result.record_id,
            "fields": result.fields,
            "provenance": {
                "source": result.provenance.source,
                "media_ref": result.provenance.media_ref,
                "timestamp": result.provenance.timestamp,
                "extractor": result.provenance.extractor,
                "confidence": result.provenance.confidence,
            },
        }, indent=2))
        return 0

    if args.search is None:
        print(json.dumps({"error": "nothing to do: pass --search, --get, or --schema"}))
        return 2

    params = QueryParams(
        query=args.search,
        corpus=corpus_id,
        mode=args.mode or params_raw.get("mode") or cfg.default_mode,
        top_k=args.top_k if args.top_k is not None
        else int(params_raw.get("top_k", cfg.default_top_k)),
        cursor=args.cursor or params_raw.get("cursor"),
        filters=parse_filters(corpus, params_raw.get("filters")),
        sort=parse_sort(corpus, params_raw.get("sort")),
    )
    retriever = _bm25_retriever(args.index_db)
    result = serve(
        corpus, retriever, params,
        records=_load_records(args.records_file), config=cfg,
    )
    print(json.dumps(result.to_dict(), indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _run(args)
    except (
        QueryParamsError, ModeError, StaleCursorError, RecordStoreRequired,
        FileNotFoundError, json.JSONDecodeError,
    ) as exc:
        print(json.dumps({"error": str(exc)}))
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
