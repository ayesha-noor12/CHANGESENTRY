from app.main import dispatch
from app.services.billing import REFUND_LEDGER

ADMIN = {"id": "admin-1", "role": "admin"}
CUSTOMER = {"id": "customer-42", "role": "customer"}


def test_admin_can_refund():
    response = dispatch("POST", "/admin/orders/refund", {"order_id": "ord_1001", "amount": 10}, user=ADMIN)
    assert response.status == 200
    assert REFUND_LEDGER[-1]["actor"] == "admin-1"


def test_customer_cannot_use_admin_refund():
    response = dispatch("POST", "/admin/orders/refund", {"order_id": "ord_1001", "amount": 10}, user=CUSTOMER)
    assert response.status == 403


def test_customer_sees_own_invoice_only():
    assert dispatch("GET", "/orders/invoice", {"order_id": "ord_1001"}, user=CUSTOMER).status == 200
    assert dispatch("GET", "/orders/invoice", {"order_id": "ord_1002"}, user=CUSTOMER).status == 403


def test_health():
    assert dispatch("GET", "/health").body == {"status": "ok"}
