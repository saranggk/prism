# Prism

Find the moment you need in a video library.

Prism is a local-first video research project. The first milestone is uploading a short tutorial, preparing timestamped transcripts and preview images, then searching and playing the matching moment.

**Status:** under development. The application foundation is being built; upload, processing, search, and playback are not yet available. No retrieval quality or performance results have been measured.

## Stack

- **Next.js + TypeScript:** browser interface.
- **FastAPI + Python:** API, retrieval, and a separate processing worker.
- **PostgreSQL + pgvector:** records and transcript embeddings.
- **PgQueuer:** durable background jobs in the same database.
- **FFmpeg:** media validation and frame extraction.
- **faster-whisper + MiniLM:** planned local transcription and text embeddings.

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

In a third terminal, start the interface:

```bash
cd web
npm ci
npm run dev
```

Open <http://127.0.0.1:3000>. The current page shows the real API and database connection state. The API health endpoint is <http://127.0.0.1:8000/health>. The checked-in `.env.example` lists optional local settings; defaults work with the Compose database.

Run `uv run ruff check .` from `server/`, and `npm run lint`, `npm run typecheck`, and `npm run build` from `web/` to check the scaffold.

## Scope

The first milestone supports short English MP4 tutorials, transcript search across a library or selected videos, and timestamped playback. Preview images provide context; they do not establish a visual match.

Later milestones add visual and combined retrieval, frame/clip queries, saved collections, and an agent that assembles sourced clips. A hosted demo follows a working local version.

## Evaluation

Planned evaluation uses a small manually labeled tutorial corpus, with separate development and held-out queries. It will report retrieval quality, timestamp error, processing/search latency, and measured resource use. Test doubles will be distinguished from real-model runs. Video files and model caches are not committed.
