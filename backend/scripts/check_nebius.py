"""Verify Token Factory credentials and list available Nemotron model ids.

Usage (from backend/):  python -m scripts.check_nebius
"""
import sys

from openai import OpenAI

from app.config import env


def main() -> int:
    key, base = env("NEBIUS_API_KEY"), env("NEBIUS_BASE_URL")
    if not key or not base:
        print("Set NEBIUS_API_KEY and NEBIUS_BASE_URL in backend/.env first.")
        return 1
    client = OpenAI(api_key=key, base_url=base, timeout=30)
    ids = sorted(m.id for m in client.models.list())
    nemotron = [i for i in ids if "nemotron" in i.lower()]
    print("Nemotron models available to this key:")
    for model_id in nemotron or ["(none found - check the catalog)"]:
        print(f"  {model_id}")
    model = env("NEBIUS_MODEL")
    if not model:
        print("\nNEBIUS_MODEL is not set; copy one of the ids above into backend/.env.")
        return 1
    if model not in ids:
        print(f"\nNEBIUS_MODEL={model} is not in the model list for this key.")
        return 1
    reply = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": 'Reply with the JSON {"ok": true} only.'}], max_tokens=200,
    )
    print(f"\nTest completion from {model}:\n{reply.choices[0].message.content}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
