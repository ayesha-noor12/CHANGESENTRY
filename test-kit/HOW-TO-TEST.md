# How to test ChangeSentry

ChangeSentry is a VS Code extension that checks whether a code change broke something. It runs **the same test on the code before and after the change** and reports a regression only when the test passes before and fails after. An AI model (NVIDIA Nemotron, through Nebius) suggests what to test.

Testing takes about 15 minutes.

## What's in this folder

| Item | What it is |
|---|---|
| `changesentry-0.1.0.vsix` | The extension |
| `demos/checkout` | A small shop where a pricing change makes some prices negative |
| `demos/auth` | A small app where a new web address lets anyone trigger a refund |
| `demos/safe` | The same app with only documentation changed. Nothing should be flagged |

Each demo is a git repository with two commits: the original code, then the change. **Don't delete the hidden `.git` folder inside each demo.**

## Before you start

- **VS Code** 1.90 or newer.
- **Python 3.10 or newer.** To check, run `python3 --version` in a terminal. Many Macs only have 3.9; if so, install Python from https://www.python.org/downloads/ (or run `brew install python`).
- **git.** To check, run `git --version`. On a Mac, the first time you run it may offer to install the developer tools; accept.
- **A Nebius Token Factory API key** (free). Create one at https://tokenfactory.nebius.com. A Tavily key is optional.

## 1. Install the extension

Run this in a terminal (macOS):
```bash
"/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code" --install-extension ~/Downloads/ChangeSentry-test-kit/changesentry-0.1.0.vsix
```
Adjust the path if you unzipped the kit somewhere else. Or, in VS Code: open the **Extensions** view, click **…** at the top right, choose **Install from VSIX…**, and pick the file.

Then reload VS Code: Cmd+Shift+P (Ctrl+Shift+P on Windows), then **Reload Window**.

## 2. Add your key

Run Cmd+Shift+P, then **ChangeSentry: Enter API keys (Nebius and Tavily)**.
- Paste your Nebius key and press Enter. The key is checked with Nebius before it's saved. If it's rejected, the box tells you how many characters you pasted, so you can see whether the paste was incomplete.
- Paste a Tavily key or press Enter to skip.

## 3. Run the three demos

For each demo, open it with **File → Open Folder…**. Then click **ChangeSentry** in the bottom-left status bar and choose **Last commit**, then **Previous commit**.

The first run asks to install the Python part. Click **Install now**; it takes about a minute.

| Demo | What you should see |
|---|---|
| `demos/checkout` | **"1 issue(s) confirmed"**. Base **PASS** (48 price combinations, 0 negative) and head **FAIL** (the same 48 combinations, 27 negative, for example `-10.0`). The requirement comes from `docs/pricing.md`: "A checkout total must never be negative." A red underline in `shop/pricing.py` |
| `demos/auth` | **"2 issue(s) confirmed"**. Base PASS and head FAIL for the new `/webhooks/payment-provider` route, with a yellow note: the route didn't exist before, so base returns 404. The old PyJWT version is listed as vulnerable |
| `demos/safe` | **"No issue detected by the checks run"**, with no underlines. The existing tests pass on both versions |

A run takes about 10–30 seconds. Most of that is the AI model.

**The Nebius key matters for the checkout demo.** In `checkout`, only the AI suggests the test that catches the bug. Without a working key, checkout shows "No issue detected… model analysis did not complete" with a yellow banner. That is the honest result without the AI, not a bug. The `auth` demo still finds its problem without a key, through a built-in rule.

## What to send back

- Did each demo show the expected result?
- Anything confusing or broken: send a screenshot. Also open **View → Output**, choose **ChangeSentry** in the dropdown, and copy that text. It never contains your keys.

## Notes

- ChangeSentry runs the demo code and its tests on your machine, as `pytest` would. Only run it on code you trust.
- If the report shows a yellow **"Nemotron analysis did not complete"** banner, the AI call failed; usually running the check again fixes it. The report never invents findings when that happens.
- To remove the extension: open the Extensions view, then ChangeSentry, then **Uninstall**.
