"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { listVideos, retryVideo, uploadVideo, type Video } from "@/lib/api";

const MAX_BYTES = 500 * 1024 * 1024;

function duration(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const rest = Math.floor(seconds % 60);
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

function statusText(video: Video): string {
  if (video.status === "queued") return "Queued — you can leave this page";
  if (video.status === "processing") return video.current_step ?? "Preparing video";
  if (video.status === "ready") return video.transcript_state === "none" ? "Ready — no transcript" : "Ready";
  return "Failed";
}

export function VideoLibrary() {
  const [videos, setVideos] = useState<Video[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState("");
  const [uploadError, setUploadError] = useState("");
  const [notice, setNotice] = useState("");
  const [uploading, setUploading] = useState(false);
  const [transfer, setTransfer] = useState<number | null>(null);
  const [retrying, setRetrying] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const cancelRef = useRef<(() => void) | null>(null);

  const refresh = useCallback(async () => {
    try {
      const latest = await listVideos();
      setVideos(latest);
      setListError("");
    } catch (error) {
      setListError(error instanceof Error ? error.message : "Could not load your videos.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { queueMicrotask(() => { void refresh(); }); }, [refresh]);
  useEffect(() => {
    if (!videos.some((video) => video.status === "queued" || video.status === "processing")) return;
    const timer = window.setInterval(() => { void refresh(); }, 2000);
    return () => window.clearInterval(timer);
  }, [videos, refresh]);
  useEffect(() => () => cancelRef.current?.(), []);

  async function onFile(file: File | undefined) {
    if (!file) return;
    setUploadError("");
    setNotice("");
    if (!file.name.toLowerCase().endsWith(".mp4")) {
      setUploadError("Choose an MP4 video.");
      return;
    }
    if (file.size > MAX_BYTES) {
      setUploadError("Video exceeds the 500 MiB limit.");
      return;
    }
    setUploading(true);
    setTransfer(0);
    const upload = uploadVideo(file, (loaded, total) => setTransfer(Math.floor((loaded / total) * 100)));
    cancelRef.current = upload.cancel;
    try {
      const video = await upload.promise;
      setNotice(`${video.title} is queued — you can leave this page.`);
      await refresh();
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : "Upload failed.");
      await refresh();
    } finally {
      cancelRef.current = null;
      setUploading(false);
      setTransfer(null);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  async function onRetry(id: string) {
    setRetrying(id);
    setListError("");
    try {
      await retryVideo(id);
      await refresh();
    } catch (error) {
      setListError(error instanceof Error ? error.message : "Retry failed.");
    } finally {
      setRetrying(null);
    }
  }

  return (
    <section className="library" aria-labelledby="library-title">
      <div className="library-heading">
        <div>
          <p className="eyebrow">YOUR LIBRARY</p>
          <h2 id="library-title">Videos</h2>
        </div>
        <span className="library-count">{videos.length} {videos.length === 1 ? "video" : "videos"}</span>
      </div>

      <div className="upload-panel">
        <div>
          <h3>Add a tutorial or demo</h3>
          <p>English MP4 · H.264 video · up to 15 minutes and 500 MiB</p>
        </div>
        <label className={`upload-button${uploading ? " is-disabled" : ""}`}>
          <input ref={inputRef} type="file" accept="video/mp4,.mp4" disabled={uploading}
            onChange={(event) => { void onFile(event.target.files?.[0]); }} />
          Choose video <span aria-hidden="true">↗</span>
        </label>
      </div>
      {uploading && (
        <div className="transfer" role="status" aria-live="polite">
          <div className="transfer-heading">
            <strong>{transfer === 100 ? "Checking video — keep this page open" : "Uploading — keep this page open"}</strong>
            <span>{transfer === null ? "" : `${transfer}%`}</span>
          </div>
          <progress value={transfer ?? 0} max="100" aria-label="Upload progress" />
          <button type="button" onClick={() => cancelRef.current?.()}>Cancel upload</button>
        </div>
      )}
      {uploadError && <p className="inline-error" role="alert">{uploadError}</p>}
      {notice && <p className="inline-success" role="status">{notice}</p>}

      <div className="library-list" aria-live="polite" aria-busy={loading}>
        {loading ? <p className="library-placeholder">Loading videos…</p> :
          listError && videos.length === 0 ? <p className="library-placeholder">Could not load videos. <button type="button" onClick={() => { void refresh(); }}>Try again</button></p> :
          videos.length === 0 ? <p className="library-placeholder">Your library is empty. Add an MP4 to get started.</p> :
          videos.map((video) => (
            <article className="video-row" key={video.id}>
              <span className="video-icon" aria-hidden="true">▶</span>
              <div className="video-info">
                <h3>{video.title}</h3>
                <p>{duration(video.duration_seconds)} · Added {new Date(video.created_at).toLocaleDateString()}</p>
                {video.status === "failed" && video.error && <p className="video-error">{video.error}</p>}
              </div>
              <div className="video-state">
                <span className={`video-badge video-badge-${video.status}`}><i aria-hidden="true" />{statusText(video)}</span>
                {video.status === "failed" && <button type="button" disabled={retrying === video.id}
                  onClick={() => { void onRetry(video.id); }}>{retrying === video.id ? "Retrying…" : "Retry"}</button>}
              </div>
            </article>
          ))}
      </div>
      {listError && videos.length > 0 && <p className="inline-error" role="alert">{listError} <button type="button" onClick={() => { void refresh(); }}>Try again</button></p>}
    </section>
  );
}
