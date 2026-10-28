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
    /** 出镜人：传 id = 选用；传 "" = 取消（后端按"字段是否出现"区分"没提"与"清空"）。 */
    characterId?: string;
  },
): Promise<Project> {
  return apiRequest<Project>(`/api/v1/projects/${projectId}`, {
    method: "PATCH",
    body: JSON.stringify({
      ...(input.productName !== undefined ? { product_name: input.productName.trim() } : {}),
      ...(input.productNote !== undefined ? { product_note: input.productNote?.trim() || null } : {}),
      ...(input.characterId !== undefined ? { character_id: input.characterId } : {}),
    }),
  });
}

export async function getProject(projectId: string): Promise<Project> {
  return apiRequest<Project>(`/api/v1/projects/${projectId}`);
}