# Retrieval evaluation

The first section preserves the local, real-model **transcript-only** baseline
from Prism's first vertical slice. The second section measures combined
retrieval. Frame/clip uploads and the research agent remain future work.
Raw run output stays in ignored `data/eval/`.

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

The first command uploads only missing corpus videos, then waits for all five
to become ready. The later commands write local JSON under `data/eval/`.
The processing script now ends its total at the passages checkpoint because
visual indexing updates the video record later; the original table used the
video-ready timestamp, so tiny differences from that table are expected.
The held-out runner sends one unlabeled warmup request and three measured
requests per question. To test another cutoff, set
`PRISM_SEARCH_SIMILARITY_CUTOFF` before starting the API and use only the
development split when choosing it. The scorer and hand-calculated examples
are in `server/prism/evaluate.py` and `server/tests/test_evaluation.py`.

## Combined retrieval slice (2026-09-30)

Prism now indexes the existing roughly five-second preview frames with a pinned
local CLIP text-image model. A ready video remains transcript-searchable while
its frames are indexed. The four tutorials contain 61 SQL, 164 CSS, 163 AJAX,
and 115 TCP indexed frames. The corpus also contains a 42-second, silent
[Open Digital Mentor product demo](https://github.com/cendywang/open-digital-mentor)
with nine indexed frames. The source demo is CC BY-SA 4.0; its visible
attribution card was retained, and the local copy was converted to H.264
yuv420p for Prism. [Corpus metadata](corpus.json) records the source, edit,
license, and checksum. No media is committed.

The 20 tutorial questions above were scored again in transcript-only,
visual-only, and combined modes. Eight [visual questions](visual-queries.json)
were labeled from the demo's visible states before looking at Prism's results:
three answerable and one unanswerable in each split. Title-only matches are
reported separately and do not count as timestamped hits. Final visual
cutoffs were selected from development questions: 0.285 for videos with
transcripts and 0.25 for silent videos. Combined ranking keeps the first five
transcript moments before additional frame-only moments; overlapping frame
evidence can support a transcript moment.

| Corpus and mode | Development hit@5 | Development false matches | Held-out hit@5 | Held-out false matches |
| --- | ---: | ---: | ---: | ---: |
| Tutorials, transcript-only | 6/7 | 1/3 | 5/7 | 2/3 |
| Tutorials, visual-only | 2/7 | 0/3 | 2/7 | 0/3 |
| Tutorials, combined | 6/7 | 1/3 | 5/7 | 2/3 |
| Silent product demo, visual-only | 1/3 | 0/1 | 1/3 | 0/1 |
| Silent product demo, combined | 1/3 | 0/1 | 1/3 | 0/1 |

The scorer also measures the difference between the first returned moment's
start and the nearest labeled interval's start, plus interval overlap (IoU).
These include top-ranked misses, so a large error can coexist with a top-five
hit. The final local runs measured:

| Corpus and mode | Development mean start error / mean IoU | Held-out mean start error / mean IoU |
| --- | ---: | ---: |
| Tutorials, transcript-only | 75.14 s / 0.165 (7 samples) | 130.43 s / 0.450 (7) |
| Tutorials, visual-only | 147.61 s / 0.014 (6) | 87.80 s / 0.061 (5) |
| Tutorials, combined | 75.14 s / 0.165 (7) | 130.43 s / 0.450 (7) |
| Silent demo, visual-only and combined | 1.50 s / 0.750 (1) | 1.50 s / 0.750 (1) |

The tutorial transcript and combined modes have identical top-five quality
and timestamp metrics in this small run. Combined search did **not** improve
the measured tutorial hit rate. It adds frame-only moments after the five
strongest transcript moments, and the interface can search frames alone.
Visual retrieval found the demo's credits screen but missed two text-heavy
interface states. CLIP is weak evidence for small UI text; Prism does not
claim to read that text. The demo's unanswerable chart question returned
no moment.

The first combined development run ranked many five-second frames ahead of
relevant transcript passages: hit@5 fell to 4/7 and all three unanswerable
tutorial questions returned a moment. The revised merge and development
cutoff restored the transcript baseline on development. **The held-out
questions had already been seen in the initial run**; the final-settings
held-out figures in the table are retrospective checks, not an untouched
estimate of generalization. More independently labeled media is needed
before claiming a quality gain.

On the same local machine, manually indexing the real SQL video took
**93.12 seconds** for 61 frames; the silent demo took **6.41 seconds** for
nine frames. These are single runs that include model loading and database
work, not per-frame benchmarks. With models loaded, 30 repeated tutorial
held-out requests had median API search times of **22.4 ms** for transcript
mode and **50.1 ms** for final combined mode; combined p95 was **97.4 ms**.
The development run's first combined query took **11.03 seconds** because
it loaded models, so its p95 is not a warmed-search figure. Browser rendering
and video transfer are excluded. No paid model API calls were made;
electricity and monetary compute cost were not measured.

To reproduce the final local comparison after ingesting the
[corpus](corpus.json), run the API and worker with their pinned models and use
`python ../eval/run.py development --mode combined` from `server/`, then
`python ../eval/run.py held_out --mode combined`. Repeat with `transcript` or
`visual` for the source-specific modes. Pass
`--queries-path ../eval/visual-queries.json` for the product-demo questions.
Use development labels to choose settings, then collect fresh held-out labels
for a future tuning cycle. The existing held-out questions should not be
treated as untouched again.

## Image and clip queries (2026-09-30)

Prism now accepts local JPEG/PNG images and MP4 clips up to 30 seconds and 60 MiB. It embeds the image or up to 16 sampled clip views with the pinned CLIP model and compares them with already indexed library frames. Query media is temporary. These results are similar appearances, not verified UI text, actions, motion, or clip alignment.

Eight [source-derived examples](frame-clip-queries.json) were labeled from visible media states before image/clip retrieval: three answerable and one filtered-out question in each split. Both clips and every screenshot come from the *same source videos* that Prism indexes. This tests near-duplicate retrieval and filtering; it does not estimate performance on independent screenshots or other products. The image cutoff is 0.65, selected on development. The result grouping changed after the first held-out run, so the final held-out figures below are **retrospective**, not an untouched estimate.

| Measure | Development | Held-out, retrospective |
| --- | ---: | ---: |
| Hit@5 on answerable queries | 3/3 | 3/3 |
| Mean precision@5 | 0.45 | 0.60 |
| False matches on filtered-out queries | 0/1 | 0/1 |
| Mean start-time error, first same-video result | 2.43 s (3) | 6.97 s (3) |
| Mean interval overlap, first same-video result | 0.279 (3) | 0.231 (3) |
| Median warm API request time, four requests | 98.07 ms | 92.39 ms |
| Median source-query media preparation time | 157.64 ms | 129.94 ms |

A hit requires a returned sampled-frame window (frame time ±2.5 seconds) to overlap the labeled visible-state interval in the correct video. Start-time error and overlap use the first result from the correct video even when its frame is outside that interval. For example, the held-out AJAX screenshot's first result was at 290.29 seconds, outside its 300–320 second label, although a later result hit. The two no-answer cases use a video filter that excludes the source; they do not test open-library abstention. Nearby frames within eight seconds are collapsed.

On the local Apple M2/16 GB machine, the first development image request after restarting the updated API took **18.83 seconds** while it loaded the model. The final table uses a warmed process. The prepared query files ranged from **151,781 to 677,996 bytes**. A single `ps` observation after both final runs showed **483,600 KiB RSS** for the warmed API process; this includes Python, FastAPI, database client, and the model, so it is not the model's incremental memory cost. Media preparation timing is FFmpeg extraction or transcoding before upload; API request timing includes local multipart transfer, inference, and database search but excludes browser rendering. No paid model API calls were made; electricity and monetary compute cost were not measured.

To reproduce, start the API and worker from the [README](../README.md), ingest and visually index the [corpus](corpus.json), then run from the repository root with the same local media and `data/eval/video-map.json`:

```bash
cd server
uv run python ../eval/frame_clip.py development --api-origin http://127.0.0.1:8000
uv run python ../eval/frame_clip.py held_out --api-origin http://127.0.0.1:8000
```

The script saves raw results under ignored `data/eval/` and deletes generated query files after each run. The current held-out examples have been inspected and need replacement before further tuning.
