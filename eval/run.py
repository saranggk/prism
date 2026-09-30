"""Run pre-labeled transcript queries against a live local Prism API.

The JSON report is written under ignored data/eval/ by default. Run each split
separately so settings can be chosen using development questions alone.
"""

import argparse
import json
import platform
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from prism.evaluate import Interval, score_case, summarize

ROOT = Path(__file__).resolve().parents[1]
QUERIES = ROOT / "eval" / "queries.json"
DEFAULT_MAP = ROOT / "data" / "eval" / "video-map.json"


def run(api_origin: str, split: str, map_path: Path, output: Path, repeats: int = 1) -> dict:
    if repeats < 1:
        raise ValueError("repeats must be at least one")
    queries = json.loads(QUERIES.read_text(encoding="utf-8"))["queries"]
    mapping = json.loads(map_path.read_text(encoding="utf-8"))
    reverse_mapping = {video_id: name for name, video_id in mapping.items()}
    selected_queries = [row for row in queries if row["split"] == split]
    cases = []
    scores = []
    all_latencies = []

    with httpx.Client(base_url=api_origin, timeout=120.0) as client:
        if split == "held_out":
            warmup = client.get(
                "/search",
                params=[("q", "software tutorial")]
                + [("video_ids", video_id) for video_id in mapping.values()],
            )
            warmup.raise_for_status()
        for query in selected_queries:
            filters = query["video_filter_ids"]
            # Even an unfiltered corpus question excludes unrelated local uploads.
            scoped_ids = filters or list(mapping)
            params = [("q", query["query"])] + [("video_ids", mapping[name]) for name in scoped_ids]
            latencies = []
            for repeat in range(repeats):
                started = time.perf_counter()
                response = client.get("/search", params=params)
                elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
                response.raise_for_status()
                latencies.append(elapsed_ms)
                if repeat == 0:
                    payload = response.json()
            all_latencies.extend(latencies)
            raw_results = payload["results"]
            results = [
                Interval(
                    reverse_mapping[row["video_id"]],
                    row["start_seconds"],
                    row["end_seconds"],
                )
                for row in raw_results
            ]
            gold = [Interval(**item) for item in query["relevant"]]
            score = score_case(results, gold)
            scores.append(score)
            cases.append(
                {
                    "id": query["id"],
                    "query": query["query"],
                    "video_filter_ids": filters,
                    "relevant": query["relevant"],
                    "state": payload["state"],
                    "latency_ms": latencies,
                    "top_5": [
                        {
                            "video_id": result.video_id,
                            "start_seconds": result.start_seconds,
                            "end_seconds": result.end_seconds,
                            "excerpt": raw_results[index]["excerpt"],
                        }
                        for index, result in enumerate(results[:5])
                    ],
                    "score": vars(score),
                }
            )
            print(f"{query['id']}: {payload['state']}, {latencies} ms")

    report = {
        "split": split,
        "run_at_utc": datetime.now(UTC).isoformat(),
        "api_origin": api_origin,
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "video_ids": mapping,
        "query_count": len(cases),
        "latency_samples": len(all_latencies),
        "warmup": "one unlabeled query before held-out measurements"
        if split == "held_out"
        else None,
        "latency_ms": {
            "first_observed": all_latencies[0] if all_latencies else None,
            "median": statistics.median(all_latencies) if all_latencies else None,
            "p95": (
                statistics.quantiles(all_latencies, n=100, method="inclusive")[94]
                if len(all_latencies) >= 2
                else None
            ),
            "max": max(all_latencies) if all_latencies else None,
        },
        "summary": summarize(scores),
        "cases": cases,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("split", choices=["development", "held_out"])
    parser.add_argument("--api-origin", default="http://127.0.0.1:8000")
    parser.add_argument("--map-path", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--repeats", type=int, help="Defaults to 1 for dev, 3 for held-out")
    parser.add_argument(
        "--output",
        type=Path,
        help="Report path; defaults to data/eval/<split>-run.json",
    )
    args = parser.parse_args()
    output = args.output or ROOT / "data" / "eval" / f"{args.split}-run.json"
    repeats = args.repeats if args.repeats is not None else (3 if args.split == "held_out" else 1)
    run(args.api_origin, args.split, args.map_path, output, repeats)


if __name__ == "__main__":
    main()
