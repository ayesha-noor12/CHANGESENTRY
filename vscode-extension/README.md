# ChangeSentry for VS Code

**Don't just predict what a code change might break. Prove it before you push.**

ChangeSentry compares your change with the code it replaces. It maps what the change touches, asks **NVIDIA Nemotron** (through **Nebius Token Factory**) what it might break, and then runs **the identical test on the base and head revisions**. A regression is reported as confirmed only when the test passes on base, fails on head, *and* the base revision itself states or enforces the behaviour.

Everything runs on your machine, against your own repository. Only the model calls (Nebius) and dependency advisory lookups (OSV, Tavily) go over the network.

## Use it

1. Open a git repository (Python, pytest).
2. Run **ChangeSentry: Check my changes** from the Command Palette, or click **ChangeSentry** in the status bar.
3. Pick the head (*Last commit* or *Uncommitted changes*) and the base (*Previous commit*, `main`, or any ref).

Results:
- a report panel with the verdict and, for each finding, **base vs head** results, the failed assertion, the requirement found in the base revision (click a `file:line` to open it), caveats, and the exact test code with its SHA-256;
- squiggles and **Problems** entries on the lines involved: an error for a confirmed regression, a warning for a behaviour change or an inconclusive test.

## Setup

- **Python backend.** The first run offers to create a private environment with the backend's requirements (Python 3.10+ must be installed). Or point `changesentry.pythonPath` to an interpreter that already has them.
- **Keys.** Run **ChangeSentry: Configure API keys**, or click **ChangeSentry: key needed** in the status bar. From there you can:
  - **import from a .env file** that has `NEBIUS_API_KEY` and `TAVILY_API_KEY` (and optionally `NEBIUS_MODEL`);
  - enter each key by hand;
  - **test the Nebius key**, which confirms it works and that the configured Nemotron model is available, and offers the available ones if not.

  Keys are kept in VS Code's encrypted secret storage. They are passed only to the local backend process, never to the tests it runs. Without a Nebius key, Nemotron analysis is skipped and a banner at the top of the report says so.
- **Settings:** `changesentry.nebiusModel` (default `nvidia/nemotron-3-super-120b-a12b`), `changesentry.nebiusBaseUrl`, `changesentry.backendPath`.
- **Route checks.** For the `auth_guard` test, add `.changesentry.json` with `{"dispatch_module": "app.main"}` (the module that exposes `dispatch(method, path, body, user)`).

## Limits

- Running a check executes your repository's tests and code locally, as `pytest` would. Only run it on code you trust.
- Two verification templates exist (`auth_guard`, `nonnegative_total`). Findings that fit neither are shown as *Not tested*. The repository's own test suite still runs on both revisions.
- Your project's dependencies must be importable by the Python interpreter ChangeSentry uses.
- The call graph is static. Dynamic dispatch and framework wiring can hide relationships.
