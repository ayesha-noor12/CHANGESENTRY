"""Price calculations shared by checkout and invoicing."""

MAX_PERCENT = 100.0
TAX_RATE = 0.08


def apply_discount(subtotal: float, percent: float, coupon_amount: float = 0.0) -> float:
    """Return the subtotal after one promotion: a flat coupon or a percentage discount.

    A coupon replaces the percentage discount. Never below zero.
    """
    if coupon_amount:
        discounted = subtotal - coupon_amount
    else:
        percent = max(0.0, min(percent, MAX_PERCENT))
        discounted = subtotal * (1 - percent / 100)
    return round(max(discounted, 0.0), 2)


def add_tax(amount: float) -> float:
    return round(amount * (1 + TAX_RATE), 2)
