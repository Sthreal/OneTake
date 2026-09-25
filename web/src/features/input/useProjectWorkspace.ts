import { useCallback, useEffect, useState } from "react";

import {
  createProject as createProjectRequest,
  getProject,
  listProjects,
  updateProject as updateProjectRequest,
} from "../../shared/api/projectApi";
import type { Project } from "./types";

const PROJECT_STORAGE_KEY = "onetake:last-project-id";

export function useProjectWorkspace() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [isLoadingProjects, setIsLoadingProjects] = useState(true);
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectProject = useCallback(async (projectId: string) => {
    setError(null);
    try {
      const selected = await getProject(projectId);
      localStorage.setItem(PROJECT_STORAGE_KEY, selected.project_id);
      setProject(selected);
      setProjects((current) => [
        selected,
        ...current.filter((item) => item.project_id !== selected.project_id),
      ]);
      return selected;
    } catch (requestError) {
      localStorage.removeItem(PROJECT_STORAGE_KEY);
      const message = requestError instanceof Error ? requestError.message : "读取项目失败";
      setError(message);
      throw requestError;
    }
  }, []);

  const refreshProjects = useCallback(async () => {
    setError(null);
    try {
      const loaded = await listProjects(20);
      setProjects(loaded);
      return loaded;
    } catch (requestError) {
      const message = requestError instanceof Error ? requestError.message : "读取项目列表失败";
      setError(message);
      return [];
    } finally {
      setIsLoadingProjects(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    const savedProjectId = localStorage.getItem(PROJECT_STORAGE_KEY);

    listProjects(20)
      .then(async (loaded) => {
        if (!active) return;
        setProjects(loaded);
        const savedProject = savedProjectId
          ? await getProject(savedProjectId).catch(() => null)
          : null;
        const selected = savedProject ?? loaded[0] ?? null;
        if (selected) {
          localStorage.setItem(PROJECT_STORAGE_KEY, selected.project_id);
        } else {
          localStorage.removeItem(PROJECT_STORAGE_KEY);
        }
        if (active) setProject(selected);
      })
      .catch((requestError) => {
        if (!active) return;
        setError(requestError instanceof Error ? requestError.message : "读取项目列表失败");
      })
      .finally(() => {
        if (active) setIsLoadingProjects(false);
      });

    return () => {
      active = false;
    };
  }, []);

  const createProject = useCallback(async (productName: string, productNote: string) => {
    setError(null);
    setIsCreating(true);
    try {
      const created = await createProjectRequest({ productName, productNote });
      localStorage.setItem(PROJECT_STORAGE_KEY, created.project_id);
      setProjects((current) => [
        created,
        ...current.filter((item) => item.project_id !== created.project_id),
      ]);
      setProject(created);
      return created;
    } catch (requestError) {
      const message = requestError instanceof Error ? requestError.message : "创建项目失败";
      setError(message);
      throw requestError;
    } finally {
      setIsCreating(false);
    }
  }, []);

  const updateProject = useCallback(
    async (projectId: string, productName: string, productNote: string) => {
      setError(null);
      try {
        const updated = await updateProjectRequest(projectId, {
          productName,
          productNote: productNote.trim() || null,
        });
        setProject(updated);
        setProjects((current) => [
          updated,
          ...current.filter((item) => item.project_id !== updated.project_id),
        ]);
        localStorage.setItem(PROJECT_STORAGE_KEY, updated.project_id);
        return updated;
      } catch (requestError) {
        const message = requestError instanceof Error ? requestError.message : "更新项目失败";
        setError(message);
        throw requestError;
      }
    },
    [],
  );

  const startNewProject = useCallback(() => {
    localStorage.removeItem(PROJECT_STORAGE_KEY);
    setProject(null);
    setError(null);
  }, []);

  return {
    projects,
    project,
    isLoadingProjects,
    isCreating,
    error,
    createProject,
    updateProject,
    selectProject,
    startNewProject,
    refreshProjects,
  };
}