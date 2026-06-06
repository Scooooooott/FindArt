#!/usr/bin/env python3
"""
Wikidata painting corpus ingestion — three independent phases.

Usage:
    python scripts/ingest_wikidata.py fetch      # Phase 1: MW search → raw.jsonl
    python scripts/ingest_wikidata.py normalize  # Phase 2: raw.jsonl → candidates.jsonl
    python scripts/ingest_wikidata.py ingest     # Phase 3: candidates.jsonl → Qdrant

    python scripts/ingest_wikidata.py all        # Run all three phases

Common flags:
    --limit N       Stop after N items (for smoke-testing; 0 = unlimited)
    --resume        Continue from last checkpoint
    --batch-size N  (ingest only) Candidates per embed+upsert call (default 256)

Quick smoke-test:
    python scripts/ingest_wikidata.py all --limit 500

Implementation note — fetch strategy:
    Phase 1 avoids SPARQL entirely.  It uses two separate APIs, both on
    www.wikidata.org (different infrastructure, different rate limits):

      Step A  MediaWiki CirrusSearch  (haswbstatement filter)
              Paginates through all paintings that have a P18 image.
              ~50 Q-IDs per request, offset-based, no SPARQL involved.

      Step B  wbgetentities  (batches of 50)
              Fetches labels + selected claims (creator, date, image
              filename, collection, genre, movement) for the Q-IDs from A.

    Practical limit of CirrusSearch offset pagination is ~10 000 items.
    For a full 200 K+ corpus, rerun with different --srsearch constraints
    (e.g. one run per century) or switch to Wikidata dump processing.
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

# ---------------------------------------------------------------------------
# Path / env bootstrap  (must happen before any app.* imports)
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

# ---------------------------------------------------------------------------
# File layout
# ---------------------------------------------------------------------------
DATA_DIR        = Path(__file__).parent / "data"
RAW_FILE        = DATA_DIR / "wikidata_raw.jsonl"
CANDIDATES_FILE = DATA_DIR / "wikidata_candidates.jsonl"
PROGRESS_FILE   = DATA_DIR / "progress.json"
SEEN_FILE       = DATA_DIR / "seen_ids.txt"

# ---------------------------------------------------------------------------
# Network constants
# ---------------------------------------------------------------------------
_MW_ENDPOINT = "https://www.wikidata.org/w/api.php"
_USER_AGENT  = (
    "FindArtIngest/0.1 "
    "(https://example.invalid/findart; contact@example.invalid)"
)

# CirrusSearch returns max 50 per page; wbgetentities max 50 per call.
_SEARCH_BATCH  = 50
_ENTITY_BATCH  = 50
_SLEEP_SEARCH  = 1.0   # between CirrusSearch pages
_SLEEP_ENTITY  = 0.5   # between wbgetentities batches

# The haswbstatement query: paintings (Q3305213) that have an image (P18).
_SEARCH_QUERY  = "haswbstatement:P31=Q3305213 haswbstatement:P18"

# ---------------------------------------------------------------------------
# SPARQL constants (used by cmd_fetch_sparql)
# ---------------------------------------------------------------------------

_SPARQL_ENDPOINT  = "https://query.wikidata.org/sparql"
_SPARQL_BATCH_SIZE = 5    # artists per query — keeps result set under LIMIT and timeout
_SLEEP_SPARQL      = 65   # seconds between batches (WDQS rate limit: 1 req/min)

# Curated list of major artists whose complete painting corpus we want.
# One SPARQL query per artist; LIMIT 2000 captures virtually all of them.
_SPARQL_ARTISTS: list[str] = [
    # Impressionism & Post-Impressionism
    "Q296",    "Q5582",   "Q39246",  "Q35548",  "Q37693",
    "Q154080", "Q47551",  "Q183147", "Q190604",
    # Dutch / Flemish Golden Age
    "Q41264",  "Q5597",   "Q5599",   "Q150679", "Q167654",
    # Italian Renaissance & Baroque
    "Q762",    "Q5592",   "Q1235",   "Q1164",   "Q5745",   "Q40599",
    # Spanish
    "Q203639", "Q5432",   "Q5580",   "Q46330",
    # French 19th Century
    "Q33477",  "Q151369", "Q36723",  "Q188159",
    # British
    "Q159438", "Q1061998",
    # Japanese
    "Q184226", "Q188399",
    # Early 20th Century / Modern
    "Q5637",   "Q61064",  "Q39631",  "Q5589",
    "Q34661",  "Q191735", "Q38435",  "Q156743", "Q80137",
    # American
    "Q217277", "Q182537", "Q188151", "Q159508",
    # Latin American
    "Q5588",   "Q189597",
    # Northern Renaissance & Other
    "Q471571", "Q315",    "Q219908",
]
# Q296=Monet  Q5582=van Gogh   Q39246=Renoir   Q35548=Cézanne  Q37693=Gauguin
# Q154080=Pissarro  Q47551=Degas  Q183147=Seurat  Q190604=Toulouse-Lautrec
# Q41264=Vermeer  Q5597=Rembrandt  Q5599=Rubens  Q150679=van Dyck  Q167654=Jan van Eyck
# Q762=Leonardo  Q5592=Michelangelo  Q1235=Raphael  Q1164=Botticelli  Q5745=Titian
# Q40599=Caravaggio  Q203639=El Greco  Q5432=Goya  Q5580=Picasso  Q46330=Dalí
# Q33477=Delacroix  Q151369=J-L David  Q36723=Ingres  Q188159=Courbet
# Q159438=Turner  Q1061998=Constable
# Q184226=Hokusai  Q188399=Hiroshige
# Q5637=Magritte  Q61064=Kandinsky  Q39631=Klee  Q5589=Matisse
# Q34661=Klimt  Q191735=Schiele  Q38435=Chagall  Q156743=Miró  Q80137=Munch
# Q217277=O'Keeffe  Q182537=Pollock  Q188151=Rothko  Q159508=Cassatt
# Q5588=Frida Kahlo  Q189597=Diego Rivera
# Q471571=Dürer  Q315=Bruegel  Q219908=Chardin

_SPARQL_QUERY_TEMPLATE = """\
SELECT DISTINCT ?item ?itemLabel ?creatorLabel ?image ?inception ?collectionLabel WHERE {{
  VALUES ?artist {{ {qids} }}
  ?item wdt:P31 wd:Q3305213 ;
        wdt:P170 ?artist ;
        wdt:P18  ?image .
  OPTIONAL {{ ?item wdt:P571 ?inception }}
  OPTIONAL {{ ?item wdt:P195 ?collection }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" }}
}}
LIMIT 2000
"""

SPARQL_FILE = DATA_DIR / "sparql_candidates.jsonl"


# ---------------------------------------------------------------------------
# Low-level HTTP helper
# ---------------------------------------------------------------------------

def _http_get_json(url: str, params: dict) -> dict:
    """GET JSON with retry: 429 → read Retry-After; other errors → exp. back-off."""
    full_url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        full_url,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept":     "application/json",
        },
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                wait = int(exc.headers.get("Retry-After", "60"))
                print(f"  429 rate-limited — waiting {wait}s (attempt {attempt + 1}/5)…")
                time.sleep(wait)
            else:
                raise
        except Exception as exc:
            wait = 10 * (attempt + 1)
            print(f"  Attempt {attempt + 1} failed: {exc}. Retrying in {wait}s…")
            time.sleep(wait)
    raise RuntimeError("Exceeded retry limit — aborting.")


# ---------------------------------------------------------------------------
# Phase 1 — FETCH
#
# Step A: CirrusSearch returns Q-IDs of paintings with P18
# Step B: wbgetentities enriches with labels + claims
# ---------------------------------------------------------------------------

def _search_page(offset: int, limit: int) -> tuple[list[str], bool]:
    """One page of painting Q-IDs via MediaWiki CirrusSearch haswbstatement.
    Returns (q_ids, has_more_pages).
    """
    payload = _http_get_json(
        _MW_ENDPOINT,
        {
            "action":        "query",
            "list":          "search",
            "srsearch":      _SEARCH_QUERY,
            "srnamespace":   "0",
            "srlimit":       str(min(limit, _SEARCH_BATCH)),
            "sroffset":      str(offset),
            "format":        "json",
            "formatversion": "2",
        },
    )
    results = payload.get("query", {}).get("search", [])
    qids = [
        r["title"] for r in results
        if isinstance(r.get("title"), str) and r["title"].startswith("Q")
    ]
    has_more = bool(payload.get("continue"))
    return qids, has_more


def _wbgetentities(ids: list[str], props: str) -> dict[str, dict]:
    """Batch-fetch Wikidata entities via wbgetentities. Returns {qid: entity_dict}.

    Silently skips failed chunks (logs a warning) and rate-limits between batches.
    """
    result: dict[str, dict] = {}
    for i in range(0, len(ids), _ENTITY_BATCH):
        chunk = ids[i : i + _ENTITY_BATCH]
        try:
            data = _http_get_json(
                _MW_ENDPOINT,
                {
                    "action":           "wbgetentities",
                    "ids":              "|".join(chunk),
                    "props":            props,
                    "languages":        "en",
                    "languagefallback": "1",
                    "format":           "json",
                    "formatversion":    "2",
                },
            )
            result.update(data.get("entities") or {})
        except Exception as exc:
            print(f"  wbgetentities batch failed: {exc} — skipping {len(chunk)} items")
            time.sleep(2)
        time.sleep(_SLEEP_ENTITY)
    return result


def _collect_related_ids(painting_entities: dict[str, dict]) -> list[str]:
    """Return Q-IDs of creator/collection/genre/movement referenced by painting entities."""
    related: set[str] = set()
    for entity in painting_entities.values():
        for pid in ("P170", "P195", "P136", "P135"):
            rid = _claim_entity_id(entity, pid)
            if rid:
                related.add(rid)
    return list(related)


def _enrich_bindings(bindings: list[dict]) -> list[dict]:
    """Add labels and claims to minimal bindings via wbgetentities (batches of 50).

    Enriches each binding in-place with underscore-prefixed keys:
      _label, _creator, _date, _image_filename, _collection, _genre, _movement

    Round 1 — fetch painting entities (labels + claims).
    Round 2 — fetch related Q-IDs (creator, collection, genre, movement) to resolve labels.
    """
    qid_map = {
        b["_qid"]: b
        for b in bindings
        if b.get("_qid", "").startswith("Q")
    }

    # Round 1: painting entities (labels + claims)
    painting_entities = _wbgetentities(list(qid_map.keys()), "labels|claims")

    # Round 2: labels for related entities (creator, collection, genre, movement)
    related_entities = _wbgetentities(_collect_related_ids(painting_entities), "labels")
    related_labels = {rid: _entity_label(e) for rid, e in related_entities.items()}

    # Merge resolved data back into each binding
    for qid, entity in painting_entities.items():
        if qid not in qid_map:
            continue
        b = qid_map[qid]
        b["_label"]          = _entity_label(entity)
        b["_image_filename"] = _claim_str(entity, "P18")
        b["_date"]           = _claim_str(entity, "P571")
        b["_creator"]        = related_labels.get(_claim_entity_id(entity, "P170"))
        b["_collection"]     = related_labels.get(_claim_entity_id(entity, "P195"))
        b["_genre"]          = related_labels.get(_claim_entity_id(entity, "P136"))
        b["_movement"]       = related_labels.get(_claim_entity_id(entity, "P135"))

    return bindings


def _entity_label(entity: dict) -> str | None:
    labels = entity.get("labels") or {}
    en = labels.get("en")
    if isinstance(en, dict) and en.get("value"):
        return en["value"]
    for v in labels.values():
        if isinstance(v, dict) and v.get("value"):
            return v["value"]
    return None


def _first_snak(entity: dict, pid: str) -> dict:
    stmts = (entity.get("claims") or {}).get(pid, [])
    return stmts[0].get("mainsnak", {}) if stmts else {}


def _claim_str(entity: dict, pid: str) -> str | None:
    """Return string/commonsMedia/time datavalue as a plain string."""
    snak = _first_snak(entity, pid)
    dv = snak.get("datavalue", {})
    val = dv.get("value")
    if isinstance(val, str):
        return val
    if isinstance(val, dict) and "time" in val:
        return val["time"]
    return None


def _claim_entity_id(entity: dict, pid: str) -> str | None:
    """Return the Q-ID of an entity-type claim value."""
    snak = _first_snak(entity, pid)
    dv = snak.get("datavalue", {})
    val = dv.get("value")
    if isinstance(val, dict) and "id" in val:
        return val["id"]
    return None


# ---------------------------------------------------------------------------
# SPARQL helpers
# ---------------------------------------------------------------------------

def _sleep_countdown(seconds: int) -> None:
    """Sleep for `seconds` with a live countdown printed every 10 s."""
    for remaining in range(seconds, 0, -10):
        print(f"\r  {remaining:4d}s remaining…", end="", flush=True)
        time.sleep(min(10, remaining))
    print("\r  done waiting.          ", flush=True)


def _sparql_query(query: str) -> list[dict]:
    """Run a SPARQL query against Wikidata, respecting Retry-After on 429."""
    url = _SPARQL_ENDPOINT + "?" + urllib.parse.urlencode({"query": query, "format": "json"})
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept":     "application/sparql-results+json",
        },
    )
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=65) as resp:
                data = json.loads(resp.read().decode())
            return data.get("results", {}).get("bindings", [])
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                wait = int(exc.headers.get("Retry-After", str(_SLEEP_SPARQL)))
                print(f"\n  429 — waiting {wait}s (attempt {attempt + 1}/6)…", flush=True)
                _sleep_countdown(wait + 2)
            else:
                raise
        except Exception as exc:
            wait = 20 * (attempt + 1)
            print(f"\n  Attempt {attempt + 1} failed: {exc}. Retrying in {wait}s…", flush=True)
            time.sleep(wait)
    raise RuntimeError("Exceeded SPARQL retry limit")


def _filename_from_sparql_image(url: str) -> str | None:
    """Extract a Commons filename from a SPARQL wdt:P18 URI.

    Wikidata SPARQL returns P18 as:
      http://commons.wikimedia.org/wiki/Special:FilePath/Mona_Lisa.jpg
    → "Mona Lisa.jpg"  (spaces restored, percent-encoding decoded)
    """
    if "Special:FilePath/" not in url:
        return None
    raw = url.split("Special:FilePath/")[-1].split("?")[0]
    decoded = urllib.parse.unquote(raw)
    return decoded.replace("_", " ").strip() or None


def _sparql_label(binding: dict, key: str, wikidata_id: str = "") -> str | None:
    """Extract a label from a SPARQL binding value, filtering fallback Q-numbers."""
    val = binding.get(key, {}).get("value", "")
    if not val or (val.startswith("Q") and val[1:].isdigit()):
        return None
    # Skip if wikibase:label fell back to the item's own Q-number
    if val == wikidata_id:
        return None
    return val


def _normalize_sparql_binding(b: dict) -> dict | None:
    """Normalize one SPARQL result binding to an ArtworkCandidate-compatible dict.

    SPARQL already returns resolved labels (via wikibase:label), so no
    second wbgetentities round-trip is needed — this is simpler and faster
    than the CirrusSearch path.
    """
    item_uri    = b.get("item", {}).get("value", "")
    wikidata_id = item_uri.rstrip("/").split("/")[-1]
    if not wikidata_id.startswith("Q"):
        return None

    title = _sparql_label(b, "itemLabel", wikidata_id)
    if not title:
        return None

    image_url = b.get("image", {}).get("value", "")
    filename  = _filename_from_sparql_image(image_url)
    if not filename:
        return None

    creator    = _sparql_label(b, "creatorLabel")
    collection = _sparql_label(b, "collectionLabel")

    inception = b.get("inception", {}).get("value", "")
    year: str | None = None
    if inception:
        y = inception.lstrip("+").split("-")[0]
        year = y[:4] if y else None

    metadata: dict = {}
    if collection:
        metadata["collection"] = collection

    return {
        "id":                   wikidata_id,
        "source_api":           "wikidata",
        "provider_id":          "wikidata",
        "provider_object_id":   wikidata_id,
        "title":                title,
        "artist":               creator,
        "year":                 year,
        "thumbnail_url":        _commons_url(filename, 400),
        "image_url":            _commons_url(filename, 2000),
        "source_url":           item_uri or None,
        "detail_url":           _commons_file_page(filename),
        "wikidata_id":          wikidata_id,
        "wikidata_url":         item_uri or None,
        "commons_filename":     filename,
        "is_public_domain":     None,
        "license_status":       "commons",
        "image_available":      True,
        "free_image_available": True,
        "image_refs": {
            "commons_file":      filename,
            "commons_thumbnail": _commons_url(filename, 400),
            "commons_medium":    _commons_url(filename, 2000),
        },
        "capabilities":    {"supports_region": False, "supports_iiif": False},
        "matched_sources": ["wikidata"],
        "metadata":        metadata,
    }


def _write_sparql_candidates(
    bindings: list[dict],
    seen: set[str],
    out,
    limit: int,
    total: int,
) -> tuple[int, int]:
    """Normalise and write new candidates from one SPARQL batch.

    Returns (written_this_batch, new_total).
    """
    written = 0
    for b in bindings:
        if limit and total >= limit:
            break
        candidate = _normalize_sparql_binding(b)
        if candidate is None or candidate["id"] in seen:
            continue
        out.write(json.dumps(candidate, ensure_ascii=False) + "\n")
        seen.add(candidate["id"])
        written += 1
        total += 1
    return written, total


def cmd_fetch_sparql(args: argparse.Namespace) -> None:
    """Fetch paintings for curated artist list via SPARQL → sparql_candidates.jsonl.

    Groups artists into batches of _SPARQL_BATCH_SIZE per query to reduce
    total request count (WDQS rate-limits to ~1 req/min during high load).
    Labels are already resolved by wikibase:label — no separate normalize step.
    Run build_vector_index.py afterwards.
    """
    DATA_DIR.mkdir(exist_ok=True)

    seen: set[str] = set()
    if args.resume and SPARQL_FILE.exists():
        with SPARQL_FILE.open(encoding="utf-8") as f:
            for line in f:
                try:
                    seen.add(json.loads(line)["id"])
                except Exception:
                    pass
        print(f"Resuming — {len(seen)} IDs already in {SPARQL_FILE}")

    limit = args.limit or 0
    total = 0

    batches = [
        _SPARQL_ARTISTS[i : i + _SPARQL_BATCH_SIZE]
        for i in range(0, len(_SPARQL_ARTISTS), _SPARQL_BATCH_SIZE)
    ]
    n_batches = len(batches)
    print(f"{len(_SPARQL_ARTISTS)} artists → {n_batches} batches of {_SPARQL_BATCH_SIZE}")
    print(f"Estimated time: {n_batches} × {_SLEEP_SPARQL}s ≈ {n_batches * _SLEEP_SPARQL // 60} min\n")

    with SPARQL_FILE.open("a" if args.resume else "w", encoding="utf-8") as out:
        for batch_no, batch in enumerate(batches, start=1):
            if limit and total >= limit:
                break

            qids = " ".join(f"wd:{q}" for q in batch)
            query = _SPARQL_QUERY_TEMPLATE.format(qids=qids)
            print(f"[{batch_no:2d}/{n_batches}] {', '.join(batch)}…", end=" ", flush=True)

            try:
                bindings = _sparql_query(query)
            except Exception as exc:
                print(f"FAILED ({exc}) — skipping batch")
                continue

            written, total = _write_sparql_candidates(bindings, seen, out, limit, total)
            print(f"{written} new  (total {total})")

            if batch_no < n_batches and not (limit and total >= limit):
                _sleep_countdown(_SLEEP_SPARQL)

    print(f"\nSPARQL fetch done. {total} candidates → {SPARQL_FILE}")
    print("Next: python scripts/build_vector_index.py")


def _resume_fetch_state(args: argparse.Namespace) -> tuple[int, int]:
    """Load fetch checkpoint if --resume is set. Returns (offset, total_fetched)."""
    if args.resume and PROGRESS_FILE.exists():
        prog = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        if prog.get("phase") == "fetch":
            offset        = prog.get("offset", 0)
            total_fetched = prog.get("total_fetched", 0)
            print(f"Resuming from offset {offset} ({total_fetched} already fetched)")
            return offset, total_fetched
    return 0, 0


def _fetch_and_enrich_page(offset: int, page_size: int) -> tuple[list[dict], bool, int]:
    """One CirrusSearch page → enriched+filtered bindings.

    Returns (bindings_with_image, has_more, raw_qid_count).
    raw_qid_count drives offset advancement even when some items are filtered out.
    """
    qids, has_more = _search_page(offset, page_size)
    if not qids:
        return [], False, 0

    print(f"  Enriching {len(qids)} items…")
    bindings = [
        {"_qid": qid, "item": {"value": f"http://www.wikidata.org/entity/{qid}"}}
        for qid in qids
    ]
    bindings = _enrich_bindings(bindings)

    before   = len(bindings)
    bindings = [b for b in bindings if b.get("_image_filename")]
    if before != len(bindings):
        print(f"  Dropped {before - len(bindings)} items without image filename")

    return bindings, has_more, len(qids)


def cmd_fetch(args: argparse.Namespace) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    offset, total_fetched = _resume_fetch_state(args)

    if not args.resume and RAW_FILE.exists():
        RAW_FILE.unlink()

    limit = args.limit or 0

    with RAW_FILE.open("a" if args.resume else "w", encoding="utf-8") as out:
        while True:
            if limit and total_fetched >= limit:
                print(f"Reached --limit {limit}.")
                break

            page_size = min(_SEARCH_BATCH, limit - total_fetched) if limit else _SEARCH_BATCH
            print(f"Searching offset={offset}, page_size={page_size} "
                  f"(total so far: {total_fetched})…")

            bindings, has_more, raw_count = _fetch_and_enrich_page(offset, page_size)
            if not raw_count:
                print("No more results.")
                break

            for b in bindings:
                out.write(json.dumps(b, ensure_ascii=False) + "\n")

            total_fetched += len(bindings)
            offset        += raw_count

            PROGRESS_FILE.write_text(json.dumps({
                "phase":         "fetch",
                "offset":        offset,
                "total_fetched": total_fetched,
            }), encoding="utf-8")

            print(f"  → {len(bindings)} written, running total {total_fetched}")

            if not has_more:
                print("Last page reached — fetch complete.")
                break

            time.sleep(_SLEEP_SEARCH)

    print(f"\nFetch done.  {total_fetched} enriched bindings  →  {RAW_FILE}")


# ---------------------------------------------------------------------------
# Phase 2 — NORMALIZE
# ---------------------------------------------------------------------------

def _commons_url(filename: str | None, width: int) -> str | None:
    if not filename:
        return None
    from urllib.parse import quote
    return (
        f"https://commons.wikimedia.org/wiki/Special:FilePath/"
        f"{quote(filename, safe='')}?width={width}"
    )


def _commons_file_page(filename: str | None) -> str | None:
    if not filename:
        return None
    from urllib.parse import quote
    return (
        f"https://commons.wikimedia.org/wiki/File:"
        f"{quote(filename.replace(' ', '_'), safe='')}"
    )


def _clean_title(filename: str | None) -> str | None:
    if not filename:
        return None
    stem = filename.rsplit("/", 1)[-1]
    if "." in stem:
        stem = stem.rsplit(".", 1)[0]
    return stem.replace("_", " ").strip() or None


def _normalize_binding(binding: dict) -> dict | None:
    """Return an ArtworkCandidate-compatible dict, or None to skip."""
    item_uri    = (binding.get("item") or {}).get("value", "")
    wikidata_id = binding.get("_qid") or item_uri.rstrip("/").split("/")[-1]
    if not wikidata_id.startswith("Q"):
        return None

    # Image filename: either enriched from wbgetentities or from SPARQL legacy
    filename = binding.get("_image_filename")
    if not filename:
        return None

    title = binding.get("_label") or _clean_title(filename)
    if not title:
        return None

    # Date: "+1665-00-00T00:00:00Z" → "1665"
    raw_date = binding.get("_date") or ""
    year: str | None = None
    if raw_date:
        y = raw_date.lstrip("+").split("-")[0]
        year = y[:4] if y else None

    collection = binding.get("_collection")
    genre      = binding.get("_genre")
    movement   = binding.get("_movement")

    metadata: dict = {}
    if collection:
        metadata["collection"] = collection
    if genre:
        metadata["genre"] = genre
    if movement:
        metadata["movement"] = movement

    return {
        "id":                   wikidata_id,
        "source_api":           "wikidata",
        "provider_id":          "wikidata",
        "provider_object_id":   wikidata_id,
        "title":                title,
        "artist":               binding.get("_creator"),
        "year":                 year,
        "thumbnail_url":        _commons_url(filename, 400),
        "image_url":            _commons_url(filename, 2000),
        "source_url":           item_uri or None,
        "detail_url":           _commons_file_page(filename),
        "wikidata_id":          wikidata_id,
        "wikidata_url":         item_uri or None,
        "commons_filename":     filename,
        "is_public_domain":     None,
        "license_status":       "commons",
        "image_available":      True,
        "free_image_available": True,
        "image_refs": {
            "commons_file":      filename,
            "commons_thumbnail": _commons_url(filename, 400),
            "commons_medium":    _commons_url(filename, 2000),
        },
        "capabilities":    {"supports_region": False, "supports_iiif": False},
        "matched_sources": ["wikidata"],
        "metadata":        metadata,
    }


def cmd_normalize(args: argparse.Namespace) -> None:
    if not RAW_FILE.exists():
        print(f"ERROR: {RAW_FILE} not found. Run 'fetch' first.")
        sys.exit(1)

    limit = args.limit or 0
    total = skipped = written = 0

    seen: set[str] = set()
    if args.resume and SEEN_FILE.exists():
        seen = set(SEEN_FILE.read_text(encoding="utf-8").splitlines())
        print(f"Loaded {len(seen)} already-seen IDs")

    if not args.resume:
        CANDIDATES_FILE.write_text("", encoding="utf-8")
        SEEN_FILE.write_text("", encoding="utf-8")

    with (
        RAW_FILE.open(encoding="utf-8") as src,
        CANDIDATES_FILE.open("a", encoding="utf-8") as dst,
        SEEN_FILE.open("a", encoding="utf-8") as seen_out,
    ):
        for line in src:
            total += 1
            try:
                candidate = _normalize_binding(json.loads(line))
            except Exception:
                skipped += 1
                continue

            if candidate is None:
                skipped += 1
                continue

            cid = candidate["id"]
            if cid in seen:
                skipped += 1
                continue
            seen.add(cid)
            seen_out.write(cid + "\n")

            dst.write(json.dumps(candidate, ensure_ascii=False) + "\n")
            written += 1

            if limit and written >= limit:
                break

    print(
        f"Normalize done.  {total} raw  →  {written} candidates  "
        f"({skipped} skipped)  →  {CANDIDATES_FILE}"
    )


# ---------------------------------------------------------------------------
# Phase 3 — INGEST
# ---------------------------------------------------------------------------

def _load_ingest_progress(args: argparse.Namespace) -> tuple[int, int]:
    """Load ingest checkpoint if --resume is set. Returns (start_offset, already_upserted)."""
    if args.resume and PROGRESS_FILE.exists():
        prog = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        if prog.get("phase") == "ingest":
            start_offset = prog.get("ingest_offset", 0)
            already      = prog.get("ingest_total", 0)
            print(f"Resuming ingest from line {start_offset} ({already} already upserted)")
            return start_offset, already
    return 0, 0


def _flush_ingest_batch(svc, batch: list, line_no: int, total_so_far: int) -> int:
    """Upsert batch to Qdrant, save progress, and clear the batch. Returns count upserted."""
    n = svc.seed_from_candidates(batch)
    batch.clear()
    PROGRESS_FILE.write_text(json.dumps({
        "phase":         "ingest",
        "ingest_offset": line_no + 1,
        "ingest_total":  total_so_far + n,
    }), encoding="utf-8")
    return n


def cmd_ingest(args: argparse.Namespace) -> None:
    if not CANDIDATES_FILE.exists():
        print(f"ERROR: {CANDIDATES_FILE} not found. Run 'normalize' first.")
        sys.exit(1)

    from app.models import ArtworkCandidate
    from app.services.vector_search import (
        QdrantVectorSearchService,
        create_vector_search_service,
    )

    svc = create_vector_search_service()
    if not isinstance(svc, QdrantVectorSearchService):
        print(
            "ERROR: Qdrant is not available.\n"
            "  Set QDRANT_URL in .env and retry.\n"
            "  Quick start:  docker run -p 6333:6333 qdrant/qdrant"
        )
        sys.exit(1)

    limit        = args.limit or 0
    batch_size   = args.batch_size
    start_offset, _ = _load_ingest_progress(args)

    batch: list[ArtworkCandidate] = []
    total   = 0
    errors  = 0
    line_no = max(start_offset - 1, 0)

    with CANDIDATES_FILE.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f):
            if line_no < start_offset:
                continue
            if limit and (total + len(batch)) >= limit:
                break
            try:
                candidate = ArtworkCandidate.model_validate(json.loads(line))
                batch.append(candidate)
            except Exception:
                errors += 1
                continue

            if len(batch) >= batch_size:
                total += _flush_ingest_batch(svc, batch, line_no, total)
                print(f"  {total} upserted…", end="\r", flush=True)

        if batch:
            total += _flush_ingest_batch(svc, batch, line_no, total)

    print(f"\nIngest done.  {total} candidates upserted  ({errors} parse errors).")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--limit", type=int, default=0,
                   metavar="N", help="Stop after N items (0 = all)")
    p.add_argument("--resume", action="store_true",
                   help="Continue from last checkpoint")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Wikidata painting corpus ingestion pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("sparql", help="Fetch top-50 artists via SPARQL → sparql_candidates.jsonl (recommended)")
    _add_common(p)

    p = sub.add_parser("fetch", help="Phase 1 (CirrusSearch): MW search + wbgetentities → raw.jsonl")
    _add_common(p)

    p = sub.add_parser("normalize", help="Phase 2: raw.jsonl → candidates.jsonl")
    _add_common(p)

    p = sub.add_parser("ingest", help="Phase 3: candidates.jsonl → Qdrant")
    _add_common(p)
    p.add_argument("--batch-size", type=int, default=256, dest="batch_size",
                   metavar="N", help="Candidates per embed+upsert call (default 256)")

    p = sub.add_parser("all", help="Run CirrusSearch fetch → normalize → ingest")
    _add_common(p)
    p.add_argument("--batch-size", type=int, default=256, dest="batch_size", metavar="N")

    args = parser.parse_args()
    if not hasattr(args, "batch_size"):
        args.batch_size = 256

    if args.cmd == "sparql":
        cmd_fetch_sparql(args)
    elif args.cmd == "fetch":
        cmd_fetch(args)
    elif args.cmd == "normalize":
        cmd_normalize(args)
    elif args.cmd == "ingest":
        cmd_ingest(args)
    elif args.cmd == "all":
        cmd_fetch(args)
        cmd_normalize(args)
        cmd_ingest(args)


if __name__ == "__main__":
    main()
