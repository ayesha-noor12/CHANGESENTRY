"""Invoice line rendering (unchanged by the feature under review)."""
from shop.pricing import apply_discount


def invoice_line(description: str, subtotal: float, percent: float) -> str:
    net = apply_discount(subtotal, percent)
    return f"{description}: {net:.2f}"
