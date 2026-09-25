import { useCallback, useEffect, useState } from "react";

import { confirmMainImage, getMainImage, requestMainImage } from "../../shared/api/mainImageApi";
import { getPipeline } from "../../shared/api/recognitionApi";
import type { PipelineState } from "../recognition/types";
import type { MainImageState } from "./types";

const EMPTY_STATE: MainImageState = { version: null };
const ACTIVE_STATUSES = new Set(["queued", "editing", "matting", "processing"]);

export function useMainImage(projectId: string | null) {
  const [state, setState] = useState<MainImageState>(EMPTY_STATE);
  const [pipeline, setPipeline] = useState<PipelineState | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isStarting, setIsStarting] = useState(false);
  const [isConfirming, setIsConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (silent = false) => {
    if (!projectId) return;
    if (!silent) setIsLoading(true);
    try {
      const [nextState, nextPipeline] = await Promise.all([
        getMainImage(projectId),
        getPipeline(projectId),
      ]);
      setState(nextState);
      setPipeline(nextPipeline);
      setError(null);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "读取主图状态失败");
    } finally {
      if (!silent) setIsLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    setState(EMPTY_STATE);
    setPipeline(null);
    setError(null);
    if (projectId) void load();
  }, [projectId, load]);

  useEffect(() => {
    const status = state.version?.status;
    if (!projectId || !status || !ACTIVE_STATUSES.has(status)) return;
    const timer = window.setInterval(() => void load(true), 1500);
    return () => window.clearInterval(timer);
  }, [projectId, state.version?.status, load]);

  const start = useCallback(async () => {
    if (!projectId) return;
    setIsStarting(true);
    try {
      const nextState = await requestMainImage(projectId);
      setState(nextState);
      setPipeline(await getPipeline(projectId));
      setError(null);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "生成主图失败");
    } finally {
      setIsStarting(false);
    }
  }, [projectId]);

  const confirm = useCallback(async () => {
    if (!projectId) return;
    setIsConfirming(true);
    try {
      const nextState = await confirmMainImage(projectId);
      setState(nextState);
      setPipeline(await getPipeline(projectId));
      setError(null);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "确认主图失败");
    } finally {
      setIsConfirming(false);
    }
  }, [projectId]);

  return {
    state,
    pipeline,
    isLoading,
    isStarting,
    isConfirming,
    error,
    load,
    start,
    confirm,
  };
}
