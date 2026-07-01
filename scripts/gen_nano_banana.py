"""Generate creatives with Google Nano Banana (gemini-2.5-flash-image).

Reads <client>/prompts.json (schema: campaign + concepts[].slug + concepts[].variations[]).
Saves PNGs to <client>/creatives/<campaign>/<NN>_<slug>.png where NN is 1-based variation index.

Usage:
  .venv/bin/python scripts/gen_nano_banana.py                       # generate all missing (default <client>/prompts.json)
  .venv/bin/python scripts/gen_nano_banana.py --prompts examples/prompts.example.json
  .venv/bin/python scripts/gen_nano_banana.py --slug hero
  .venv/bin/python scripts/gen_nano_banana.py --variation 2
  .venv/bin/python scripts/gen_nano_banana.py --names 01_hero,02_hero
  .venv/bin/python scripts/gen_nano_banana.py --force                # overwrite existing
  .venv/bin/python scripts/gen_nano_banana.py --aspect 16:9          # override aspect (default reads from prompts.json or 9:16)
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROMPTS = ROOT / "examples" / "prompts.example.json"
MODEL = "gemini-2.5-flash-image"
ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"


def load_api_key() -> str:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip()
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY not found in .env or environment")
    return key


def _mime_for(path: Path) -> str:
    ext = path.suffix.lower()
    return {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(ext, "image/png")


def call_gemini(prompt: str, api_key: str, aspect_ratio: str = "9:16", ref_images: list[str] | None = None) -> bytes:
    parts: list[dict] = []
    for ref in ref_images or []:
        rp = Path(ref)
        if not rp.is_absolute():
            rp = ROOT / rp
        if not rp.exists():
            raise RuntimeError(f"reference image not found: {rp}")
        parts.append({"inlineData": {"mimeType": _mime_for(rp), "data": base64.b64encode(rp.read_bytes()).decode()}})
    parts.append({"text": prompt})
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {"aspectRatio": aspect_ratio},
        },
    }
    # Payload (esp. with reference images) can exceed ARG_MAX, so pass it via a temp file, not -d inline.
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
        json.dump(payload, tf)
        payload_path = tf.name
    try:
        proc = subprocess.run(
            [
                "curl", "-sS", "--fail-with-body",
                "-X", "POST",
                "-H", "Content-Type: application/json",
                "--data-binary", f"@{payload_path}",
                f"{ENDPOINT}?key={api_key}",
            ],
            capture_output=True, text=True, timeout=180,
        )
    finally:
        os.unlink(payload_path)
    if proc.returncode != 0:
        raise RuntimeError(f"curl exit {proc.returncode}: {proc.stdout[:600]}")
    try:
        body = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"non-JSON response: {proc.stdout[:600]}")
    candidates = body.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"No candidates: {json.dumps(body)[:500]}")
    for part in candidates[0].get("content", {}).get("parts", []):
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            return base64.b64decode(inline["data"])
    raise RuntimeError(f"No image data in response")


def flatten_prompts(data: dict) -> list[dict]:
    """Expand concepts[].variations[] into a flat list of {name, slug, variation, prompt, campaign}."""
    campaign = data.get("campaign", "default")
    default_refs = data.get("reference_images", [])
    out = []
    for concept in data["concepts"]:
        slug = concept["slug"]
        refs = concept.get("reference_images", default_refs)
        for idx, prompt in enumerate(concept["variations"], start=1):
            out.append({
                "campaign": campaign,
                "slug": slug,
                "variation": idx,
                "name": f"{idx:02d}_{slug}",
                "prompt": prompt,
                "reference_images": refs,
            })
    return out


def filter_prompts(prompts: list[dict], args: argparse.Namespace) -> list[dict]:
    if args.names:
        wanted = set(args.names.split(","))
        prompts = [p for p in prompts if p["name"] in wanted]
    if args.slug:
        slugs = set(args.slug.split(","))
        prompts = [p for p in prompts if p["slug"] in slugs]
    if args.variation:
        vs = set(int(v) for v in args.variation.split(","))
        prompts = [p for p in prompts if p["variation"] in vs]
    return prompts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompts", help="path to prompts.json (default: examples/prompts.example.json)")
    ap.add_argument("--names", help="comma-separated names like 01_slug,02_slug")
    ap.add_argument("--slug", help="comma-separated concept slugs")
    ap.add_argument("--variation", help="comma-separated variation numbers (1,2,3)")
    ap.add_argument("--aspect", help="aspect ratio override (e.g. 9:16, 1:1, 16:9)")
    ap.add_argument("--force", action="store_true", help="overwrite existing files")
    args = ap.parse_args()

    api_key = load_api_key()
    prompts_path = Path(args.prompts) if args.prompts else DEFAULT_PROMPTS
    if not prompts_path.is_absolute():
        prompts_path = ROOT / prompts_path
    data = json.loads(prompts_path.read_text())
    prompts = filter_prompts(flatten_prompts(data), args)

    if not prompts:
        print("no prompts matched filters", flush=True)
        return

    aspect = args.aspect or data.get("aspect_ratio", "9:16")
    # Creatives are written next to the prompts file: <client>/creatives/<campaign>/
    creatives_root = prompts_path.parent / "creatives"
    out_dir = creatives_root / prompts[0]["campaign"]
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"-> {len(prompts)} prompts @ {aspect} → {out_dir.relative_to(ROOT)}/", flush=True)

    for p in prompts:
        out = out_dir / f"{p['name']}.png"
        if out.exists() and not args.force:
            print(f"   {p['name']} already exists, skipping (use --force to overwrite)", flush=True)
            continue
        print(f"   {p['name']} ...", end="", flush=True)
        try:
            img = call_gemini(p["prompt"], api_key, aspect_ratio=aspect, ref_images=p.get("reference_images"))
            out.write_bytes(img)
            print(f" {len(img):,} bytes", flush=True)
        except Exception as e:
            print(f" FAILED: {e}", flush=True)
        time.sleep(0.5)


if __name__ == "__main__":
    main()
