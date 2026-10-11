"""Fast-mode deterministic field extractor (PRD 16.7).

Order: document_number -> reference_number -> dates -> names -> amounts -> currency -> payment_terms ->
line_items_summary. Within a key the first match in document order wins. All values are strings.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field

AMOUNT = r"-?\(?[$€£]?\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})\)?"
DATE = r"\b(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\b"

DOC_NO = re.compile(
    r"\b(tax invoice|invoice|inv|purchase order|po|order|quotation|quote|receipt|credit note)\b"
    r"\s*(?:no\.?|number|#|:)?\s*[:#]?\s*([A-Z]{0,5}[-/]?\d[\w\-/]{2,})",
    re.I,
)
REF_NO = re.compile(
    r"\b(?:ref(?:erence)?|po|your order|order ref)\b\s*(?:no\.?|#|:)?\s*[:#]?\s*([A-Z0-9][\w\-/]{2,})",
    re.I,
)
DATE_RE = re.compile(DATE)
AMOUNT_RE = re.compile(AMOUNT)
COMPANY_RE = re.compile(r"\b(pty|ltd|llc|inc|limited|corp|gmbh)\b|\bco\.", re.I)
RECIPIENT_LABEL_RE = re.compile(r"^(bill to|ship to|to|customer|sold to)\b\s*:?\s*(.*)$", re.I)
SUBTOTAL_KW = r"\b(subtotal|sub total|net)\b"
TAX_KW = r"\b(gst|vat|tax)\b"
TOTAL_KW = r"\b(total|amount due|balance due|grand total)\b"
CURRENCY_RE = re.compile(r"\b(AUD|USD|EUR|GBP|NZD|CAD|SGD|INR|JPY)\b")
TERMS_RE = re.compile(r"\b(net\s*\d{1,3}|due on receipt|cod|\d{1,3}\s*days)\b", re.I)
LINE_ITEM_RE = re.compile(r"^(.{3,60}?)\s+(\d+(?:\.\d+)?)\s+[$€£]?[\d,]+\.\d{2}")
# Lines that look like line items but are summary rows.
SUMMARY_ROW_RE = re.compile(rf"{SUBTOTAL_KW}|{TAX_KW}|{TOTAL_KW}", re.I)


@dataclass
class Ctx:
    lines: list[str]
    used: set[int] = field(default_factory=set)  # line indexes already consumed


def _first_line(ctx: Ctx, pred: Callable[[str], bool]) -> int | None:
    for i, ln in enumerate(ctx.lines):
        if i not in ctx.used and pred(ln):
            return i
    return None


def _clean_amount(raw: str) -> str:
    return re.sub(r"[$€£\s]", "", raw)


def _amount_on(ctx: Ctx, keyword_re: str, last: bool = False, exclude_re: str | None = None) -> str | None:
    hits: list[tuple[int, list[str]]] = []
    for i, ln in enumerate(ctx.lines):
        if not re.search(keyword_re, ln, re.I):
            continue
        if exclude_re and re.search(exclude_re, ln, re.I):
            continue
        amounts = [m.group(0) for m in AMOUNT_RE.finditer(ln)]
        if amounts:
            hits.append((i, amounts))
    if not hits:
        return None
    _, amts = hits[-1] if last else hits[0]
    return _clean_amount(amts[-1])  # last amount on the line, symbols stripped


def _document_number(ctx: Ctx, out: dict[str, str]) -> None:
    for i, ln in enumerate(ctx.lines):
        if m := DOC_NO.search(ln):
            out["document_number"] = m.group(2)
            ctx.used.add(i)
            return


def _reference_number(ctx: Ctx, out: dict[str, str]) -> None:
    for i, ln in enumerate(ctx.lines):
        if i in ctx.used:
            continue
        if m := REF_NO.search(ln):
            value = m.group(1)
            if value == out.get("document_number"):
                continue
            out["reference_number"] = value
            ctx.used.add(i)
            return


def _dates(ctx: Ctx, out: dict[str, str]) -> None:
    due_idx: int | None = None
    for i, ln in enumerate(ctx.lines):
        if re.search(r"\bdue\b", ln, re.I) and (m := DATE_RE.search(ln)):
            out["due_date"] = m.group(1)
            due_idx = i
            break
    # document_date: prefer a line containing 'date' (but not the due-date line), else first date anywhere.
    for i, ln in enumerate(ctx.lines):
        if i != due_idx and re.search(r"date", ln, re.I) and (m := DATE_RE.search(ln)):
            out["document_date"] = m.group(1)
            return
    for i, ln in enumerate(ctx.lines):
        if i != due_idx and (m := DATE_RE.search(ln)):
            out["document_date"] = m.group(1)
            return


def _names(ctx: Ctx, out: dict[str, str]) -> None:
    recipient_idx: int | None = None
    for i, ln in enumerate(ctx.lines):
        if m := RECIPIENT_LABEL_RE.match(ln):
            inline = m.group(2).strip()
            if inline:
                out["recipient_name"] = inline
                recipient_idx = i
            elif i + 1 < len(ctx.lines):
                out["recipient_name"] = ctx.lines[i + 1]
                recipient_idx = i + 1
            break
    for i, ln in enumerate(ctx.lines):
        if i != recipient_idx and COMPANY_RE.search(ln):
            out["issuer_name"] = ln
            return
    for i, ln in enumerate(ctx.lines):
        if i != recipient_idx and len(ln) <= 60:
            out["issuer_name"] = ln
            return


def _amounts(ctx: Ctx, out: dict[str, str]) -> None:
    if v := _amount_on(ctx, SUBTOTAL_KW):
        out["subtotal"] = v
    if v := _amount_on(ctx, TAX_KW, exclude_re=r"\btotal\b"):
        out["tax_amount"] = v
    if v := _amount_on(ctx, TOTAL_KW, last=True, exclude_re=SUBTOTAL_KW):
        out["total_amount"] = v


def _currency(ctx: Ctx, out: dict[str, str]) -> None:
    for ln in ctx.lines:
        if m := CURRENCY_RE.search(ln):
            out["currency"] = m.group(1)
            return


def _payment_terms(ctx: Ctx, out: dict[str, str]) -> None:
    for ln in ctx.lines:
        if m := TERMS_RE.search(ln):
            out["payment_terms"] = m.group(1)
            return


def _line_items(ctx: Ctx, out: dict[str, str]) -> None:
    descriptions: list[str] = []
    for ln in ctx.lines:
        if SUMMARY_ROW_RE.search(ln):
            continue
        if m := LINE_ITEM_RE.match(ln):
            descriptions.append(f"{m.group(1).strip()} x{m.group(2)}")
    if descriptions:
        out["line_items_summary"] = f"{len(descriptions)} line items: " + "; ".join(descriptions[:3])


def extract(raw_text: str) -> dict[str, str]:
    ctx = Ctx([ln.strip() for ln in raw_text.splitlines() if ln.strip()])
    out: dict[str, str] = {}
    for step in (_document_number, _reference_number, _dates, _names, _amounts, _currency, _payment_terms, _line_items):
        step(ctx, out)
    return {k: str(v) for k, v in out.items() if v and str(v).strip()}
