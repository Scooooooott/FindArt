#!/usr/bin/env python3
"""
Patch the 'artist' field in wikidata_candidates.jsonl.

The original fetch phase had a bug where P170 creator Q-IDs were not
resolved to English labels. This script reads candidates.jsonl, queries
Wikidata for the missing artist names, and writes the file back in-place.

After running, re-index Qdrant:
    python scripts/ingest_wikidata.py ingest

Usage:
    python scripts/patch_artist.py [--dry-run] [--limit N]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

DATA_DIR = Path(__file__).parent / "data"
CANDIDATES_FILE = DATA_DIR / "wikidata_candidates.jsonl"

_MW_ENDPOINT = "https://www.wikidata.org/w/api.php"
_USER_AGENT = (
    "FindArtIngest/0.1 "
    "(https://example.invalid/findart; contact@example.invalid)"
)
_ENTITY_BATCH = 50
_SLEEP = 0.5


def _http_get_json(url: str, params: dict) -> dict:
    full_url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        full_url,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                wait = int(exc.headers.get("Retry-After", "60"))
                print(f"  429 rate-limited — waiting {wait}s…")
                time.sleep(wait)
            else:
                raise
        except Exception as exc:
            wait = 10 * (attempt + 1)
            print(f"  Attempt {attempt + 1} failed: {exc}. Retrying in {wait}s…")
            time.sleep(wait)
    raise RuntimeError("Exceeded retry limit")


def _entity_label(entity: dict) -> str | None:
    labels = entity.get("labels") or {}
    en = labels.get("en")
    if isinstance(en, dict) and en.get("value"):
        return en["value"]
    for v in labels.values():
        if isinstance(v, dict) and v.get("value"):
            return v["value"]
    return None


def _claim_entity_id(entity: dict, pid: str) -> str | None:
    stmts = (entity.get("claims") or {}).get(pid, [])
    if not stmts:
        return None
    snak = stmts[0].get("mainsnak", {})
    val = snak.get("datavalue", {}).get("value")
    if isinstance(val, dict) and "id" in val:
        return val["id"]
    return None


def _chunks(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dry-run", action="store_true", help="Show stats without writing")
    parser.add_argument("--limit", type=int, default=0, help="Patch at most N candidates (0 = all)")
    args = parser.parse_args()

    if not CANDIDATES_FILE.exists():
        print(f"ERROR: {CANDIDATES_FILE} not found. Run 'normalize' first.")
        sys.exit(1)

    # ── Load all candidates ──────────────────────────────────────────────────
    candidates: list[dict] = []
    with CANDIDATES_FILE.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                candidates.append(json.loads(line))
            except Exception:
                pass
    print(f"Loaded {len(candidates)} candidates")

    # ── Identify those missing artist ────────────────────────────────────────
    null_ids = [
        c["id"]
        for c in candidates
        if c.get("source_api") == "wikidata"
        and not c.get("artist")
        and isinstance(c.get("id"), str)
        and c["id"].startswith("Q")
    ]
    if args.limit:
        null_ids = null_ids[: args.limit]
    print(f"  {len(null_ids)} have artist=null (of {len(candidates)} total)")

    if not null_ids:
        print("Nothing to patch.")
        return

    # ── Step 1: fetch P170 (creator) claims for each painting ───────────────
    print(f"\nStep 1: fetching P170 claims for {len(null_ids)} paintings…")
    painting_to_creator: dict[str, str] = {}

    for i, batch in enumerate(_chunks(null_ids, _ENTITY_BATCH), start=1):
        try:
            data = _http_get_json(
                _MW_ENDPOINT,
                {
                    "action":        "wbgetentities",
                    "ids":           "|".join(batch),
                    "props":         "claims",
                    "format":        "json",
                    "formatversion": "2",
                },
            )
            for qid, entity in (data.get("entities") or {}).items():
                creator_id = _claim_entity_id(entity, "P170")
                if creator_id:
                    painting_to_creator[qid] = creator_id
        except Exception as exc:
            print(f"  Batch {i} failed: {exc}")
        time.sleep(_SLEEP)
        print(f"  batch {i}: {len(painting_to_creator)} paintings with creator Q-ID so far…", end="\r")

    print(f"\n  Found P170 for {len(painting_to_creator)} / {len(null_ids)} paintings")

    if not painting_to_creator:
        print("No creator Q-IDs found — nothing to patch.")
        return

    # ── Step 2: resolve creator Q-IDs → English labels ──────────────────────
    creator_ids = list(set(painting_to_creator.values()))
    print(f"\nStep 2: resolving {len(creator_ids)} unique creator Q-IDs…")
    creator_labels: dict[str, str] = {}

    for i, batch in enumerate(_chunks(creator_ids, _ENTITY_BATCH), start=1):
        try:
            data = _http_get_json(
                _MW_ENDPOINT,
                {
                    "action":           "wbgetentities",
                    "ids":              "|".join(batch),
                    "props":            "labels",
                    "languages":        "en",
                    "languagefallback": "1",
                    "format":           "json",
                    "formatversion":    "2",
                },
            )
            for qid, entity in (data.get("entities") or {}).items():
                label = _entity_label(entity)
                if label:
                    creator_labels[qid] = label
        except Exception as exc:
            print(f"  Batch {i} failed: {exc}")
        time.sleep(_SLEEP)

    print(f"  Resolved {len(creator_labels)} / {len(creator_ids)} creator labels")

    # ── Step 3: build painting_id → artist_name ──────────────────────────────
    id_to_artist: dict[str, str] = {}
    for painting_id, creator_id in painting_to_creator.items():
        name = creator_labels.get(creator_id)
        if name:
            id_to_artist[painting_id] = name

    print(f"\n  Will patch {len(id_to_artist)} candidates")

    if args.dry_run:
        print("  Sample (first 10):")
        for pid, name in list(id_to_artist.items())[:10]:
            print(f"    {pid} → {name}")
        print("  (dry-run — not writing)")
        return

    # ── Step 4: write patched file ───────────────────────────────────────────
    print("\nStep 4: writing patched candidates.jsonl…")
    patched = 0
    with CANDIDATES_FILE.open("w", encoding="utf-8") as f:
        for c in candidates:
            if c.get("id") in id_to_artist and not c.get("artist"):
                c["artist"] = id_to_artist[c["id"]]
                patched += 1
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    print(f"\nDone. Patched {patched} / {len(candidates)} candidates → {CANDIDATES_FILE}")
    print("Next step:  python scripts/ingest_wikidata.py ingest")


if __name__ == "__main__":
    main()
