export type VoiceStatus = "queued" | "generating" | "ready" | "failed";

export interface VoiceRun {
  run_id: string;
  project_id: string;
  script_version_id: string;
  status: VoiceStatus;
  enabled: boolean;
  provider: string;
  model: string;
  voice_id: string;
  language: "zh" | "en";
  speed: number;
  duration_seconds: number | null;
  audio_url: string | null;
  error_code: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface VoiceState {
  run: VoiceRun | null;
}

export interface VoiceRequestInput {
  enabled: boolean;
  voiceId: string;
  language: "zh" | "en";
  speed: number;
}
