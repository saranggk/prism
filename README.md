# Prism

Find the moment you need in a video library.

Prism is a local-first video research project. The first milestone is uploading a short tutorial, preparing timestamped transcripts and preview images, then searching and playing the matching moment.

**Status:** the local upload → process → transcript search → timestamp playback slice works. Search matches are provisional; visual search, clip collections, and the research agent are not built yet. [Real-media evaluation](eval/RESULTS.md) reports measured successes and misses.

## Stack

- **Next.js + TypeScript:** browser interface.
- **FastAPI + Python:** API, retrieval, and a separate processing worker.
- **PostgreSQL + pgvector:** records and transcript embeddings.
- **PgQueuer:** durable background jobs in the same database.
- **FFmpeg:** media validation and frame extraction.
- **faster-whisper + MiniLM:** pinned local transcription and text embeddings.

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

Open <http://127.0.0.1:3000> to upload an English H.264 MP4 (up to 15 minutes or 500 MiB) and see its processing state. Suitable English captions are used first; otherwise audio is transcribed locally. A silent video becomes ready with previews and a “no transcript” label. Search ready videos with a question, optionally narrow to selected videos, then open a result to play the original at the matching time. The API health endpoint is <http://127.0.0.1:8000/health>. The checked-in `.env.example` lists optional local settings; defaults work with the Compose database.

Run `uv run ruff check .` from `server/`, and `npm run lint`, `npm run typecheck`, and `npm run build` from `web/` to check the current code.

## Scope

The first milestone supports short English MP4 tutorials, transcript search across a library or selected videos, and timestamped playback. Preview images provide context; they do not establish a visual match.

Later milestones add visual and combined retrieval, frame/clip queries, saved collections, and an agent that assembles sourced clips. A hosted demo follows a working local version.

## Evaluation

The [evaluation report](eval/RESULTS.md) describes four real tutorials, 20 pre-labeled questions, retrieval quality, timestamp error, and local processing/search timings. It explains how to rerun the scorer and where the first model fails. CI runs deterministic behavior tests; real media and model caches are kept out of Git.
