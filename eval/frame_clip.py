"""Reproduce source-derived image and clip query measurements locally."""

import argparse
import json
import statistics
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from prism.evaluate import Interval, score_case, summarize

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "eval" / "frame-clip-queries.json"
CORPUS = ROOT / "eval" / "corpus.json"
VIDEO_MAP = ROOT / "data" / "eval" / "video-map.json"


def query_file(case: dict, source: Path, destination: Path) -> None:
    common = [
        "ffmpeg",
        "-v",
        "error",
        "-nostdin",
        "-ss",
        str(case["at_seconds"]),
        "-i",
        str(source),
    ]
    if case["kind"] == "image":
        command = common + ["-frames:v", "1", "-y", str(destination)]
    else:
        command = common + [
            "-t",
            str(case["duration_seconds"]),
            "-an",
            "-sn",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(destination),
        ]
    subprocess.run(command, check=True, timeout=120)


def run(split: str, origin: str) -> dict:
    cases = [case for case in json.loads(MANIFEST.read_text())["cases"] if case["split"] == split]
    corpus = {
        video["id"]: ROOT / video["local_path"]
        for video in json.loads(CORPUS.read_text())["videos"]
    }
    mapping = json.loads(VIDEO_MAP.read_text())
    reverse = {value: key for key, value in mapping.items()}
    scores = []
    rows = []
    with (
        tempfile.TemporaryDirectory(prefix="prism-eval-query-") as temp,
        httpx.Client(base_url=origin, timeout=180) as client,
    ):
        for case in cases:
            path = Path(temp) / f"{case['id']}.{'png' if case['kind'] == 'image' else 'mp4'}"
            generated_at = time.perf_counter()
            query_file(case, corpus[case["source_id"]], path)
            generation_ms = round((time.perf_counter() - generated_at) * 1000, 2)
            size = path.stat().st_size
            params = [("video_ids", mapping[name]) for name in case["filter_ids"]]
            started = time.perf_counter()
            with path.open("rb") as file:
                response = client.post(
                    "/search/visual",
                    params=params,
                    files={"file": (path.name, file)},
                    headers={"X-Prism-Request": "1"},
                )
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            response.raise_for_status()
            body = response.json()
            retrieved = [
                Interval(
                    reverse[result["video_id"]],
                    max(0, result["frame_time_seconds"] - 2.5),
                    result["frame_time_seconds"] + 2.5,
                )
                for result in body["results"]
            ]
            relevant = [Interval(**item) for item in case["relevant"]]
            score = score_case(retrieved, relevant)
            scores.append(score)
            rows.append(
                {
                    "id": case["id"],
                    "kind": case["kind"],
                    "query_bytes": size,
                    "generation_ms": generation_ms,
                    "latency_ms": latency_ms,
                    "state": body["state"],
                    "top_5": [
                        {
                            "video_id": reverse[item["video_id"]],
                            "frame_time_seconds": item["frame_time_seconds"],
                            "query_time_seconds": item["query_time_seconds"],
                        }
                        for item in body["results"][:5]
                    ],
                    "score": vars(score),
                }
            )
            print(f"{case['id']}: {body['state']}, {latency_ms} ms")
    report = {
        "split": split,
        "run_at_utc": datetime.now(UTC).isoformat(),
        "source": "eval/frame-clip-queries.json",
        "summary": summarize(scores),
        "median_latency_ms": statistics.median(row["latency_ms"] for row in rows),
        "cases": rows,
    }
    output = ROOT / "data" / "eval" / f"frame-clip-{split}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("split", choices=["development", "held_out"])
    parser.add_argument("--api-origin", default="http://127.0.0.1:8001")
    args = parser.parse_args()
    print(json.dumps(run(args.split, args.api_origin)["summary"], indent=2))
