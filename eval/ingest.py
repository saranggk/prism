"""Upload the labeled local corpus through Prism's public API.

Run with the API and worker started. The video-ID map lives under ignored data/.
"""

import argparse
import hashlib
import json
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "eval" / "corpus.json"
DEFAULT_MAP = ROOT / "data" / "eval" / "video-map.json"


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_map(path: Path, mapping: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(mapping, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def ingest(api_origin: str, map_path: Path, wait_seconds: int) -> dict[str, str]:
    manifest = json.loads(CORPUS.read_text(encoding="utf-8"))
    mapping: dict[str, str] = (
        json.loads(map_path.read_text(encoding="utf-8")) if map_path.exists() else {}
    )
    videos = manifest["videos"]
    corpus_ids = [item["id"] for item in videos]
    with httpx.Client(base_url=api_origin, timeout=httpx.Timeout(300.0)) as client:
        for item in videos:
            path = ROOT / item["local_path"]
            if not path.is_file():
                raise FileNotFoundError(
                    f"Missing {path}; see eval/corpus.json for its source."
                )
            if checksum(path) != item["sha256"]:
                raise ValueError(
                    f"Checksum mismatch for {path}; this is not the labeled media."
                )

            existing = mapping.get(item["id"])
            if existing:
                response = client.get(f"/videos/{existing}")
                if response.status_code == 200:
                    if response.json()["title"] != path.stem:
                        raise ValueError(
                            f"Video map points {item['id']} to another upload."
                        )
                    print(f"{item['id']}: existing {existing}")
                    continue
                if response.status_code != 404:
                    response.raise_for_status()

            with path.open("rb") as source:
                response = client.post(
                    "/videos",
                    files={"file": (path.name, source, "video/mp4")},
                    headers={"X-Prism-Request": "1"},
                )
            response.raise_for_status()
            mapping[item["id"]] = response.json()["id"]
            save_map(map_path, mapping)
            print(f"{item['id']}: uploaded {mapping[item['id']]}")

        deadline = time.monotonic() + wait_seconds
        while wait_seconds:
            statuses = {}
            for name in corpus_ids:
                response = client.get(f"/videos/{mapping[name]}")
                response.raise_for_status()
                statuses[name] = response.json()
            failures = {
                name: row["error"]
                for name, row in statuses.items()
                if row["status"] == "failed"
            }
            if failures:
                raise RuntimeError(f"Processing failed: {failures}")
            if len(statuses) == len(videos) and all(
                row["status"] == "ready" for row in statuses.values()
            ):
                print(f"All {len(videos)} evaluation videos are ready.")
                break
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    "Videos are still processing; keep the worker running and retry."
                )
            time.sleep(2)
    return mapping


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-origin", default="http://127.0.0.1:8000")
    parser.add_argument("--map-path", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--wait-seconds", type=int, default=1800)
    args = parser.parse_args()
    ingest(args.api_origin, args.map_path, args.wait_seconds)


if __name__ == "__main__":
    main()
