#!/usr/bin/env python
"""
Build (or refresh) the vector search index in a persistent Qdrant instance.

For in-memory development, this script is not needed — the API server
auto-seeds from DEFAULT_CATALOG on startup. Run this script when you have
a real Qdrant URL (Docker or Qdrant Cloud) and want to populate it.

Usage (from project root):
    python scripts/build_vector_index.py
    python scripts/build_vector_index.py --clear    # wipe and rebuild

Environment variables (read from .env):
    QDRANT_URL        Qdrant server URL (required for persistent indexing)
    QDRANT_API_KEY    Optional API key
    EMBEDDING_MODEL   sentence-transformers model name
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger("build_index")


def _check_sentence_transformers() -> None:
    try:
        from sentence_transformers import SentenceTransformer  # noqa: F401
    except ImportError:
        logger.error("sentence-transformers not installed. Run: pip install sentence-transformers")
        sys.exit(1)


def _connect_qdrant(url: str, api_key: str | None):
    """Return a QdrantClient for url, or an in-memory client if url is empty."""
    try:
        from qdrant_client import QdrantClient
    except ImportError:
        logger.error("qdrant-client not installed. Run: pip install qdrant-client")
        sys.exit(1)

    if not url:
        logger.warning(
            "QDRANT_URL is not set — running in-memory. "
            "Data will be lost when this script exits. "
            "Set QDRANT_URL in .env to index into a persistent Qdrant instance."
        )
        return QdrantClient(":memory:")

    logger.info("Connecting to Qdrant at %s", url)
    return QdrantClient(url=url, api_key=api_key)


def _ingest_jsonl(path: Path, label: str, service) -> tuple[int, int]:
    """Load ArtworkCandidate records from a JSONL file and upsert into Qdrant.

    Returns (upserted_count, error_count).
    """
    from app.models import ArtworkCandidate

    if not path.exists():
        logger.info("%s skipped: %s not found.", label, path)
        return 0, 0

    logger.info("Found %s — ingesting…", path)
    batch: list[ArtworkCandidate] = []
    total = errors = 0
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                batch.append(ArtworkCandidate.model_validate(json.loads(line)))
            except Exception:
                errors += 1
                continue
            if len(batch) >= 256:
                total += service.seed_from_candidates(batch)
                batch.clear()
                logger.info("  %d %s points upserted…", total, label)
    if batch:
        total += service.seed_from_candidates(batch)
    logger.info("%s done: %d candidates (%d parse errors)", label, total, errors)
    return total, errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--clear", action="store_true", help="Delete existing collection and rebuild from scratch")
    args = parser.parse_args()

    _check_sentence_transformers()

    from app.data.default_catalog import DEFAULT_CATALOG
    from app.services.vector_search import COLLECTION_NAME, QdrantVectorSearchService

    qdrant_url = os.getenv("QDRANT_URL", "").strip()
    qdrant_api_key = os.getenv("QDRANT_API_KEY", "").strip() or None
    model_name = os.getenv("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")

    client = _connect_qdrant(qdrant_url, qdrant_api_key)

    if args.clear:
        try:
            client.delete_collection(COLLECTION_NAME)
            logger.info("Deleted existing collection '%s'", COLLECTION_NAME)
        except Exception:
            pass  # collection did not exist yet

    logger.info("Loading embedding model: %s", model_name)
    service = QdrantVectorSearchService(client=client, model_name=model_name)

    # ── Tier 1: DEFAULT_CATALOG ──────────────────────────────────────────────
    logger.info("Indexing %d items from DEFAULT_CATALOG ...", len(DEFAULT_CATALOG))
    n = service.seed_from_catalog(list(DEFAULT_CATALOG))
    logger.info("Tier 1 done: %d items indexed", n)

    # ── Tier 2a: SPARQL candidates (top-50 artists, recommended) ─────────────
    sparql_file = Path(__file__).parent / "data" / "sparql_candidates.jsonl"
    _ingest_jsonl(sparql_file, "Tier 2a SPARQL", service)

    # ── Tier 2b: CirrusSearch candidates (ingest_wikidata.py fetch+normalize) ─
    wikidata_file = Path(__file__).parent / "data" / "wikidata_candidates.jsonl"
    _ingest_jsonl(wikidata_file, "Tier 2b CirrusSearch", service)

    if not sparql_file.exists() and not wikidata_file.exists():
        logger.info(
            "Tip: run 'python scripts/ingest_wikidata.py sparql' to build the corpus."
        )

    # ── Tier 3: Museum API seeding (auto-grows via pipeline._seed_new_candidates) ─

    count = client.count(collection_name=COLLECTION_NAME).count
    logger.info("Collection '%s' now has %d points total", COLLECTION_NAME, count)


if __name__ == "__main__":
    main()
