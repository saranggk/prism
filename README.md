# Prism

Find the moment you need in a video library.

Prism is a local-first video research project. Upload a short tutorial or product demo, prepare timestamped transcripts and representative frames, then search and play a matching moment.

**Status:** the local upload → process → combined search → timestamp playback slice works. Image and short clip queries can find visually similar sampled frames in ready videos. You can save, edit, and order timestamp ranges in manual collections, then inspect nearby source transcript segments and sampled frames. Matches remain provisional; the research agent is not built yet. [Real-media evaluation](eval/RESULTS.md) reports measured successes and misses.

## Stack

- **Next.js + TypeScript:** browser interface.
- **FastAPI + Python:** API, retrieval, and a separate processing worker.
- **PostgreSQL + pgvector:** records, transcript embeddings, and frame embeddings.
- **PgQueuer:** durable background jobs in the same database.
- **FFmpeg:** media validation and frame extraction.
- **faster-whisper + MiniLM + CLIP:** pinned local transcription, transcript embeddings, and frame/text embeddings.

PostgreSQL runs in Docker; the application runs directly on your machine. Videos and generated files stay in an ignored local data directory.

## Development prerequisites

- Node.js 24 (use `nvm install` with the repository's `.nvmrc`)
- Python 3.11 and [uv](https://docs.astral.sh/uv/)
- Docker Desktop or another Docker engine with Compose
- FFmpeg and ffprobe (`brew install ffmpeg` on macOS)

## Run the current app

Start PostgreSQL from the repository root:

```bash
docker compose up -d db
```

In another terminal, start the API:

```bash
cd server
uv sync
uv run alembic upgrade head
uv run uvicorn prism.main:app --host 127.0.0.1 --port 8000
```

Download the pinned models once, then start the processing worker in another terminal. Model files stay under ignored `data/models`. The worker reads from the same database and continues after the browser closes. If the models are unavailable, an audio or embedding stage fails visibly and can be retried after setup.

```bash
cd server
uv run python -m prism.worker --download-models
uv run python -m prism.worker
```

In another terminal, start the interface:

```bash
cd web
npm ci
npm run dev
```

Open <http://127.0.0.1:3000> to upload an English H.264 MP4 (up to 15 minutes or 500 MiB) and see its processing state. Suitable English captions are used first; otherwise audio is transcribed locally. A silent video becomes ready with previews and a “no transcript” label. Visual indexing runs separately, so ready transcript search remains available while its frames are indexed. Failed visual indexing can be retried from the library. Search ready videos with a question or provide a JPEG, PNG, or MP4 clip up to 30 seconds and 60 MiB. Video filters apply to both searches. Image and clip queries are processed locally and discarded after the request; results show the matching indexed frame and play from its timestamp. Clip search compares up to 16 sampled views, not motion or sequence. The API health endpoint is <http://127.0.0.1:8000/health>. The checked-in `.env.example` lists optional local settings; defaults work with the Compose database.

Run `uv run ruff check .` from `server/`, and `npm run lint`, `npm run typecheck`, and `npm run build` from `web/` to check the current code.

## Scope

The current local slice supports short English MP4 tutorials and demos, text and image/clip queries across a library or selected videos, title matches, timestamped playback, manually assembled collections of editable video ranges, and on-demand inspection of original transcript segments and registered frames near a chosen time. Library frames are sampled about every five seconds, so brief visual actions can be missed. A visually similar frame does not verify UI text, an action, or the order of events in a clip. A nearby preview provides context unless the result explicitly labels it as a frame match.

Later milestones add an agent that assembles sourced collections. A hosted demo follows a working local version.

## Evaluation

The [evaluation report](eval/RESULTS.md) describes four real tutorials and a product demo, pre-labeled transcript, visual text, image, and clip queries, retrieval quality, timestamp error, and local timings. It explains the limits of the small source-derived image and clip set and how to rerun it. Real media and model caches are kept out of Git.
