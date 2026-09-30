// Generated from FastAPI OpenAPI. Run: python -m prism.generate_api_types

export type Video = {
  id: string;
  title: string;
  duration_seconds: number;
  status: "queued" | "processing" | "ready" | "failed";
  current_step: string | null;
  error: string | null;
  transcript_state?: "present" | "none" | null;
  created_at: string;
  updated_at: string;
};

export type SearchResult = {
  video_id: string;
  video_title: string;
  start_seconds: number;
  end_seconds: number;
  excerpt: string;
  preview_time_seconds: number | null;
  preview_url: string | null;
  playback_url: string;
};

export type SearchResponse = {
  state: "results" | "no_searchable_videos" | "no_matches";
  results: Array<SearchResult>;
  provisional?: boolean;
};
