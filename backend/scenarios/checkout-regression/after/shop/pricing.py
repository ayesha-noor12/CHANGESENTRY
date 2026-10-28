"""Price calculations shared by checkout and invoicing."""

MAX_PERCENT = 100.0
TAX_RATE = 0.08


def apply_discount(subtotal: float, percent: float, coupon_amount: float = 0.0) -> float:
    """Return the subtotal after a percentage discount and an optional flat coupon.

    Coupons now stack with percentage promotions.
    """
    discounted = subtotal * (1 - percent / 100)
    return round(discounted - coupon_amount, 2)


def add_tax(amount: float) -> float:
    return round(amount * (1 + TAX_RATE), 2)
