# ChangeSentry

**Detect what a code change could break before it reaches production.**

A new feature can open a security hole or break existing behaviour through the way it interacts with older code, and reviewing only the changed lines can miss that. ChangeSentry takes a change, follows its relationships through the rest of the repository, runs deterministic checks, asks an **NVIDIA Nemotron** model (through **Nebius Token Factory**) to reason over that evidence, searches for advisories on changed dependencies (**Tavily** and **OSV**), and then **runs bounded verification tests** whose real output it displays.

Every finding carries one of three verification labels: **Confirmed by test**, **Not reproduced**, or **Not tested**. The report also lists the checks that were *not* performed.

## What it does (implemented)

| Step | Module | What actually happens |
|---|---|---|
| Diff | `repository_analyzer.py` | Unified diff of a fixture's `before/` and `after/` trees, with changed line numbers |
| AST index | `repository_analyzer.py` | Python `ast`: imports, functions, direct calls, route decorators, request-payload keys |
| Impact graph | `repository_analyzer.py` | Changed functions plus up to 3 hops of callers and callees. An edge is **resolved** when it goes through a static import and **candidate** when it is matched by name only |
| Deterministic checks | `static_checks.py` | `ruff` and `bandit` on the changed files, plus the repo's existing `pytest` suite, all run in a disposable copy |
| Guard-consistency rule | `repository_analyzer.py` | Flags a changed route that calls a function which every other route guards with `require_*`/auth checks |
| Model analysis | `nemotron_client.py`, `prompts.py` | Sends the diff, graph edges, source excerpts, tool output and the list of valid test targets. The model must return JSON, which is checked with Pydantic and retried once if invalid |
| Validation | `pipeline.py` | Rejects unknown files, invalid lines, unsupported templates and targets that don't exist in the repo. Rejections appear in the report |
| Verification planning | `pipeline.py` | A second Nemotron call (Prompt C) per risk picks a template and target, which the backend validates again |
| Advisories | `advisory_search.py` | For added or re-pinned dependencies: an **OSV** exact-version query (a verified affected-version match) and a **Tavily** search (leads with URLs and snippets, never treated as proof) |
| Test execution | `test_runner.py` | Fills an approved template (`auth_guard`, `nonnegative_total`) with `repr` literals, writes it into a temporary copy, and runs a fixed `pytest` command with a timeout, CPU and memory limits, and an environment stripped of secrets |
| Report | `report_builder.py` | Verdict, per-risk status, real command, exit code, stdout, the generated test code, and the checks not performed |

The model never supplies shell commands or code that gets executed. It only picks a template id and a target, and both are checked against the AST index.

## Demo scenarios

| Scenario | Change | Expected result |
|---|---|---|
| `auth-boundary` | New `POST /webhooks/payment-provider` calls `billing.issue_refund` without `require_admin`, which the existing admin route uses. It also adds `PyJWT==1.7.1` | The `auth_guard` test **confirms** that anonymous and customer callers get HTTP 200 and a refund. OSV lists PyJWT 1.7.1 as affected |
| `checkout-regression` | `apply_discount` gains a stacking coupon and loses its clamp at zero. `checkout_total` and `invoice_line` depend on it | The `nonnegative_total` test **confirms** negative totals and prints the counterexamples |
| `safe-change` | A docstring and a README section change | No confirmed issue: "No issue detected by the checks run" |

The existing tests in each fixture still pass after the change. ChangeSentry's verification tests are what catch the problem.

## Run locally

Requirements: Python 3.10+, Node 18+.

```bash
# Backend
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # fill in NEBIUS_API_KEY, NEBIUS_MODEL, TAVILY_API_KEY
python -m scripts.check_nebius  # lists Nemotron model ids available to your key and sends a test call
uvicorn app.main:app --reload --port 8000

# Frontend (second terminal)
cd frontend
npm install
cp .env.example .env.local      # BACKEND_URL=http://localhost:8000
npm run dev                     # http://localhost:3000
```

Keys are read only by the backend. The browser talks to Next.js, which proxies `/api/*` to FastAPI (`next.config.mjs`), so no secret is ever placed in a `NEXT_PUBLIC_*` variable.

Without keys the app still runs. The deterministic checks and tests execute, and the report says plainly that Nemotron and Tavily were not called.

### Tests and evaluation

```bash
cd backend
pytest                     # offline: stubs the model and the network
python -m scripts.run_eval # end to end on all three scenarios with your real keys; compares against scenario.json "expected"
```

## API

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/health` | Which integrations are configured (booleans and the model id, never keys) |
| `GET` | `/api/scenarios` | The predefined scenarios |
| `POST` | `/api/analyze` | `{"scenario_id": "auth-boundary"}` returns a run with `run_id`. Add `"wait": true` to block until the report is ready |
| `GET` | `/api/analysis/{run_id}` | Stage progress, plus the report (partial while running) |

The response schema is in `backend/app/models.py` and mirrored in `frontend/src/lib/types.ts`.

## Deploy

- **Backend**: `backend/Dockerfile` (listens on `$PORT`) works on Render, Railway, Fly.io and similar hosts. Set `NEBIUS_API_KEY`, `NEBIUS_BASE_URL`, `NEBIUS_MODEL`, `TAVILY_API_KEY` and `ALLOWED_ORIGINS` as service secrets.
- **Frontend**: deploy `frontend/` to Vercel with `BACKEND_URL=https://<your-backend>`.

## Limits

- Only the three bundled fixtures can be analyzed. Arbitrary repositories and uploaded code are deliberately unsupported.
- The call graph is static. Dynamic dispatch, reflection and framework wiring can hide relationships.
- Only two test templates exist, and anything outside their contracts is not tested.
- Passing checks are evidence, not proof that a change is safe.

## License

MIT. See [LICENSE](LICENSE).
