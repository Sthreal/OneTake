import { apiRequest } from "./client";
import type { Project } from "../../features/input/types";

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

export async function listProjects(limit = 20): Promise<Project[]> {
  return apiRequest<Project[]>(`/api/v1/projects?limit=${limit}`);
}

export async function getProject(projectId: string): Promise<Project> {
  return apiRequest<Project>(`/api/v1/projects/${projectId}`);
}