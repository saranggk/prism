"""Measure completed processing stages from Prism's persisted checkpoints.

The first interval starts when upload registration commits, so upload transfer
time is excluded. Queue waiting is included in the frames interval.
"""

import argparse
import json
from pathlib import Path
from uuid import UUID

from prism.jobs import connect

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAP = ROOT / "data" / "eval" / "video-map.json"


def measure(map_path: Path, output: Path) -> dict:
    mapping = json.loads(map_path.read_text(encoding="utf-8"))
    measured = {}
    with connect() as db:
        for name, video_id in mapping.items():
            row = db.execute(
                "SELECT created_at, updated_at, status, duration_seconds FROM videos WHERE id = %s",
                (UUID(video_id),),
            ).fetchone()
            if row is None or row["status"] != "ready":
                raise ValueError(f"{name} is not a ready video")
            checkpoints = db.execute(
                "SELECT stage, completed_at FROM stage_checkpoints WHERE video_id = %s",
                (UUID(video_id),),
            ).fetchall()
            times = {item["stage"]: item["completed_at"] for item in checkpoints}
            if set(times) != {"frames", "transcript", "passages"}:
                raise ValueError(f"{name} has incomplete checkpoints: {set(times)}")
            frames = (times["frames"] - row["created_at"]).total_seconds()
            transcript = (times["transcript"] - times["frames"]).total_seconds()
            passages = (times["passages"] - times["transcript"]).total_seconds()
            total = (row["updated_at"] - row["created_at"]).total_seconds()
            measured[name] = {
                "video_duration_seconds": row["duration_seconds"],
                "upload_excluded_seconds": round(total, 2),
                "queued_and_frames_seconds": round(frames, 2),
                "transcript_seconds": round(transcript, 2),
                "passages_seconds": round(passages, 2),
            }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(measured, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output}")
    return measured


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map-path", type=Path, default=DEFAULT_MAP)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "data" / "eval" / "processing.json"
    )
    args = parser.parse_args()
    measure(args.map_path, args.output)


if __name__ == "__main__":
    main()
