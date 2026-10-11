"""Jev document-type categories (PRD 6.3): option keys, display labels, rubric descriptions."""

INSTRUCTIONS = (
    "Classify this scanned business document into exactly one document type based on its content, layout cues, "
    "and labels such as 'Invoice', 'PO', 'Quote', 'Receipt'. If it does not clearly match any listed type, "
    "choose none_of_the_above."
)

# Ordered: key -> (display label, rubric description sent as the criteria value).
CATEGORIES: dict[str, tuple[str, str]] = {
    "purchase_order": (
        "Purchase Order",
        "A buyer's formal order to a supplier listing items/services to purchase, quantities, prices, and a PO "
        "number. Issued by the buyer, addressed to the seller.",
    ),
    "transport_request": (
        "Transport Request",
        "A request to move goods: pickup/delivery addresses, dates, weights, pallet or parcel counts, carrier or "
        "freight instructions. Not an invoice for transport.",
    ),
    "sales_order": (
        "Sales Order",
        "A seller's confirmation of a customer's order: order number, customer details, items, quantities, prices, "
        "delivery date. Issued by the seller.",
    ),
    "invoice_from_supplier": (
        "Invoice from Supplier",
        "A supplier's demand for payment for goods/services delivered: invoice number, invoice date, due date, "
        "line items, tax, total due, payment instructions.",
    ),
    "credit_note": (
        "Credit Note",
        "A document issued by a seller reducing an amount owed, usually referencing an earlier invoice; shows a "
        "negative or credited amount.",
    ),
    "receipt": (
        "Receipt",
        "Proof that payment was made, typically point-of-sale: merchant name, date/time, items, amount paid, "
        "payment method, 'paid' or 'thank you'.",
    ),
    "bill": (
        "Bill",
        "A statement of charges for a service or utility (electricity, telecom, rent, subscription) with account "
        "number, billing period, and amount due. Not an itemised goods invoice.",
    ),
    "packing_slip": (
        "Packing Slip",
        "A shipment document listing items and quantities packed, often with order/PO reference and no or minimal "
        "pricing; accompanies delivered goods.",
    ),
    "quotation": (
        "Quotation",
        "A seller's offer stating prices for specified goods/services, valid for a period; may be labelled Quote, "
        "Quotation, Estimate, or Proposal.",
    ),
    "quote_request": (
        "Quote Request",
        "A buyer's request asking a supplier to provide prices; may be labelled RFQ, Request for Quotation, or ask "
        "'please quote'.",
    ),
    "none_of_the_above": (
        "None of the above",
        "Not a business transaction document of the kinds listed, or the text is too sparse or unrelated to decide.",
    ),
}

CATEGORY_KEYS: tuple[str, ...] = tuple(CATEGORIES)
CRITERIA: dict[str, str] = {key: rubric for key, (_, rubric) in CATEGORIES.items()}
LABELS: dict[str, str] = {key: label for key, (label, _) in CATEGORIES.items()}
