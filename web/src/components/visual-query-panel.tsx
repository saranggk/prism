"use client";
/* eslint-disable @next/next/no-img-element -- Local uploads and generated video frames have unknown dimensions. */

import { useEffect, useRef, useState } from "react";

import { mediaUrl, searchVisual, type SearchResult, type Video, type VisualQueryResponse, type VisualQueryResult } from "@/lib/api";
import { formatTime, VideoPlayer } from "@/components/video-player";
import { EvidenceInspector, type EvidenceTarget } from "@/components/evidence-inspector";

const MAX_BYTES = 60 * 1024 * 1024;

export function VisualQueryPanel({ videos, selectedIds, onSaveMoment }: { videos: Video[]; selectedIds: string[]; onSaveMoment: (result: SearchResult) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState("");
  const [response, setResponse] = useState<VisualQueryResponse | null>(null);
  const [active, setActive] = useState<VisualQueryResult | null>(null);
  const [inspected, setInspected] = useState<EvidenceTarget | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null);
  const clipRef = useRef<HTMLVideoElement>(null);
  const previewRef = useRef("");

  useEffect(() => {
    return () => {
      controller.current?.abort();
      if (previewRef.current) URL.revokeObjectURL(previewRef.current);
    };
  }, []);

  function choose(next: File | null) {
    controller.current?.abort();
    setResponse(null);
    setActive(null);
    setInspected(null);
    setError("");
    setLoading(false);
    setFile(null);
    if (previewRef.current) URL.revokeObjectURL(previewRef.current);
    previewRef.current = "";
    setPreview("");
    if (!next) return;
    if (!/\.(jpe?g|png|mp4)$/i.test(next.name)) {
      setError("Choose a JPEG, PNG, or MP4 file.");
    } else if (next.size > MAX_BYTES) {
      setError("Query file exceeds 60 MiB.");
    } else {
      previewRef.current = URL.createObjectURL(next);
      setPreview(previewRef.current);
      setFile(next);
    }
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;
    controller.current?.abort();
    const next = new AbortController();
    controller.current = next;
    setLoading(true);
    setError("");
    setResponse(null);
    setActive(null);
    setInspected(null);
    try {
      const data = await searchVisual(file, selectedIds, next.signal);
      if (!next.signal.aborted) setResponse(data);
    } catch (cause) {
      if (!next.signal.aborted) setError(cause instanceof Error ? cause.message : "Visual search failed.");
    } finally {
      if (!next.signal.aborted) setLoading(false);
    }
  }

  function play(result: VisualQueryResult) {
    setActive(result);
    if (clipRef.current) clipRef.current.currentTime = result.query_time_seconds;
  }

  function frameRange(result: VisualQueryResult) {
    const duration = videos.find((video) => video.id === result.video_id)?.duration_seconds ?? result.frame_time_seconds + 2.5;
    return {
      start_seconds: Math.max(0, result.frame_time_seconds - 2.5),
      end_seconds: Math.min(duration, result.frame_time_seconds + 2.5),
    };
  }

  function save(result: VisualQueryResult) {
    onSaveMoment({
      video_id: result.video_id, video_title: result.video_title,
      ...frameRange(result),
      excerpt: null, evidence: ["frame"],
      preview_time_seconds: result.frame_time_seconds, preview_url: result.frame_url,
      playback_url: result.playback_url,
    });
  }

  function inspect(result: VisualQueryResult) {
    setInspected({
      video_id: result.video_id, video_title: result.video_title,
      ...frameRange(result),
      match_frame_time: result.frame_time_seconds,
    });
  }

  const isClip = file?.name.toLowerCase().endsWith(".mp4");
  return <div className="visual-query">
    <div className="visual-query-heading">
      <h3>Search with an image or clip</h3>
      <p>Find similar sampled views in your ready videos. This compares appearance, not text, actions, or motion.</p>
    </div>
    <form className="visual-query-form" onSubmit={(event) => { void submit(event); }}>
      <label htmlFor="visual-query-file">Screenshot or clip</label>
      <input id="visual-query-file" type="file" accept="image/jpeg,image/png,video/mp4,.jpg,.jpeg,.png,.mp4"
        onChange={(event) => choose(event.target.files?.[0] ?? null)} />
      <span>JPEG or PNG · MP4 up to 30 seconds · 60 MiB maximum</span>
      <button type="submit" disabled={!file || loading || videos.length === 0}>{loading ? "Comparing frames…" : "Find similar moments"}</button>
    </form>
    {preview && file && <div className="visual-query-preview">
      <p>Your {isClip ? "clip" : "image"}{active && isClip ? ` · sampled view at ${formatTime(active.query_time_seconds)}` : ""}</p>
      {isClip ? <video ref={clipRef} src={preview} controls muted playsInline preload="metadata" aria-label="Query clip" /> :
        <img src={preview} alt="Image submitted for visual search" />}
    </div>}
    <div aria-live="polite" aria-busy={loading}>
      {error && <p className="inline-error" role="alert">{error}</p>}
      {response?.skipped_videos.length ? <p className="search-message">Visual indexing is not ready for: {response.skipped_videos.join(", ")}.</p> : null}
      {response?.state === "no_searchable_videos" && <p className="search-message">No ready, visually indexed videos in this selection yet.</p>}
      {response?.state === "no_matches" && <p className="search-message">No sampled frame qualified as a similar view.</p>}
      {response?.state === "results" && <>
        <div className="results-heading"><h3>{response.results.length} possible visual {response.results.length === 1 ? "moment" : "moments"}</h3>
          <p>Each image is an indexed frame, sampled about every five seconds. A match does not verify an action or clip sequence.</p></div>
        <div className="results-grid">{response.results.map((result) => <article className="result-card" key={`${result.video_id}:${result.frame_time_seconds}`}>
          <div className="result-preview is-evidence"><img src={mediaUrl(result.frame_url)} alt={`Matched frame from ${result.video_title} at ${formatTime(result.frame_time_seconds)}`} />
            <span className="preview-time">{formatTime(result.frame_time_seconds)}</span></div>
          <div className="result-body"><p className="result-source">{result.video_title}</p>
            <p className="evidence-label">Similar sampled frame at {formatTime(result.frame_time_seconds)}</p>
            {isClip && <p className="evidence-detail">Matched query sample near {formatTime(result.query_time_seconds)}. Clip order and motion were not compared.</p>}
            <button type="button" onClick={() => play(result)}>Play from this frame <span aria-hidden="true">→</span></button>
            <button type="button" onClick={() => inspect(result)}>Inspect evidence</button>
            <button type="button" onClick={() => save(result)}>Save to collection</button>
          </div></article>)}</div>
      </>}
    </div>
    {active && <VideoPlayer key={`${active.video_id}:${active.frame_time_seconds}`} result={active} />}
    {inspected && <EvidenceInspector key={`${inspected.video_id}:${inspected.match_frame_time}`} target={inspected} onClose={() => setInspected(null)} />}
  </div>;
}
