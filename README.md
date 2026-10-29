# ChangeSentry

**Don't just predict what a code change might break. Prove it before it reaches production.**

A few changed lines can break behaviour elsewhere in a repository, and reviewing only the changed lines can miss that. ChangeSentry follows a change through the rest of the code, asks an **NVIDIA Nemotron** model (through **Nebius Token Factory**) what it might break, and then tests that hypothesis: it runs **the same test against the code before and after the change** and reports what actually happened.

A finding is reported as a **confirmed regression** only when both of these hold:

1. The identical test **passes on the base revision and fails on the head revision**.
2. The **base revision itself** states or enforces the behaviour the test checks. This evidence is found by deterministic rules, not by the model.

Everything else is labelled for what it is: a behaviour change, a pre-existing failure, not reproduced, or not tested. The report also lists the checks that were *not* performed.

## Measured results

These are the results of `python -m scripts.run_eval` with the real Nemotron model (`nvidia/nemotron-3-super-120b-a12b`) on 29 October 2026. The base and head outcomes were identical on every run in which the model call succeeded (see [Limits](#limits) for the one that did not).

| Scenario | Base | Head | Conclusion | Requirement found in the base revision |
|---|---|---|---|---|
| `checkout-regression` | PASS: 48 input combinations, 0 negative | FAIL: the same 48 combinations, 27 negative (for example, `apply_discount(subtotal=0, percent=0, coupon_amount=10) = -10.0`) | **Regression confirmed** | `docs/pricing.md:4`: "A checkout total must never be negative." It is also stated in the docstrings of `shop/pricing.py` and `shop/checkout.py` |
| `auth-boundary` | PASS: anonymous and customer callers get 404 | FAIL: both callers get HTTP 200 and a refund is issued | **Regression confirmed**, with a caveat (see [Limits](#limits)) | `app/routes/admin.py:9`: the existing refund route calls `require_admin` before `issue_refund` |
| `safe-change` | Existing suite PASS (4 tests) | Existing suite PASS (4 tests) | **No regression detected by these tests.** No findings were raised | Not applicable |

In `auth-boundary`, OSV also lists the newly added `PyJWT==1.7.1` as an affected version, and Tavily returns advisory links for it.

In each fixture the repository's existing tests pass on both revisions. The tests that ChangeSentry generates are the ones that catch the problem.

## How differential verification works

```
diff + AST graph → Nemotron hypothesis → validated test plan → render the test once
      → run on base ─┐
                     ├─ compare → look for the requirement in base → classify → report
      → run on head ─┘
```

1. **One test, two revisions.** The backend fills an approved template, writing the inputs into the file as literal values, and renders it **once**. The identical file is written into disposable copies of the base and head revisions and run with the same fixed `pytest` command. The dashboard shows the file's SHA-256 so anyone can check that it is the same on both sides.
2. **Classification** ([`test_runner.classify`](backend/app/test_runner.py)):

   | Base | Head | Outcome | Shown as |
   |---|---|---|---|
   | PASS | FAIL | `regression_confirmed` if the base revision has a requirement, otherwise `behavior_changed` | Confirmed regression / Behaviour changed |
   | FAIL | FAIL | `fails_on_both` (a pre-existing issue or an invalid test) | Fails on base too |
   | FAIL | PASS | `fixed_on_head` (a possible improvement or intentional change) | Not reproduced |
   | PASS | PASS | `not_reproduced` | Not reproduced |
   | error on either | | `inconclusive` | Test error |

3. **Independent requirement** ([`expectations.py`](backend/app/expectations.py)). The requirement is searched for in the **base** revision only, with fixed rules:
   - `auth_guard`: a base route that calls the same operation only after a `require_*` or auth guard, or the target route itself being guarded in base.
   - `nonnegative_total`: a "never negative" or "never below zero" statement in `docs/`, the README, or the modules of the target and of its callers and callees.

   If nothing is found, a base-pass/head-fail result stays **"Behaviour changed"**, because the change may be intended.
4. **Existing test suite on both revisions.** The repository's own `tests/` directory runs on base and on head. If it passes on base and fails on head, that also counts as a confirmed regression, because an existing test is an established requirement.

The model never supplies code or shell commands that get executed. It only picks a template id and a target, and the backend checks both against the AST index of the repository.

## Pipeline

| Step | Module | What happens |
|---|---|---|
| Diff | `repository_analyzer.py` | Unified diff of a fixture's `before/` and `after/` trees, with changed line numbers |
| AST index | `repository_analyzer.py` | Python `ast` for both revisions: imports, functions, direct calls, route decorators, request-payload keys |
| Impact graph | `repository_analyzer.py` | Changed functions plus up to 3 hops of callers and callees. An edge is **resolved** when it goes through a static import and **candidate** when it is matched by name only |
| Deterministic checks | `static_checks.py` | `ruff` and `bandit` on the changed files, and the existing `pytest` suite on base and head, each in a disposable copy |
| Guard-consistency rule | `repository_analyzer.py` | Flags a changed route that calls a function which every other route guards with `require_*` or an auth check |
| Model analysis | `nemotron_client.py`, `prompts.py` | Sends the diff, graph edges, source excerpts, tool output and the valid test targets. The model must return JSON, which is checked with Pydantic and retried once if invalid |
| Validation | `pipeline.py` | Rejects unknown files, invalid lines, unsupported templates and targets that don't exist. The rejections appear in the report |
| Verification planning | `pipeline.py` | A second Nemotron call per risk picks a template and target, which the backend validates again |
| Advisories | `advisory_search.py` | For added or re-pinned dependencies: an **OSV** exact-version query (a verified match) and a **Tavily** search (leads only, never treated as proof) |
| Differential test | `test_runner.py`, `expectations.py`, `sandbox.py` | Renders the test once, runs it on base and head with a timeout, a CPU limit, a memory limit where the OS allows it, and an environment stripped of secrets, then classifies the result |
| Report | `report_builder.py` | Verdict, per-risk status, base and head results (command, exit code, per-test output, failed assertion), the requirement citations, the test code and its hash, and the checks not performed |

## Run locally

Requirements: Python 3.10+ (tested locally on 3.14; the Dockerfile uses 3.11) and Node 18+.

```bash
# Backend
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # fill in NEBIUS_API_KEY, NEBIUS_MODEL, TAVILY_API_KEY
python -m scripts.check_nebius  # lists the Nemotron model ids available to your key and sends a test call
uvicorn app.main:app --reload --port 8000

# Frontend (second terminal)
cd frontend
npm install
cp .env.example .env.local      # BACKEND_URL=http://localhost:8000
npm run dev                     # http://localhost:3000
```

Keys are read only by the backend. The browser talks to Next.js, which proxies `/api/*` to FastAPI (`next.config.mjs`), so no secret ever goes into a `NEXT_PUBLIC_*` variable.

Without keys the app still runs. The deterministic checks and the base/head tests run, and the report states that Nemotron and Tavily were not called.

### Reproduce the results

```bash
cd backend
pytest                      # offline: stubs the model and the network
python -m scripts.run_eval  # all three scenarios end to end with your real keys
```

`run_eval` compares each run with the `expected` block in each `scenario.json` and prints, for every test, the base outcome, the head outcome, the classification, the number of base requirements found and the test hash:

```
PASS checkout-regression: model=ok verdict=issues_confirmed risks=1 confirmed=['nonnegative_total']
     existing tests: base=passed (4 passed) head=passed (4 passed)
     nonnegative_total shop.pricing:apply_discount: base=passed head=violated -> regression_confirmed (3 base requirement(s), test sha256 8483e9fa0e8e)
```

Nemotron does not always pick the same target, for example `apply_discount` or `checkout_total`. The conclusion is the same either way, but the test hash depends on the target.

## API

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/health` | Which integrations are configured (booleans and the model id, never keys) |
| `GET` | `/api/scenarios` | The predefined scenarios |
| `POST` | `/api/analyze` | `{"scenario_id": "checkout-regression"}` returns a run with `run_id`. Add `"wait": true` to block until the report is ready |
| `GET` | `/api/analysis/{run_id}` | Stage progress, plus the report (partial while running) |

Each risk's `verification` contains `base` and `head` runs, `outcome`, `requirements`, `caveats`, `test_code` and `test_sha256`. The schema is in `backend/app/models.py` and mirrored in `frontend/src/lib/types.ts`.

## Deploy

- **Backend**: `backend/Dockerfile` (listens on `$PORT`) works on Render, Railway, Fly.io and similar hosts. Set `NEBIUS_API_KEY`, `NEBIUS_BASE_URL`, `NEBIUS_MODEL`, `TAVILY_API_KEY` and `ALLOWED_ORIGINS` as service secrets.
- **Frontend**: deploy `frontend/` to Vercel with `BACKEND_URL=https://<your-backend>`.

## Limits

- **The authorization baseline is weaker than the checkout one.** `POST /webhooks/payment-provider` is new, so on the base revision the router returns **404** and the test passes because the endpoint did not exist. That shows anonymous callers could not trigger a refund through this path before the change. It does **not** show that the change removed a guard from an existing route. The requirement comes from a *different* base route (`/admin/orders/refund`) that guards the same `issue_refund` operation. The report states this caveat next to the result. The checkout scenario has no such gap: both revisions have the same function signature and receive the same 48 inputs.
- **Model failures make the analysis incomplete, not invented.** In our runs, one Nemotron call out of about a dozen on `safe-change` failed and we could not reproduce it. When that happens, the stage turns red, the verdict reads "model analysis did not complete", and the error appears in the Model tab and under *Checks not performed*. No finding is invented to fill the gap. The deterministic rules and the existing suite still run, and rerunning the scenario normally succeeds.
- Only the three bundled fixtures can be analyzed. Arbitrary repositories and uploaded code are deliberately unsupported, and revisions are `before/` and `after/` folders rather than git commits.
- Tests run as local processes with resource limits and a scrubbed environment, not in network-isolated containers. That is acceptable for the bundled fixtures only.
- The call graph is static. Dynamic dispatch, reflection and framework wiring can hide relationships.
- Only two test templates exist (`auth_guard`, `nonnegative_total`), and the requirement search uses fixed rules for each one. Behaviour outside their contracts is not tested.
- Passing checks are evidence, not proof that a change is safe.

## License

MIT. See [LICENSE](LICENSE).
