"use client";

import { useRef, useState } from "react";

import { mediaUrl, type SearchResult, type VideoResult, type VisualQueryResult } from "@/lib/api";

export function formatTime(seconds: number): string {
  const whole = Math.floor(Math.max(0, seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

export function VideoPlayer({ result }: { result: SearchResult | VideoResult | VisualQueryResult }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [playBlocked, setPlayBlocked] = useState(false);
  const [mediaError, setMediaError] = useState(false);
  const visual = "frame_time_seconds" in result ? result : null;
  const moment = "start_seconds" in result ? result : null;
  const frameOnly = moment?.evidence.includes("frame") && !moment.evidence.includes("transcript");
  let matchTime = 0;
  let label = "Video title";
  if (visual) {
    matchTime = visual.frame_time_seconds;
    label = "Visual match";
  } else if (moment) {
    matchTime = frameOnly ? moment.preview_time_seconds ?? moment.start_seconds : moment.start_seconds;
    label = frameOnly ? "Frame" : "Moment";
  }
  const seekTo = Math.max(0, matchTime - (visual ? 0 : 3));

  function onMetadata() {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = seekTo;
    void video.play().then(() => setPlayBlocked(false)).catch(() => setPlayBlocked(true));
  }

  return (
    <section className="player-panel" aria-label="Selected result playback">
      <div className="player-heading">
        <div>
          <p className="eyebrow">NOW PLAYING</p>
          <h3>{result.video_title}</h3>
        </div>
        <span>{label} {formatTime(visual?.frame_time_seconds ?? moment?.start_seconds ?? 0)}{moment && moment.end_seconds > moment.start_seconds ? `–${formatTime(moment.end_seconds)}` : ""}</span>
      </div>
      <video ref={videoRef} controls playsInline preload="metadata" src={mediaUrl(result.playback_url)}
        onLoadedMetadata={onMetadata} onError={() => setMediaError(true)}
        aria-label={`${result.video_title} video`} />
      <p className="player-context">Starts at {formatTime(seekTo)}{visual ? " on the matched frame." : " with up to three seconds of context."} Playback continues normally.</p>
      {playBlocked && <p className="player-note" role="status">Ready at the selected moment. Press Play to continue.</p>}
      {mediaError && <p className="inline-error" role="alert">The original video could not be loaded.</p>}
    </section>
  );
}
