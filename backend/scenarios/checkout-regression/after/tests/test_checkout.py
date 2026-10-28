from shop.checkout import checkout_total
from shop.invoice import invoice_line


def test_full_price_includes_tax_and_shipping():
    assert checkout_total(20.0) == 26.59


def test_discount_applies_before_tax():
    assert checkout_total(100.0, discount_percent=10) == 97.2


def test_invoice_line_formats_net_amount():
    assert invoice_line("Mug", 10.0, 50) == "Mug: 5.00"


def test_coupon_reduces_total():
    assert checkout_total(100.0, coupon_amount=10) == 97.2
