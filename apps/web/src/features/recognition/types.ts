export type PipelineStatus =
  | "assets_ready"
  | "recognizing"
  | "recognition_ready"
  | "recognition_confirmed"
  | "main_image_queued"
  | "image_editing"
  | "matting"
  | "main_image_ready"
  | "main_image_confirmed"
  | "failed";

export interface PipelineState {
  pipeline_run_id: string;
  project_id: string;
  status: PipelineStatus;
  current_step: number;
  state_version: number;
  updated_at: string;
}

export interface RecognitionRun {
  run_id: string;
  project_id: string;
  status: "queued" | "running" | "ready" | "confirmed" | "failed";
  input_hash: string;
  selected_asset_id: string | null;
  selected_candidate_id: string | null;
  error_code: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface RecognitionCandidate {
  candidate_id: string;
  run_id: string;
  asset_id: string;
  label: string;
  confidence: number;
  reason: string;
}

export interface RecognitionState {
  run: RecognitionRun | null;
  candidates: RecognitionCandidate[];
}
