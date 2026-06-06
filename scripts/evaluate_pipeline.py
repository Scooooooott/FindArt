#!/usr/bin/env python
"""
Evaluate the full SearchPipeline against a set of known-answer test cases.

Metrics reported per case:
  Hit@1/3/5  — correct result appears in top-k candidates
  RR         — Reciprocal Rank (1/rank of first correct hit, 0 if not found)
  Fallback   — which fallback strategy fired (Layer 2)
  ms         — wall-clock latency

Usage (from project root):
    python scripts/evaluate_pipeline.py
    python scripts/evaluate_pipeline.py --limit 5
    python scripts/evaluate_pipeline.py --verbose
    python scripts/evaluate_pipeline.py --cases backend/tests/eval_cases.json
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import logging
import sys
import time

# Force UTF-8 output on Windows (avoids GBK encoding errors for CJK/symbols)
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

logging.basicConfig(level=logging.WARNING, format="%(levelname)s  %(message)s")

from app.models import ArtworkCandidate  # noqa: E402
from app.services.museum import build_museum_search_service  # noqa: E402
from app.services.pipeline import SearchPipeline  # noqa: E402

# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    return text.lower().strip()


def is_match(
    candidate: ArtworkCandidate,
    expected_title: str | None,
    expected_artist: str | None,
) -> bool:
    """Return True if the candidate satisfies either the title or artist expectation."""
    if expected_title:
        if _normalise(expected_title) in _normalise(candidate.title):
            return True
    if expected_artist and candidate.artist:
        if _normalise(expected_artist) in _normalise(candidate.artist):
            return True
    return False


def reciprocal_rank(
    candidates: list[ArtworkCandidate],
    expected_title: str | None,
    expected_artist: str | None,
) -> float:
    for i, c in enumerate(candidates):
        if is_match(c, expected_title, expected_artist):
            return 1.0 / (i + 1)
    return 0.0


# ---------------------------------------------------------------------------
# Evaluation runner
# ---------------------------------------------------------------------------

async def _run_case(
    pipeline: SearchPipeline,
    case: dict,
) -> tuple[dict, list[ArtworkCandidate] | None]:
    """Run a single eval case. Returns (row_dict, candidates) or (error_row, None)."""
    text = case["input"]
    exp_title = case.get("expected_title")
    exp_artist = case.get("expected_artist")
    category = case.get("category", "")

    try:
        t0 = time.perf_counter()
        response = await pipeline.search(text, limit=5)
        elapsed_ms = round((time.perf_counter() - t0) * 1000)
    except Exception as exc:
        return {
            "input": text, "category": category,
            "h1": False, "h3": False, "h5": False, "rr": 0.0,
            "fallback": "error", "ms": 0, "n": 0,
            "error": str(exc),
        }, None

    candidates = response.candidates
    return {
        "input": text, "category": category,
        "h1": any(is_match(c, exp_title, exp_artist) for c in candidates[:1]),
        "h3": any(is_match(c, exp_title, exp_artist) for c in candidates[:3]),
        "h5": any(is_match(c, exp_title, exp_artist) for c in candidates[:5]),
        "rr": reciprocal_rank(candidates, exp_title, exp_artist),
        "fallback": response.diagnostics.fallback_mode or "-",
        "ms": elapsed_ms,
        "n": len(candidates),
    }, candidates


async def run_evaluation(cases: list[dict], verbose: bool) -> None:
    pipeline = SearchPipeline(
        museum_search=build_museum_search_service(include_default=False)
    )
    rows: list[dict] = []

    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case['input']} ...", end=" ", flush=True)
        row, candidates = await _run_case(pipeline, case)
        rows.append(row)

        if candidates is None:
            print(f"ERROR: {row['error']}")
            continue

        h1, h3, h5 = row["h1"], row["h3"], row["h5"]
        print(f"H@1={'Y' if h1 else 'N'}  H@3={'Y' if h3 else 'N'}  H@5={'Y' if h5 else 'N'}  {row['ms']}ms")

        if verbose and candidates:
            exp_title = case.get("expected_title")
            exp_artist = case.get("expected_artist")
            for rank, c in enumerate(candidates[:3], 1):
                marker = "+" if is_match(c, exp_title, exp_artist) else " "
                print(f"    {marker} #{rank} {c.title!r}  {c.artist or '?'}  [{c.source_api}]")

    _print_summary(rows)


def _print_summary(rows: list[dict]) -> None:
    W = 30
    print()
    header = f"{'输入':<{W}} {'类型':<8} {'H@1':<5} {'H@3':<5} {'H@5':<5} {'RR':<6} {'降级':<16} {'n':>3} {'ms':>6}"
    print(header)
    print("─" * len(header))

    for r in rows:
        h1 = "Y" if r["h1"] else "N"
        h3 = "Y" if r["h3"] else "N"
        h5 = "Y" if r["h5"] else "N"
        err = " !" if r.get("error") else ""
        print(
            f"{r['input'][:W]:<{W}} {r['category']:<8} "
            f"{h1:<5} {h3:<5} {h5:<5} {r['rr']:<6.2f} "
            f"{r['fallback']:<16} {r['n']:>3} {r['ms']:>6}{err}"
        )

    valid = [r for r in rows if not r.get("error")]
    n = len(valid)
    if n == 0:
        print("\n全部用例执行失败。")
        return

    hit1 = sum(r["h1"] for r in valid) / n
    hit3 = sum(r["h3"] for r in valid) / n
    hit5 = sum(r["h5"] for r in valid) / n
    mrr  = sum(r["rr"] for r in valid) / n
    avg_ms = sum(r["ms"] for r in valid) / n
    fallback_rate = sum(r["fallback"] != "-" for r in valid) / n

    print("─" * len(header))
    print(f"\n总计 {len(rows)} 条（{len(rows) - n} 条出错）")
    print(f"Hit@1={hit1:.0%}  Hit@3={hit3:.0%}  Hit@5={hit5:.0%}  MRR={mrr:.2f}")
    print(f"降级触发率={fallback_rate:.0%}  平均耗时={avg_ms:.0f}ms")

    # Per-category breakdown
    categories = sorted({r["category"] for r in valid})
    if len(categories) > 1:
        print("\n── 分类详情 ──")
        for cat in categories:
            sub = [r for r in valid if r["category"] == cat]
            ns = len(sub)
            print(
                f"  {cat:<10} n={ns}  "
                f"H@1={sum(r['h1'] for r in sub)/ns:.0%}  "
                f"H@3={sum(r['h3'] for r in sub)/ns:.0%}  "
                f"H@5={sum(r['h5'] for r in sub)/ns:.0%}"
            )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate FindArt search pipeline")
    parser.add_argument(
        "--cases",
        default=str(ROOT / "backend" / "tests" / "eval_cases.json"),
        help="Path to eval_cases.json",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Run only the first N cases",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Show top-3 candidates for each case",
    )
    args = parser.parse_args()

    with open(args.cases, encoding="utf-8") as f:
        cases = json.load(f)

    if args.limit:
        cases = cases[: args.limit]

    print(f"评估 {len(cases)} 条用例 — {args.cases}\n")
    asyncio.run(run_evaluation(cases, verbose=args.verbose))


if __name__ == "__main__":
    main()
