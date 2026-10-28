"""Price calculations shared by checkout and invoicing."""

MAX_PERCENT = 100.0
TAX_RATE = 0.08


def apply_discount(subtotal: float, percent: float) -> float:
    """Return the subtotal after a percentage discount. Never below zero."""
    percent = max(0.0, min(percent, MAX_PERCENT))
    return round(subtotal * (1 - percent / 100), 2)


def add_tax(amount: float) -> float:
    return round(amount * (1 + TAX_RATE), 2)
