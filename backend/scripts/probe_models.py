"""List models your API key can call, and optionally probe a few (probing uses a little quota).
  python -m scripts.probe_models
  python -m scripts.probe_models --probe gemma-4-26b-a4b-it,gemini-2.5-flash-lite
"""
import argparse
import time

from google import genai
from google.genai import errors, types

from app.config import get_settings

HINTS = ("flash", "gemma", "lite")


def probe(client, model: str) -> None:
    tests = (
        ("plain", {}),
        ("json+system", {"system_instruction": "Reply as JSON.", "response_mime_type": "application/json"}),
    )
    for label, extra in tests:
        start = time.perf_counter()
        try:
            r = client.models.generate_content(
                model=model,
                contents='Return {"ok": true}',
                config=types.GenerateContentConfig(max_output_tokens=200, **extra),
            )
            ms = int((time.perf_counter() - start) * 1000)
            print(f"  {model:<34} {label:<12} OK   {ms:>5}ms  {(r.text or '').strip()[:40]!r}")
        except errors.APIError as e:
            print(f"  {model:<34} {label:<12} FAIL {e.code} {(e.message or '')[:120]}")
        except Exception as e:
            print(f"  {model:<34} {label:<12} FAIL {type(e).__name__}: {str(e)[:100]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", default="", help="comma-separated model names to test")
    args = ap.parse_args()

    client = genai.Client(api_key=get_settings().gemini_api_key)
    names = []
    for m in client.models.list():
        actions = getattr(m, "supported_actions", None) or []
        if not actions or "generateContent" in actions:
            names.append(m.name.removeprefix("models/"))
    names = sorted(set(names))
    print(f"{len(names)} models support generateContent. Likely candidates:")
    for n in names:
        if any(h in n.lower() for h in HINTS):
            print("  ", n)

    for model in [m.strip() for m in args.probe.split(",") if m.strip()]:
        print(f"\nProbing {model} ...")
        probe(client, model)


if __name__ == "__main__":
    main()
