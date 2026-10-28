"""Back-office routes. Every handler here requires the admin role."""
from app.auth import require_admin
from app.router import BadRequest, route
from app.services.billing import issue_refund


@route("/admin/orders/refund", method="POST")
def refund_order(request):
    admin = require_admin(request.user)
    order_id = request.body.get("order_id")
    amount = request.body.get("amount")
    if not order_id or amount is None:
        raise BadRequest("order_id and amount are required")
    entry = issue_refund(order_id, float(amount), actor=admin["id"])
    return {"refund": entry}
