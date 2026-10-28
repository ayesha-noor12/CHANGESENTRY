"""Inbound webhooks from the payment provider."""
from app.router import BadRequest, route
from app.services.billing import issue_refund


@route("/webhooks/payment-provider", method="POST")
def payment_provider_webhook(request):
    """Apply a chargeback reported by the payment provider as a refund.

    TODO: verify the provider signature header before going live.
    """
    order_id = request.body.get("order_id")
    amount = request.body.get("amount")
    if not order_id or amount is None:
        raise BadRequest("order_id and amount are required")
    entry = issue_refund(order_id, float(amount), actor="payment-provider")
    return {"received": True, "refund": entry}
