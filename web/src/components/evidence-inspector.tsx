"use client";
/* eslint-disable @next/next/no-img-element -- Indexed frames have unknown dimensions. */

import { useEffect, useId, useState } from "react";

import { inspectEvidence, mediaUrl, type EvidenceWindow } from "@/lib/api";
import { formatTime, VideoPlayer } from "@/components/video-player";

export type EvidenceTarget = {
  video_id: string;
  video_title: string;
  start_seconds: number;
  end_seconds: number;
  match_frame_time?: number | null;
  match_transcript?: boolean;
};

export function EvidenceInspector({ target, onClose }: { target: EvidenceTarget; onClose: () => void }) {
  const timeInputId = useId();
  const [time, setTime] = useState(target.match_frame_time ?? target.start_seconds);
  const [draftTime, setDraftTime] = useState(time);
  const [window, setWindow] = useState<EvidenceWindow | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    void inspectEvidence(target.video_id, time, controller.signal).then((data) => {
      setWindow(data);
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Could not inspect evidence.");
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [target.video_id, time]);

  const playback = window?.media_available ? {
    video_id: target.video_id, video_title: window.video_title,
    start_seconds: time, end_seconds: time, playback_url: window.playback_url,
  } : null;

  return <section className="evidence-inspector" aria-label={`Evidence from ${target.video_title}`}>
    <div className="evidence-inspector-heading">
      <div><p className="eyebrow">SOURCE INSPECTION</p><h3>{target.video_title}</h3>
        <p>Original transcript and sampled frames near {formatTime(time)}. Search matches are leads, not verified answers.</p></div>
      <button type="button" onClick={onClose}>Close inspection</button>
    </div>
    <div className="evidence-time-control">
      <label htmlFor={timeInputId}>Inspect time within range: {formatTime(draftTime)}</label>
      <input id={timeInputId} type="range" min={target.start_seconds} max={target.end_seconds}
        step="any" value={draftTime} onChange={(event) => setDraftTime(Number(event.target.value))} />
      <button type="button" disabled={draftTime === time} onClick={() => {
          setWindow(null);
          setLoading(true);
          setError("");
          setTime(draftTime);
        }}>Inspect selected time</button>
      <span>{formatTime(target.start_seconds)}–{formatTime(target.end_seconds)}</span>
    </div>
    {loading && <p role="status">Loading source evidence…</p>}
    {error && <p className="inline-error" role="alert">{error}</p>}
    {window && !loading && !error && <>
      <p className="evidence-window-time">Source window {formatTime(window.window_start_seconds)}–{formatTime(window.window_end_seconds)}</p>
      <div className="evidence-columns">
        <div><h4>Spoken text</h4>
          {target.match_transcript && <p className="evidence-hint">The search matched transcript text. These are the original nearby segments.</p>}
          {window.segments.length ? <ol className="evidence-segments">{window.segments.map((segment) =>
            <li key={segment.ordinal}><span>{formatTime(segment.start_seconds)}–{formatTime(segment.end_seconds)} · {segment.source === "captions" ? "Captions" : "Transcription"}</span><p>{segment.text}</p></li>
          )}</ol> : <p>{window.transcript_state === "present" ? "No transcript segments in this window." : "No transcript is available for this video."}</p>}
        </div>
        <div><h4>Sampled frames</h4>
          <p className="evidence-hint">Frames show sampled views, not actions or motion between them.</p>
          {window.frames.length ? <div className="evidence-frames">{window.frames.map((frame) => {
            const matched = target.match_frame_time != null && Math.abs(frame.time_seconds - target.match_frame_time) < 0.001;
            return <figure key={frame.ordinal}>
              {frame.media_available ? <img src={mediaUrl(frame.url)} alt={`Source frame at ${formatTime(frame.time_seconds)}`} /> : <div className="evidence-frame-missing">Frame file unavailable</div>}
              <figcaption>{matched ? "Matching frame" : "Context frame"} · {formatTime(frame.time_seconds)}</figcaption>
            </figure>;
          })}</div> : <p>{window.visual_state === "ready" ? "No sampled frames in this window." : "Visual evidence is unavailable for this video."}</p>}
        </div>
      </div>
      {playback ? <VideoPlayer key={`${target.video_id}:${time}`} result={playback} exactStart /> :
        <p className="inline-error" role="status">The original video file is unavailable for playback.</p>}
    </>}
  </section>;
}
