import type { Collection, SearchResponse, Video } from "@/lib/api-types";

export type { Collection, CollectionItem, SearchResult, SearchResponse, Video, VideoResult, VisualQueryResult, VisualQueryResponse } from "@/lib/api-types";

const origin = process.env.NEXT_PUBLIC_API_ORIGIN ?? "http://127.0.0.1:8000";

function message(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") {
    return body.detail;
  }
  return fallback;
}

export function mediaUrl(path: string): string {
  return `${origin}${path}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${origin}${path}`, { ...init, cache: "no-store" });
  const body: unknown = await response.json();
  if (!response.ok) throw new Error(message(body, `Request failed (${response.status}).`));
  return body as T;
}

export function listVideos(): Promise<Video[]> {
  return request<Video[]>("/videos");
}

const writeHeaders = { "Content-Type": "application/json", "X-Prism-Request": "1" };

export function listCollections(): Promise<Collection[]> {
  return request<Collection[]>("/collections");
}

export function createCollection(title: string): Promise<Collection> {
  return request<Collection>("/collections", { method: "POST", headers: writeHeaders, body: JSON.stringify({ title }) });
}

export function renameCollection(id: string, title: string): Promise<Collection> {
  return request<Collection>(`/collections/${encodeURIComponent(id)}`, { method: "PATCH", headers: writeHeaders, body: JSON.stringify({ title }) });
}

export async function deleteCollection(id: string): Promise<void> {
  const response = await fetch(`${origin}/collections/${encodeURIComponent(id)}`, { method: "DELETE", headers: { "X-Prism-Request": "1" } });
  if (!response.ok) {
    const body: unknown = await response.json();
    throw new Error(message(body, `Could not delete collection (${response.status}).`));
  }
}

export type RangeDraft = { video_id: string; start_seconds: number; end_seconds: number; note: string };

export function addCollectionItem(id: string, range: RangeDraft): Promise<Collection> {
  return request<Collection>(`/collections/${encodeURIComponent(id)}/items`, { method: "POST", headers: writeHeaders, body: JSON.stringify(range) });
}

export function editCollectionItem(id: string, itemId: string, range: Omit<RangeDraft, "video_id">): Promise<Collection> {
  return request<Collection>(`/collections/${encodeURIComponent(id)}/items/${encodeURIComponent(itemId)}`, { method: "PATCH", headers: writeHeaders, body: JSON.stringify(range) });
}

export function reorderCollectionItems(id: string, itemIds: string[]): Promise<Collection> {
  return request<Collection>(`/collections/${encodeURIComponent(id)}/items/order`, { method: "PUT", headers: writeHeaders, body: JSON.stringify({ item_ids: itemIds }) });
}

export function removeCollectionItem(id: string, itemId: string): Promise<Collection> {
  return request<Collection>(`/collections/${encodeURIComponent(id)}/items/${encodeURIComponent(itemId)}`, { method: "DELETE", headers: { "X-Prism-Request": "1" } });
}

export type SearchMode = "combined" | "transcript" | "visual";

export function searchVideos(query: string, videoIds: string[], mode: SearchMode, signal?: AbortSignal): Promise<SearchResponse> {
  const params = new URLSearchParams({ q: query, mode });
  for (const id of videoIds) params.append("video_ids", id);
  return request<SearchResponse>(`/search?${params.toString()}`, { signal });
}

export async function searchVisual(file: File, videoIds: string[], signal?: AbortSignal): Promise<import("@/lib/api-types").VisualQueryResponse> {
  const params = new URLSearchParams();
  for (const id of videoIds) params.append("video_ids", id);
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${origin}/search/visual?${params.toString()}`, {
    method: "POST", headers: { "X-Prism-Request": "1" }, body: form, signal,
  });
  const body: unknown = await response.json();
  if (!response.ok) throw new Error(message(body, `Visual search failed (${response.status}).`));
  return body as import("@/lib/api-types").VisualQueryResponse;
}

export function retryVideo(id: string): Promise<Video> {
  return request<Video>(`/videos/${encodeURIComponent(id)}/retry`, {
    method: "POST",
    headers: { "X-Prism-Request": "1" },
  });
}

export function retryVisual(id: string): Promise<Video> {
  return request<Video>(`/videos/${encodeURIComponent(id)}/retry-visual`, {
    method: "POST",
    headers: { "X-Prism-Request": "1" },
  });
}

export function uploadVideo(file: File, onProgress: (loaded: number, total: number) => void): {
  promise: Promise<Video>;
  cancel: () => void;
} {
  const xhr = new XMLHttpRequest();
  const promise = new Promise<Video>((resolve, reject) => {
    xhr.open("POST", `${origin}/videos`);
    xhr.setRequestHeader("X-Prism-Request", "1");
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded, event.total);
    };
    xhr.onload = () => {
      let body: unknown;
      try { body = JSON.parse(xhr.responseText); } catch { body = null; }
      if (xhr.status === 201) resolve(body as Video);
      else reject(new Error(message(body, `Upload failed (${xhr.status}).`)));
    };
    xhr.onerror = () => reject(new Error("Connection lost. Check the library before trying again."));
    xhr.onabort = () => reject(new Error("Upload canceled. No video was queued."));
    const data = new FormData();
    data.append("file", file);
    xhr.send(data);
  });
  return { promise, cancel: () => xhr.abort() };
}
