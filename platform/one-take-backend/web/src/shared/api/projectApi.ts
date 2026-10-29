import { apiRequest } from "./client";
import type { Project, ProjectFromUrlResult } from "../../features/input/types";

export async function createProject(input: {
  productName: string;
  productNote?: string;
}): Promise<Project> {
  return apiRequest<Project>("/api/v1/projects", {
    method: "POST",
    body: JSON.stringify({
      product_name: input.productName.trim(),
      product_note: input.productNote?.trim() || null,
    }),
  });
}

/** S13：粘贴商品链接建项目。内网/环回/元数据地址会被后端拒绝（422）。 */
export async function createProjectFromUrl(url: string): Promise<ProjectFromUrlResult> {
  return apiRequest<ProjectFromUrlResult>("/api/v1/projects/from-url", {
    method: "POST",
    body: JSON.stringify({ url: url.trim() }),
  });
}

export async function listProjects(limit = 20): Promise<Project[]> {
  return apiRequest<Project[]>(`/api/v1/projects?limit=${limit}`);
}

export async function updateProject(
  projectId: string,
  input: {
    productName?: string;
    productNote?: string | null;
    /** 出镜人：传库 id = 选用；传 null 或 "" = 清空。字段缺省则不动。 */
    characterId?: string | null;
  },
): Promise<Project> {
  return apiRequest<Project>(`/api/v1/projects/${projectId}`, {
    method: "PATCH",
    body: JSON.stringify(projectUpdateBody(input)),
  });
}

/** null 必须留在 JSON 里，后端才把 character_id 当成「显式清空」而不是「没提」。 */
export function projectUpdateBody(input: {
  productName?: string;
  productNote?: string | null;
  characterId?: string | null;
}): Record<string, unknown> {
  return {
    ...(input.productName !== undefined ? { product_name: input.productName.trim() } : {}),
    ...(input.productNote !== undefined ? { product_note: input.productNote?.trim() || null } : {}),
    ...(input.characterId !== undefined ? { character_id: input.characterId } : {}),
  };
}

export async function getProject(projectId: string): Promise<Project> {
  return apiRequest<Project>(`/api/v1/projects/${projectId}`);
}