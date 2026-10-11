"""Canonical extracted-field vocabulary (PRD 6.4) and the whitelist filter (PRD 7.6)."""

from collections.abc import Mapping

CANONICAL_FIELDS: tuple[str, ...] = (
    "document_number",
    "document_date",
    "due_date",
    "issuer_name",
    "recipient_name",
    "reference_number",
    "subtotal",
    "tax_amount",
    "total_amount",
    "currency",
    "payment_terms",
    "line_items_summary",
)

_CANONICAL_SET = frozenset(CANONICAL_FIELDS)


def filter_fields(fields: Mapping[str, object]) -> dict[str, str]:
    """Keep only canonical keys whose values are non-empty strings, in canonical order."""
    out: dict[str, str] = {}
    for key in CANONICAL_FIELDS:
        value = fields.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value
    return out


def unknown_keys(fields: Mapping[str, object]) -> list[str]:
    return sorted(k for k in fields if k not in _CANONICAL_SET)
