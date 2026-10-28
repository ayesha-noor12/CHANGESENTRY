# Sample billing service

Toy application used by ChangeSentry demos. Routes are dispatched in-process;
billing operations are mocked and never contact a payment provider.

## Health checks

`GET /health` returns `{"status": "ok"}` and is polled by the load balancer.
