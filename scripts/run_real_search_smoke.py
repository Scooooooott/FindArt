from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.models import ArtworkCandidate, ArtworkQuery  # noqa: E402
from app.providers import (  # noqa: E402
    AicProvider,
    CmaProvider,
    MetProvider,
    RijksProvider,
    WikiProvider,
)
from app.services.aggregation import aggregate_candidates  # noqa: E402
from app.services.museum import build_museum_search_service  # noqa: E402

REAL_CASES: dict[str, ArtworkQuery] = {
    "cma": ArtworkQuery(raw_text="water lilies monet", title="Water Lilies", artist="Monet"),
    "aic": ArtworkQuery(raw_text="Paris Street Rainy Day", title="Paris Street; Rainy Day"),
    "met": ArtworkQuery(
        raw_text="Wheat Field with Cypresses van Gogh",
        title="Wheat Field with Cypresses",
        artist="Vincent van Gogh",
    ),
    "rijks": ArtworkQuery(raw_text="Night Watch Rembrandt", title="Night Watch", artist="Rembrandt van Rijn"),
    "wiki": ArtworkQuery(raw_text="The Great Wave off Kanagawa", title="The Great Wave off Kanagawa"),
}


PROVIDERS = {
    "cma": CmaProvider,
    "aic": AicProvider,
    "met": MetProvider,
    "rijks": RijksProvider,
    "wiki": WikiProvider,
    "wikidata": WikiProvider,
}


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run live search smoke tests against museum/Wiki APIs.")
    parser.add_argument(
        "--provider",
        choices=[*PROVIDERS.keys(), "all"],
        default="all",
        help="Provider to call. Defaults to all providers.",
    )
    parser.add_argument("--limit", type=int, default=3, help="Result limit per provider.")
    parser.add_argument(
        "--pipeline",
        action="store_true",
        help="Also run the combined external provider search and aggregation.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON instead of a compact human-readable report.",
    )
    args = parser.parse_args()

    provider_names = ["cma", "aic", "met", "rijks", "wiki"] if args.provider == "all" else [args.provider]
    report: dict[str, Any] = {}

    for provider_name in provider_names:
        query = REAL_CASES["wiki" if provider_name == "wikidata" else provider_name]
        provider = PROVIDERS[provider_name]()
        try:
            candidates = await provider.search(query, limit=args.limit)
            report[provider_name] = {
                "query": query.model_dump(mode="json"),
                "count": len(candidates),
                "candidates": [_summarize(candidate) for candidate in candidates],
            }
        except Exception as exc:
            report[provider_name] = {
                "query": query.model_dump(mode="json"),
                "error": f"{type(exc).__name__}: {exc}",
            }

    if args.pipeline:
        pipeline_query = REAL_CASES["wiki"]
        service = build_museum_search_service(include_default=False, include_external=True)
        try:
            provider_candidates = await service.search(pipeline_query, limit=args.limit)
            aggregated = aggregate_candidates([provider_candidates], limit=args.limit)
            report["combined_pipeline"] = {
                "query": pipeline_query.model_dump(mode="json"),
                "warnings": service.last_warnings,
                "count": len(aggregated),
                "candidates": [_summarize(candidate) for candidate in aggregated],
            }
        except Exception as exc:
            report["combined_pipeline"] = {
                "query": pipeline_query.model_dump(mode="json"),
                "error": f"{type(exc).__name__}: {exc}",
            }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_report(report)

    return 0


def _summarize(candidate: ArtworkCandidate) -> dict[str, Any]:
    return {
        "provider_id": candidate.provider_id,
        "id": candidate.id,
        "title": candidate.title,
        "artist": candidate.artist,
        "year": candidate.year,
        "thumbnail_url": candidate.thumbnail_url,
        "source_url": candidate.source_url,
        "detail_url": candidate.detail_url,
        "provider_image_id": candidate.provider_image_id,
        "wikidata_id": candidate.wikidata_id,
        "commons_filename": candidate.commons_filename,
        "license_status": candidate.license_status,
        "image_available": candidate.image_available,
        "free_image_available": candidate.free_image_available,
        "capabilities": candidate.capabilities,
        "image_refs": candidate.image_refs,
        "score": candidate.score,
    }


def _print_report(report: dict[str, Any]) -> None:
    for provider_name, payload in report.items():
        print(f"\n## {provider_name}")
        if "error" in payload:
            print(f"ERROR: {payload['error']}")
            continue

        query = payload["query"]
        print(f"query: {query.get('title') or query.get('raw_text')}")
        print(f"count: {payload['count']}")
        warnings = payload.get("warnings")
        if warnings:
            print(f"warnings: {warnings}")

        for index, candidate in enumerate(payload["candidates"], start=1):
            print(f"{index}. {candidate['title']} | {candidate.get('artist') or '-'} | {candidate.get('year') or '-'}")
            print(
                f"   provider={candidate['provider_id']} id={candidate['id']}"
                f" image_id={candidate.get('provider_image_id')}"
            )
            print(
                "   image_available="
                f"{candidate.get('image_available')} free={candidate.get('free_image_available')} "
                f"license={candidate.get('license_status')}"
            )
            print(f"   source={candidate.get('source_url')}")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
