import type { VoiceRequestInput, VoiceState } from "../../features/audio-subtitle/types";
import { apiRequest } from "./client";

export function getVoice(projectId: string): Promise<VoiceState> {
  return apiRequest<VoiceState>(`/api/v1/projects/${projectId}/voice`);
}

export function requestVoice(projectId: string, input: VoiceRequestInput): Promise<VoiceState> {
  return apiRequest<VoiceState>(`/api/v1/projects/${projectId}/voice`, {
    method: "POST",
    body: JSON.stringify({
      enabled: input.enabled,
      voice_id: input.voiceId,
      language: input.language,
      speed: input.speed,
    }),
  });
}
