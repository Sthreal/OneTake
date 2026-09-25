import { useCallback, useEffect, useState } from "react";

import { confirmContentPlan, generateContentPlan, getContentPlan, updateContentPlan } from "../../shared/api/contentPlanApi";
import type { ContentPlan, ContentScene } from "./types";

export function useContentPlan(projectId: string | null) {
  const [plan, setPlan] = useState<ContentPlan | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isConfirming, setIsConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!projectId) return;
    setIsLoading(true);
    try {
      setPlan(await getContentPlan(projectId));
      setError(null);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "读取视频分镜失败");
    } finally {
      setIsLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    setPlan(null);
    setError(null);
    if (projectId) void load();
  }, [projectId, load]);

  const generate = useCallback(async () => {
    if (!projectId) return;
    setIsGenerating(true);
    try {
      setPlan(await generateContentPlan(projectId));
      setError(null);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "生成视频分镜失败");
    } finally {
      setIsGenerating(false);
    }
  }, [projectId]);

  const save = useCallback(async (selectedVariantIndex: number, scenes: ContentScene[]) => {
    if (!projectId) return;
    setIsSaving(true);
    try {
      setPlan(await updateContentPlan(projectId, selectedVariantIndex, scenes));
      setError(null);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "保存视频分镜失败");
    } finally {
      setIsSaving(false);
    }
  }, [projectId]);

  const confirm = useCallback(async () => {
    if (!projectId) return;
    setIsConfirming(true);
    try {
      setPlan(await confirmContentPlan(projectId));
      setError(null);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "确认视频分镜失败");
    } finally {
      setIsConfirming(false);
    }
  }, [projectId]);

  return { plan, isLoading, isGenerating, isSaving, isConfirming, error, load, generate, save, confirm };
}
