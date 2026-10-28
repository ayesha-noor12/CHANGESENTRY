"""Billing operations (mocked: no external payment provider is contacted)."""

REFUND_LEDGER = []

INVOICES = {
    "ord_1001": {"order_id": "ord_1001", "owner": "customer-42", "total": 120.0},
    "ord_1002": {"order_id": "ord_1002", "owner": "customer-77", "total": 35.5},
}


def issue_refund(order_id, amount, actor):
    """Refund part of an order.

    SENSITIVE: moves money. Callers must authorize the actor first
    (see ``app.auth.require_admin``).
    """
    if amount <= 0:
        raise ValueError("refund amount must be positive")
    entry = {"order_id": order_id, "amount": round(float(amount), 2), "actor": actor}
    REFUND_LEDGER.append(entry)
    return entry


def get_invoice(order_id):
    return INVOICES.get(order_id)
