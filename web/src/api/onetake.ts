import { api } from './client';

export interface OneTakeProject {
  project_id: string;
  product_name: string;
  product_note?: string | null;
  status: string;
  created_at?: string;
  updated_at?: string;
}

export interface OneTakePipeline {
  status?: string;
  current_step?: number;
  [key: string]: unknown;
}

export interface OneTakeVideoPlan {
  plan_id?: string;
  mode?: string;
  status?: string;
  duration_seconds?: number;
  video_url?: string | null;
  error_code?: string | null;
}

export interface OneTakeVideoState {
  plan?: OneTakeVideoPlan | null;
}

export interface OneTakeEstimate {
  estimated_known_cost?: number;
  currency?: string;
  requires_confirmation?: boolean;
  estimated_minutes?: number;
}

export interface OneTakeCapabilities {
  write_enabled?: boolean;
  paid_enabled?: boolean;
  asset_import_enabled?: boolean;
  editor_url?: string;
}

export interface OneTakeProvider {
  capability?: string;
  effective_mode?: string;
  effective_provider?: string;
  ready?: boolean;
  reason?: string;
}

export async function getOneTakeProjects(limit = 20) {
  const response = await api.get<{ data: OneTakeProject[] }>(
    `/api/onetake/projects?limit=${limit}`,
  );
  return response.data;
}

export async function getOneTakeProject(projectId: string) {
  const response = await api.get<{ data: OneTakeProject }>(
    `/api/onetake/projects/${encodeURIComponent(projectId)}`,
  );
  return response.data;
}

export async function getOneTakePipeline(projectId: string) {
  const response = await api.get<{ data: OneTakePipeline }>(
    `/api/onetake/projects/${encodeURIComponent(projectId)}/pipeline`,
  );
  return response.data;
}

export async function getOneTakeVideo(projectId: string) {
  const response = await api.get<{ data: OneTakeVideoState }>(
    `/api/onetake/projects/${encodeURIComponent(projectId)}/video`,
  );
  return response.data;
}

export async function getOneTakeEstimate(projectId: string, planId: string) {
  const response = await api.get<{ data: OneTakeEstimate }>(
    `/api/onetake/projects/${encodeURIComponent(projectId)}/estimate?planId=${encodeURIComponent(planId)}`,
  );
  return response.data;
}

export async function getOneTakeProviderStatus() {
  const response = await api.get<{ data: OneTakeProvider[] }>(
    '/api/onetake/provider-status',
  );
  return response.data;
}
export async function getOneTakeCapabilities() {
  const response = await api.get<{ data: OneTakeCapabilities }>(
    '/api/onetake/capabilities',
  );
  return response.data;
}

export async function requestOneTakeVideo(projectId: string, planId: string) {
  const response = await api.post<{ data: OneTakeVideoState }>(
    `/api/onetake/projects/${encodeURIComponent(projectId)}/request-video`,
    { plan_id: planId },
  );
  return response.data;
}
export interface OneTakeEditorState {
  mainImage: Record<string, any>;
  script: Record<string, any>;
  subtitle: Record<string, any>;
  video: Record<string, any>;
}

export async function loadOneTakeEditorState(projectId: string) {
  const response = await api.get<{ data: OneTakeEditorState }>(
    `/api/onetake/projects/${encodeURIComponent(projectId)}/editor`,
  );
  return response.data;
}

export async function confirmOneTakeMainImage(projectId: string) {
  return api.post(
    `/api/onetake/projects/${encodeURIComponent(projectId)}/main-image/confirm`,
  );
}

export async function updateOneTakeScript(
  projectId: string,
  payload: Record<string, unknown>,
) {
  return api.patch(
    `/api/onetake/projects/${encodeURIComponent(projectId)}/script`,
    payload,
  );
}

export async function confirmOneTakeScript(projectId: string) {
  return api.post(
    `/api/onetake/projects/${encodeURIComponent(projectId)}/script/confirm`,
  );
}

export async function updateOneTakeSubtitle(
  projectId: string,
  segments: Array<{ index: number; text: string }>,
) {
  return api.patch(
    `/api/onetake/projects/${encodeURIComponent(projectId)}/subtitle`,
    { segments },
  );
}

export async function confirmOneTakeAudioSubtitle(projectId: string) {
  return api.post(
    `/api/onetake/projects/${encodeURIComponent(projectId)}/audio-subtitle/confirm`,
  );
}

export async function createOneTakeVideoPlan(
  projectId: string,
  mode: 'avatar' | 'product',
  templateId?: string,
) {
  return api.post(
    `/api/onetake/projects/${encodeURIComponent(projectId)}/video-plan`,
    { mode, template_id: templateId },
  );
}