# Transcript search evaluation

This is a local, real-model run of Prism's first vertical slice. It evaluates
**transcript search only**. Visual search, frame/clip queries, and the research
agent are future work. The raw run output stays in ignored `data/eval/`.

## Corpus and method

Four CS50 tutorial excerpts (about 5, 9.5, 13.5, and 13.7 minutes) were
uploaded and processed through the normal API and worker. The SQL excerpt
used local speech transcription; the other three used embedded official
captions. [Corpus metadata](corpus.json) records sources, license links,
changes, durations, and SHA-256 checksums. Media files are not in Git.

Twenty questions and answer intervals were marked from source captions
**before** inspecting Prism results: ten development questions and ten held-out
questions. Each split has seven answerable and three unanswerable questions.
The evaluation limits searches to these four videos, even if a developer's
local library has other uploads. A question's explicit video filter narrows
that scope further.

The cosine-similarity cutoff was held at **0.30**. On the development split,
lowering it to 0.15 did not improve hit@5 (both were 6/7) and increased
false matches on unanswerable questions from 1/3 to 3/3. The held-out split
was then scored at 0.30 without further tuning. Results are possible matches,
not verified answers.

| Metric | Development | Held-out |
| --- | ---: | ---: |
| Hit@5 on answerable questions | 6/7 | 5/7 |
| Mean precision@5 on answerable questions | 0.229 | 0.179 |
| False matches on unanswerable questions | 1/3 | 2/3 |
| Mean start-time error, first same-video result | 75.14 s (7 samples) | 130.43 s (7 samples) |
| Mean interval overlap (IoU), first same-video result | 0.165 (7 samples) | 0.450 (7 samples) |

Hit@5 requires a returned range in the correct video to overlap a labeled
range. Precision divides relevant matches by the actual number of results
returned, up to five, and averages over answerable questions. A false match
means any result was returned for a question with no labeled answer in its
selected videos. Start error and interval overlap use the **first returned
result from a correct video**, even if its moment is wrong. They are not
playback seek error; the browser separately checks seek behavior. These
figures come from one small, single-source corpus with one set of labels, so
they should not be read as general accuracy estimates.

The development query “Where do they configure the database connection?”
missed its labeled SQL range (55–98 s) in the top five. The search surfaced
nearby explanation and later SQL execution instead. In held-out questions,
the jQuery page-update and TCP packet-order moments were misses; database
schema migration and the filtered-out secure-browsing answer still returned
possible matches. This is the main retrieval and abstention limitation to
address in the next iteration.

## Time and resource observations

Measured on an Apple M2 with 16 GB RAM, macOS 26.5.2, Python 3.11,
`faster-whisper` 1.2.1, `sentence-transformers` 5.7.0, and the pinned model
revisions in `server/prism/transcripts.py`. This local run made no paid model
API calls; electricity, model downloads, and a monetary compute cost were
not measured. The four media files total 558.4 MiB by logical file size.

| Video | Video length | Upload-excluded processing | Queue + frames | Transcript | Passages |
| --- | ---: | ---: | ---: | ---: | ---: |
| SQL connection | 5:00 | 181.28 s | 2.46 s | 124.13 s | 54.67 s |
| CSS | 13:39 | 188.35 s | 187.79 s | 0.08 s | 0.47 s |
| AJAX | 13:32 | 173.61 s | 173.09 s | 0.06 s | 0.44 s |
| TCP | 9:31 | 170.71 s | 170.32 s | 0.06 s | 0.32 s |

Processing times come from database creation, stage checkpoint, and ready
timestamps. The first stage includes queue waiting, so it is **not** a pure
frame-extraction benchmark; the three captioned videos queued behind the SQL
transcription. Upload transfer is excluded. Small rounding differences can
occur between the stage sum and total.

After one unlabeled warmup query, the 10 held-out questions were each sent
three times to the already running API. Across 30 requests, median search
latency was **37.0 ms** and p95 was **89.8 ms**. This excludes browser
rendering, video transfer, and model cold start. The first measured query
after warmup took 39.8 ms. The 10 development requests had a 22.7 ms median;
their first observed request was 32.4 ms, also with a loaded model.
One separate request to a fresh API process took **18.1 s** while several
other local model processes were running. It is a single cold-start
observation under contention, not a latency distribution or a reliable
uncontended startup benchmark.

## Reproduce locally

Follow the [README setup](../README.md) to start PostgreSQL, API, and worker.
Acquire the source media listed in [the corpus](corpus.json) and prepare the
files described there; the local file checksum must match before ingestion.
Run these commands from `server/`:

```bash
uv run python ../eval/ingest.py
uv run python ../eval/processing.py
uv run python ../eval/run.py development
uv run python ../eval/run.py held_out
```

The first command uploads only missing corpus videos, then waits for all four
to become ready. The later commands write local JSON under `data/eval/`.
The held-out runner sends one unlabeled warmup request and three measured
requests per question. To test another cutoff, set
`PRISM_SEARCH_SIMILARITY_CUTOFF` before starting the API and use only the
development split when choosing it. The scorer and hand-calculated examples
are in `server/prism/evaluate.py` and `server/tests/test_evaluation.py`.
