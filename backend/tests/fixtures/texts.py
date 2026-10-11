"""Synthetic fixture documents (PRD 16.7 required fixtures) and their exact expected heuristic output."""

PAGE_SEPARATOR = "\n\n--- page {n} ---\n\n"

# (a) two-page supplier invoice with subtotal, GST, total, PO reference and Net 30 terms
INVOICE_PAGES = [
    "\n".join(
        [
            "Acme Supplies Pty Ltd",
            "123 Harbour St, Sydney NSW 2000",
            "TAX INVOICE",
            "Invoice No: INV-2026-0412",
            "Invoice Date: 28/09/2026",
            "Due Date: 28/10/2026",
            "Bill To:",
            "Blue Gum Cafe",
            "Your PO: PO-1187",
            "Description Qty Unit Price Amount",
            "Coffee beans 1kg 20 45.00 900.00",
            "Takeaway cups 500 0.40 200.00",
        ]
    ),
    "\n".join(
        [
            "Lids 500 0.10 50.00",
            "Delivery 1 30.00 30.00",
            "Subtotal 1,180.00",
            "GST 10% 118.00",
            "Total AUD 1,298.00",
            "Payment terms: Net 30",
            "Please pay to BSB 062-000 Account 1234 5678",
        ]
    ),
]
INVOICE_TEXT = INVOICE_PAGES[0] + PAGE_SEPARATOR.format(n=2) + INVOICE_PAGES[1]
INVOICE_EXPECTED = {
    "document_number": "INV-2026-0412",
    "reference_number": "PO-1187",
    "document_date": "28/09/2026",
    "due_date": "28/10/2026",
    "issuer_name": "Acme Supplies Pty Ltd",
    "recipient_name": "Blue Gum Cafe",
    "subtotal": "1,180.00",
    "tax_amount": "118.00",
    "total_amount": "1,298.00",
    "currency": "AUD",
    "payment_terms": "Net 30",
    "line_items_summary": "4 line items: Coffee beans 1kg x20; Takeaway cups x500; Lids x500",
}

# (b) point-of-sale receipt with tax and total but no document number
RECEIPT_TEXT = "\n".join(
    [
        "OFFICEWORKS",
        "Store 0412 Melbourne",
        "03/10/2026 14:32",
        "Printer paper A4 2 9.95 19.90",
        "Blue pens 10pk 1 6.50 6.50",
        "Stapler 1 16.20 16.20",
        "GST included 4.26",
        "TOTAL AUD 46.85",
        "EFTPOS PAID",
        "Thank you for shopping with us",
    ]
)
RECEIPT_EXPECTED = {
    "document_date": "03/10/2026",
    "issuer_name": "OFFICEWORKS",
    "tax_amount": "4.26",
    "total_amount": "46.85",
    "currency": "AUD",
    "line_items_summary": "3 line items: Printer paper A4 x2; Blue pens 10pk x1; Stapler x1",
}

# (c) quotation with a validity line
QUOTATION_TEXT = "\n".join(
    [
        "Brightline Signage Ltd",
        "QUOTATION",
        "Quote Number: Q-5531",
        "Date: 15 September 2026",
        "Customer:",
        "Harbour Bakery",
        "Item Qty Price Total",
        "Shopfront sign 1 850.00 850.00",
        "Installation 1 220.00 220.00",
        "Subtotal 1,070.00",
        "VAT 214.00",
        "Grand Total GBP 1,284.00",
        "This quotation is valid for 30 days from the date above.",
    ]
)
QUOTATION_EXPECTED = {
    "document_number": "Q-5531",
    "document_date": "15 September 2026",
    "issuer_name": "Brightline Signage Ltd",
    "recipient_name": "Harbour Bakery",
    "subtotal": "1,070.00",
    "tax_amount": "214.00",
    "total_amount": "1,284.00",
    "currency": "GBP",
    "payment_terms": "30 days",
    "line_items_summary": "2 line items: Shopfront sign x1; Installation x1",
}
