import type { EditScriptInput, GenerateScriptInput, ScriptState } from "../../features/script/types";
import { apiRequest } from "./client";

export function getScript(projectId: string): Promise<ScriptState> {
  return apiRequest<ScriptState>(`/api/v1/projects/${projectId}/script`);
}

export function generateScript(projectId: string, input: GenerateScriptInput): Promise<ScriptState> {
  return apiRequest<ScriptState>(`/api/v1/projects/${projectId}/script/generate`, {
    method: "POST",
    body: JSON.stringify({
      pain_point: input.painPoint,
      selling_points: input.sellingPoints,
      usage_scenario: input.usageScenario,
      offer: input.offer,
    }),
  });
}

export function editScript(projectId: string, input: EditScriptInput): Promise<ScriptState> {
  return apiRequest<ScriptState>(`/api/v1/projects/${projectId}/script`, {
    method: "PATCH",
    body: JSON.stringify({
      hook: input.hook,
      pain_point: input.painPoint,
      selling_points: input.sellingPoints,
      usage_scenario: input.usageScenario,
      cta: input.cta,
    }),
  });
}

export function confirmScript(projectId: string): Promise<ScriptState> {
  return apiRequest<ScriptState>(`/api/v1/projects/${projectId}/script/confirm`, {
    method: "POST",
  });
}
