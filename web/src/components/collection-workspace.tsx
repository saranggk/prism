"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  addCollectionItem, createCollection, deleteCollection, editCollectionItem, listCollections,
  removeCollectionItem, renameCollection, reorderCollectionItems,
  type Collection, type CollectionItem, type SearchResult, type Video,
} from "@/lib/api";
import { formatTime, VideoPlayer } from "@/components/video-player";
import { EvidenceInspector } from "@/components/evidence-inspector";

function editTime(seconds: number): string {
  const rounded = Math.round(seconds * 1000) / 1000;
  const minutes = Math.floor(rounded / 60);
  const remaining = rounded - minutes * 60;
  const value = Number.isInteger(remaining) ? String(remaining) : remaining.toFixed(3).replace(/0+$/, "");
  return `${minutes}:${value.padStart(2, "0")}`;
}

function parseTime(value: string): number | null {
  const match = /^(\d+):([0-5]?\d(?:\.\d{1,3})?)$/.exec(value.trim());
  if (!match) return null;
  return Number(match[1]) * 60 + Number(match[2]);
}

function ItemRow({ item, index, count, busy, onEdit, onMove, onRemove, onPlay, onInspect }: {
  item: CollectionItem;
  index: number;
  count: number;
  busy: boolean;
  onEdit: (item: CollectionItem, start: number, end: number, note: string) => Promise<void>;
  onMove: (index: number, direction: -1 | 1) => void;
  onRemove: (item: CollectionItem) => void;
  onPlay: (item: CollectionItem) => void;
  onInspect: (item: CollectionItem) => void;
}) {
  const [start, setStart] = useState(editTime(item.start_seconds));
  const [end, setEnd] = useState(editTime(item.end_seconds));
  const [note, setNote] = useState(item.note);
  const [error, setError] = useState("");

  useEffect(() => {
    queueMicrotask(() => {
      setStart(editTime(item.start_seconds));
      setEnd(editTime(item.end_seconds));
      setNote(item.note);
    });
  }, [item.start_seconds, item.end_seconds, item.note]);

  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const first = parseTime(start);
    const last = parseTime(end);
    if (first === null || last === null || first >= last) {
      setError("Enter a valid start and end as minutes:seconds.");
      return;
    }
    setError("");
    await onEdit(item, first, last, note);
  }

  return <li className="collection-item">
    <div className="collection-item-heading">
      <div><strong>{item.video_title}</strong><span>{formatTime(item.start_seconds)}–{formatTime(item.end_seconds)}</span></div>
      <div className="collection-actions">
        <button type="button" onClick={() => onPlay(item)}>Play source</button>
        <button type="button" onClick={() => onInspect(item)}>Inspect evidence</button>
        <button type="button" disabled={busy || index === 0} onClick={() => onMove(index, -1)} aria-label={`Move ${item.video_title} earlier`}>↑</button>
        <button type="button" disabled={busy || index === count - 1} onClick={() => onMove(index, 1)} aria-label={`Move ${item.video_title} later`}>↓</button>
        <button type="button" disabled={busy} onClick={() => onRemove(item)}>Remove</button>
      </div>
    </div>
    <form className="collection-item-form" onSubmit={(event) => { void save(event); }}>
      <label>Start (m:ss)<input value={start} onChange={(event) => setStart(event.target.value)} /></label>
      <label>End (m:ss)<input value={end} onChange={(event) => setEnd(event.target.value)} /></label>
      <label className="collection-note">Note<input value={note} maxLength={500} onChange={(event) => setNote(event.target.value)} placeholder="Why keep this moment?" /></label>
      <button type="submit" disabled={busy}>Save changes</button>
    </form>
    {error && <p className="inline-error" role="alert">{error}</p>}
  </li>;
}

