"""Canonical KbPost v1 schema and provenance contract.

Pin: field names here are the single source of truth for all workers
consuming/producing KbPost records. Do not rename fields.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "1"

# Ordered list of field names in a KbPost record.
KBPOST_FIELDS = [
    "post_id",
    "shortcode",
    "url",
    "owner",
    "content_type",
    "value_score",
    "is_educational",
    "domains",
    "summary",
    "resources",
    "workflow_steps",
    "tips",
    "concepts",
    "tools_apps",
    "tags",
    "gated_content",
    "gated_trigger",
    "transcript",
    "media_files",
    "media_count",
    "domain",
    "extraction_status",
    "is_promo",
    "provenance",
    "ingestion",
]

# Fields that must be present (and non-None where applicable).
KBPOST_REQUIRED = [
    "post_id",
    "shortcode",
    "url",
    "owner",
    "content_type",
    "domain",
    "extraction_status",
    "provenance",
    "ingestion",
]

# Allowed values for content_type (from quick_analyze prompt enum).
CONTENT_TYPES = {
    "resource_list",
    "workflow",
    "tutorial",
    "tip",
    "concept",
    "showcase",
    "promo",
    "other",
}

# Canonical corpus domains for KbPost records.
KB_DOMAINS = {"uiux", "creator-growth"}

# Allowed values for domains (from quick_analyze prompt enum).
DOMAINS = {
    "graphic_design",
    "frontend",
    "ui_ux",
    "branding",
    "typography",
    "color",
    "motion",
    "illustration",
    "photography",
    "ai_tools",
    "dev_tools",
    "career",
    "other",
}

# Allowed values for extraction_status.
EXTRACTION_STATUSES = {"ok", "failed", "partial", "pending"}

EXTRACTION_STATUS_DEFAULT = "pending"


def empty_kbpost(post_id: str, shortcode: str, owner: str, domain: str = "uiux") -> dict[str, Any]:
    """Build a valid KbPost record with safe defaults for every field.

    Preconditions: post_id, shortcode, owner are strings; domain is the
    domain label (default "uiux").
    Postconditions: returned dict has exactly the keys in KBPOST_FIELDS,
    with defaults ("" / [] / None / enums), and passes validate_kbpost.
    """
    url = f"https://www.instagram.com/p/{shortcode}/"
    rec: dict[str, Any] = {
        "post_id": post_id,
        "shortcode": shortcode,
        "url": url,
        "owner": owner,
        "content_type": "other",
        "value_score": None,
        "is_educational": None,
        "domains": [],
        "summary": "",
        "resources": [],
        "workflow_steps": [],
        "tips": [],
        "concepts": [],
        "tools_apps": [],
        "tags": [],
        "gated_content": None,
        "gated_trigger": "",
        "transcript": "",
        "media_files": [],
        "media_count": 0,
        "domain": domain,
        "extraction_status": EXTRACTION_STATUS_DEFAULT,
        "is_promo": None,
        "provenance": {},
        "ingestion": {},
    }
    return rec


def build_provenance(
    source_post_id: str,
    media_ref: str | None = None,
    extractor_model: str = "gemini-3.1-flash-lite",
    confidence: float | None = None,
    extracted_at: str | None = None,
) -> dict[str, Any]:
    """Build the provenance dict for an extraction.

    Preconditions: source_post_id is a string. extracted_at, when given,
    is an ISO-8601 string; when None, the current UTC time is used.
    Postconditions: returns a dict with keys source_post_id, media_ref,
    extractor_model, confidence, extracted_at.
    """
    return {
        "source_post_id": source_post_id,
        "media_ref": media_ref,
        "extractor_model": extractor_model,
        "confidence": confidence,
        "extracted_at": extracted_at or datetime.now(timezone.utc).isoformat(),
    }


def validate_kbpost(rec: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate a record against the KbPost v1 contract.

    Preconditions: rec is a dict (or any mapping).
    Postconditions: returns (ok, errors) where errors is a list of
    human-readable strings; ok is True iff errors is empty. Checks:
      * all KBPOST_REQUIRED keys present
      * no keys outside KBPOST_FIELDS
      * content_type in CONTENT_TYPES (when truthy)
      * domain in KB_DOMAINS
    """
    errors: list[str] = []
    for key in KBPOST_REQUIRED:
        if key not in rec:
            errors.append(f"missing required field: {key}")
    for key in rec:
        if key not in KBPOST_FIELDS:
            errors.append(f"unknown field: {key}")
    content_type = rec.get("content_type")
    if content_type and content_type not in CONTENT_TYPES:
        errors.append(f"content_type not allowed: {content_type!r}")
    if rec.get("domain") not in KB_DOMAINS:
        errors.append(
            f"domain must be one of {sorted(KB_DOMAINS)}, got: {rec.get('domain')!r}"
        )
    return (not errors, errors)
