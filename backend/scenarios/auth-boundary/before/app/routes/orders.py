"""Customer-facing order routes."""
from app.auth import require_user
from app.router import PermissionDenied, route
from app.services.billing import get_invoice


@route("/orders/invoice", method="GET")
def view_invoice(request):
    user = require_user(request.user)
    invoice = get_invoice(request.body.get("order_id"))
    if invoice is None or invoice["owner"] != user["id"]:
        raise PermissionDenied("not your order")
    return {"invoice": invoice}