export function CollectionWorkspace({ videos, pendingMoment, onPendingSaved }: {
  videos: Video[];
  pendingMoment: SearchResult | null;
  onPendingSaved: () => void;
}) {
  const [collections, setCollections] = useState<Collection[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [title, setTitle] = useState("");
  const [rename, setRename] = useState("");
  const [videoId, setVideoId] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [note, setNote] = useState("");
  const [activeId, setActiveId] = useState<string | null>(null);
  const [inspectedId, setInspectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const sectionRef = useRef<HTMLElement>(null);
  const selected = collections.find((collection) => collection.id === selectedId) ?? null;
  const active = selected?.items.find((item) => item.id === activeId) ?? null;
  const inspected = selected?.items.find((item) => item.id === inspectedId) ?? null;

  useEffect(() => {
    void listCollections().then((data) => {
      setCollections(data);
      setSelectedId(data[0]?.id ?? "");
      setRename(data[0]?.title ?? "");
    }).catch((cause: unknown) => {
      setError(cause instanceof Error ? cause.message : "Could not load collections.");
    }).finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!pendingMoment) return;
    queueMicrotask(() => {
      setVideoId(pendingMoment.video_id);
      setStart(editTime(pendingMoment.start_seconds));
      setEnd(editTime(pendingMoment.end_seconds));
      setNote("");
      setNotice("Review this suggested range, then add it to a collection.");
      sectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }, [pendingMoment]);

  const replace = useCallback((updated: Collection) => {
    setCollections((current) => current.map((item) => item.id === updated.id ? updated : item));
  }, []);

  async function change(action: () => Promise<Collection>, success: string): Promise<boolean> {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      replace(await action());
      setNotice(success);
      return true;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save the collection.");
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function makeCollection(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!title.trim()) { setError("Enter a collection name."); return; }
    setBusy(true);
    setError("");
    try {
      const created = await createCollection(title.trim());
      setCollections((current) => [created, ...current]);
      setSelectedId(created.id);
      setRename(created.title);
      setTitle("");
      setNotice("Collection created.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not create the collection.");
    } finally { setBusy(false); }
  }

  async function add(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) { setError("Create a collection first."); return; }
    const first = parseTime(start);
    const last = parseTime(end);
    if (!videoId || first === null || last === null || first >= last) {
      setError("Choose a video and enter a valid start and end as minutes:seconds.");
      return;
    }
    const saved = await change(
      () => addCollectionItem(selected.id, { video_id: videoId, start_seconds: first, end_seconds: last, note }),
      "Moment added to collection.",
    );
    if (saved) {
      setStart(""); setEnd(""); setNote("");
      if (pendingMoment) onPendingSaved();
    }
  }

  async function removeSelected() {
    if (!selected || !window.confirm(`Delete “${selected.title}” and its saved moments?`)) return;
    setBusy(true);
    setError("");
    try {
      await deleteCollection(selected.id);
      const remaining = collections.filter((collection) => collection.id !== selected.id);
      setCollections(remaining);
      setSelectedId(remaining[0]?.id ?? "");
      setRename(remaining[0]?.title ?? "");
      setActiveId(null);
      setInspectedId(null);
      setNotice("Collection deleted.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not delete the collection.");
    } finally { setBusy(false); }
  }

  function move(index: number, direction: -1 | 1) {
    if (!selected) return;
    const ids = selected.items.map((item) => item.id);
    [ids[index], ids[index + direction]] = [ids[index + direction], ids[index]];
    void change(() => reorderCollectionItems(selected.id, ids), "Collection order saved.");
  }

  return <section className="collections" aria-labelledby="collections-title" ref={sectionRef}>
    <div className="collections-heading"><div><p className="eyebrow">KEEP THE CONTEXT</p><h2 id="collections-title">Collections</h2></div><p>Save editable ranges from your videos. Each one plays from its original source.</p></div>
    {loading ? <p className="collection-placeholder">Loading collections…</p> : <>
      <form className="collection-create" onSubmit={(event) => { void makeCollection(event); }}>
        <label htmlFor="collection-title">New collection</label>
        <input id="collection-title" value={title} maxLength={100} onChange={(event) => setTitle(event.target.value)} placeholder="e.g. Database setup" />
        <button type="submit" disabled={busy}>Create collection</button>
      </form>
      {collections.length === 0 ? <p className="collection-placeholder">Create a collection to save moments from search or add a range by hand.</p> : <>
        <div className="collection-toolbar">
          <label htmlFor="collection-select">Collection</label>
          <select id="collection-select" value={selectedId} onChange={(event) => { setSelectedId(event.target.value); setRename(collections.find((item) => item.id === event.target.value)?.title ?? ""); setActiveId(null); setInspectedId(null); }}>
            {collections.map((collection) => <option key={collection.id} value={collection.id}>{collection.title}</option>)}
          </select>
          <form onSubmit={(event) => { event.preventDefault(); if (selected) void change(() => renameCollection(selected.id, rename), "Collection renamed."); }}>
            <label htmlFor="rename-collection" className="sr-only">Rename collection</label>
            <input id="rename-collection" value={rename} maxLength={100} onChange={(event) => setRename(event.target.value)} />
            <button type="submit" disabled={busy}>Rename</button>
          </form>
          <button type="button" disabled={busy} onClick={() => { void removeSelected(); }}>Delete collection</button>
        </div>
        <form className="collection-add" onSubmit={(event) => { void add(event); }}>
          <h3>{pendingMoment ? "Save this search moment" : "Add a moment"}</h3>
          <div className="collection-fields">
            <label>Source video<select value={videoId} onChange={(event) => setVideoId(event.target.value)} required><option value="">Choose a ready video</option>{videos.map((video) => <option key={video.id} value={video.id}>{video.title}</option>)}</select></label>
            <label>Start (m:ss)<input value={start} onChange={(event) => setStart(event.target.value)} placeholder="0:30" required /></label>
            <label>End (m:ss)<input value={end} onChange={(event) => setEnd(event.target.value)} placeholder="0:45" required /></label>
            <label className="collection-note">Note<input value={note} maxLength={500} onChange={(event) => setNote(event.target.value)} placeholder="Why keep this moment?" /></label>
          </div>
          <p>Times use minutes:seconds. Choose a range within the source video.</p>
          <button type="submit" disabled={busy || videos.length === 0}>Add to collection</button>
        </form>
        {selected?.items.length ? <ol className="collection-items">{selected.items.map((item, index) => <ItemRow key={item.id} item={item} index={index} count={selected.items.length} busy={busy}
          onEdit={async (target, first, last, text) => { await change(() => editCollectionItem(selected.id, target.id, { start_seconds: first, end_seconds: last, note: text }), "Moment updated."); }}
          onMove={move} onRemove={(target) => { void change(() => removeCollectionItem(selected.id, target.id), "Moment removed."); }} onPlay={(target) => setActiveId(target.id)} onInspect={(target) => setInspectedId(target.id)} />)}</ol> : <p className="collection-placeholder">This collection has no moments yet.</p>}
        {active && <VideoPlayer key={`${active.id}:${active.start_seconds}`} result={active} />}
        {inspected && <EvidenceInspector key={`${inspected.id}:${inspected.start_seconds}:${inspected.end_seconds}`} target={inspected} onClose={() => setInspectedId(null)} />}
      </>}
    </>}
    {error && <p className="inline-error" role="alert">{error}</p>}
    {notice && <p className="inline-success" role="status">{notice}</p>}
  </section>;
}
