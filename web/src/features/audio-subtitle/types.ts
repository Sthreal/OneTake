export type VoiceStatus = "queued" | "generating" | "ready" | "confirmed" | "failed";
export type SubtitleStatus = "queued" | "generating" | "ready" | "confirmed" | "failed";

export interface VoiceRun {
  run_id: string; project_id: string; script_version_id: string;
  status: VoiceStatus; enabled: boolean; subtitle_enabled: boolean;
  provider: string; model: string; voice_id: string; language: "zh" | "en"; speed: number;
  duration_seconds: number | null; audio_url: string | null; error_code: string | null;
  created_at: string; updated_at: string; completed_at: string | null; confirmed_at: string | null;
}

export interface SubtitleSegment { index: number; text: string; start: number; end: number; }

export interface SubtitleVersion {
  subtitle_id: string; project_id: string; script_version_id: string; voice_run_id: string;
  status: SubtitleStatus; enabled: boolean; language: "zh" | "en"; segments: SubtitleSegment[];
  srt_url: string | null; error_code: string | null; created_at: string; updated_at: string;
  completed_at: string | null; confirmed_at: string | null;
}

export interface VoiceState { run: VoiceRun | null; }
export interface SubtitleState { version: SubtitleVersion | null; }

export interface VoiceRequestInput {
  enabled: boolean; subtitleEnabled: boolean; voiceId: string; language: "zh" | "en"; speed: number;
}
