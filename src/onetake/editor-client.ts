import { ONETAKE_API_URL } from '../config.js';

async function request<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`${ONETAKE_API_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  });
  const payload = (await response.json().catch(() => ({}))) as Record<
    string,
    unknown
  >;
  if (!response.ok) {
    throw new Error(
      String(payload.detail || payload.error || `One Take HTTP ${response.status}`),
    );
  }
  return (payload.data ?? payload) as T;
}

export interface OneTakeEditorState {
  mainImage: Record<string, unknown>;
  script: Record<string, unknown>;
  subtitle: Record<string, unknown>;
  video: Record<string, unknown>;
}

export async function loadOneTakeEditorState(
  projectId: string,
): Promise<OneTakeEditorState> {
  const encoded = encodeURIComponent(projectId);
  const [mainImage, script, subtitle, video] = await Promise.all([
    request<Record<string, unknown>>(`/api/v1/projects/${encoded}/main-image`),
    request<Record<string, unknown>>(`/api/v1/projects/${encoded}/script`),
    request<Record<string, unknown>>(`/api/v1/projects/${encoded}/subtitle`),
    request<Record<string, unknown>>(`/api/v1/projects/${encoded}/video`),
  ]);
  return { mainImage, script, subtitle, video };
}

export async function confirmOneTakeMainImage(projectId: string) {
  return request(`/api/v1/projects/${encodeURIComponent(projectId)}/main-image/confirm`, {
    method: 'POST',
  });
}

export async function updateOneTakeScript(
  projectId: string,
  payload: Record<string, unknown>,
) {
  return request(`/api/v1/projects/${encodeURIComponent(projectId)}/script`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export async function confirmOneTakeScript(projectId: string) {
  return request(`/api/v1/projects/${encodeURIComponent(projectId)}/script/confirm`, {
    method: 'POST',
  });
}

export async function updateOneTakeSubtitle(
  projectId: string,
  segments: Array<{ index: number; text: string }>,
) {
  return request(`/api/v1/projects/${encodeURIComponent(projectId)}/subtitle`, {
    method: 'PATCH',
    body: JSON.stringify({ segments }),
  });
}

export async function confirmOneTakeAudioSubtitle(projectId: string) {
  return request(
    `/api/v1/projects/${encodeURIComponent(projectId)}/audio-subtitle/confirm`,
    { method: 'POST' },
  );
}

export async function createOneTakeVideoPlan(
  projectId: string,
  mode: 'avatar' | 'product',
  templateId?: string,
) {
  return request(`/api/v1/projects/${encodeURIComponent(projectId)}/video-plan`, {
    method: 'POST',
    body: JSON.stringify({ mode, template_id: templateId }),
  });
}