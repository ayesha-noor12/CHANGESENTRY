"""Checkout totals.

Invariant (docs/pricing.md): a checkout total is never negative.
"""
from shop.pricing import add_tax, apply_discount

FREE_SHIPPING_THRESHOLD = 50.0
SHIPPING_FEE = 4.99


def shipping_for(subtotal: float) -> float:
    return 0.0 if subtotal >= FREE_SHIPPING_THRESHOLD else SHIPPING_FEE


def checkout_total(subtotal: float, discount_percent: float = 0.0) -> float:
    """Amount charged to the customer at checkout."""
    discounted = apply_discount(subtotal, discount_percent)
    return round(add_tax(discounted) + shipping_for(subtotal), 2)
