"use client";
/* eslint-disable @next/next/no-img-element -- Preview frames are pre-generated JPEGs with unknown dimensions. */

import { useEffect, useRef, useState } from "react";

import { mediaUrl, searchVideos, type SearchResponse, type SearchResult, type Video } from "@/lib/api";
import { formatTime, VideoPlayer } from "@/components/video-player";

export function SearchResults({ videos }: { videos: Video[] }) {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [active, setActive] = useState<SearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const requestId = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const searchable = videos.filter((video) => video.status === "ready" && video.transcript_state === "present");

  useEffect(() => () => controller.current?.abort(), []);

  function invalidate() {
    requestId.current += 1;
    controller.current?.abort();
    setLoading(false);
  }

  function execute(text: string, ids: string[]) {
    invalidate();
    const current = requestId.current;
    const next = new AbortController();
    controller.current = next;
    setResponse(null);
    setActive(null);
    setError("");
    setLoading(true);
    void searchVideos(text, ids, next.signal).then((data) => {
      if (current === requestId.current) setResponse(data);
    }).catch((cause: unknown) => {
      if (current === requestId.current && !next.signal.aborted) {
        setError(cause instanceof Error ? cause.message : "Search failed. Try again.");
      }
    }).finally(() => {
      if (current === requestId.current) setLoading(false);
    });
  }

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = query.trim();
    if (!text) {
      invalidate();
      setResponse(null);
      setActive(null);
      setError("Enter a question or phrase to search.");
      return;
    }
    setSubmitted(text);
    execute(text, selectedIds);
  }

  function toggle(id: string) {
    const next = selectedIds.includes(id) ? selectedIds.filter((item) => item !== id) : [...selectedIds, id];
    setSelectedIds(next);
    if (submitted) execute(submitted, next);
  }

  return (
    <section className="search-section" aria-labelledby="search-title">
      <div className="search-heading">
        <p className="eyebrow">FIND A MOMENT</p>
        <h2 id="search-title">Search your videos</h2>
        <p>Ask where a step happens. Results come from spoken words or captions.</p>
      </div>
      <form className="search-form" onSubmit={submit}>
        <label htmlFor="search-query" className="sr-only">Search question</label>
        <input id="search-query" type="search" value={query} maxLength={1000}
          placeholder="How do they execute a SQL query from Python?"
          onChange={(event) => {
            invalidate();
            setQuery(event.target.value);
            setSubmitted("");
            setResponse(null);
            setActive(null);
            setError("");
          }} />
        <button type="submit" disabled={loading || searchable.length === 0}>Search <span aria-hidden="true">↗</span></button>
      </form>
      <fieldset className="video-filters">
        <legend>Videos to search <span>{selectedIds.length ? `${selectedIds.length} selected` : "All ready videos"}</span></legend>
        {searchable.length === 0 ? <p>No ready videos with transcripts yet. Upload a tutorial or wait for processing to finish.</p> :
          <div className="filter-options">
            {searchable.map((video) => <label key={video.id} className={selectedIds.includes(video.id) ? "is-selected" : ""}>
              <input type="checkbox" value={video.id} checked={selectedIds.includes(video.id)} onChange={() => toggle(video.id)} />
              {video.title}
            </label>)}
            {selectedIds.length > 0 && <button type="button" className="clear-filters" onClick={() => {
              setSelectedIds([]);
              if (submitted) execute(submitted, []);
            }}>Clear filters</button>}
          </div>}
      </fieldset>
      <div className="search-feedback" aria-live="polite" aria-busy={loading}>
        {loading && <p className="search-message">Searching ready transcripts…</p>}
        {error && <p className="inline-error" role="alert">{error}</p>}
        {!loading && !error && response?.state === "no_searchable_videos" &&
          <p className="search-message">None of the selected videos has a ready transcript. Clear filters or wait for processing.</p>}
        {!loading && !error && response?.state === "no_matches" &&
          <p className="search-message">No passages qualified for this search. Try different words or clear your filters.</p>}
        {!loading && response?.state === "results" && <>
          <div className="results-heading">
            <h3>{response.results.length} possible {response.results.length === 1 ? "match" : "matches"}</h3>
            <p>Transcript matches are suggestions. Preview images show nearby context, not visual proof. Ranking is provisional.</p>
          </div>
          <div className="results-grid">
            {response.results.map((result) => {
              const key = `${result.video_id}:${result.start_seconds}:${result.end_seconds}`;
              const chosen = active?.video_id === result.video_id && active.start_seconds === result.start_seconds;
              return <article className={`result-card${chosen ? " is-active" : ""}`} key={key}>
                <div className="result-preview">
                  {result.preview_url ? <img src={mediaUrl(result.preview_url)} alt={`Frame from ${result.video_title} at ${formatTime(result.preview_time_seconds ?? 0)}`} /> :
                    <span>No preview available</span>}
                  <span className="preview-time">{result.preview_time_seconds === null ? "" : formatTime(result.preview_time_seconds)}</span>
                </div>
                <div className="result-body">
                  <p className="result-source">{result.video_title} <span>· {formatTime(result.start_seconds)}–{formatTime(result.end_seconds)}</span></p>
                  <p className="result-excerpt">“{result.excerpt}”</p>
                  <button type="button" onClick={() => setActive(result)}>{chosen ? "Playing this moment" : "Play this moment"} <span aria-hidden="true">→</span></button>
                </div>
              </article>;
            })}
          </div>
        </>}
      </div>
      {active && <VideoPlayer key={`${active.video_id}:${active.start_seconds}:${active.end_seconds}`} result={active} />}
    </section>
  );
}
