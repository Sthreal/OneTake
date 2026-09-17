import { useCallback, useEffect, useState } from "react";

import { confirmRecognition, getPipeline, getRecognition, requestRecognition } from "../../shared/api/recognitionApi";
import type { PipelineState, RecognitionState } from "./types";

const EMPTY_STATE: RecognitionState = { run: null, candidates: [] };

export function useRecognition(projectId: string | null) {
  const [pipeline, setPipeline] = useState<PipelineState | null>(null);
  const [recognition, setRecognition] = useState<RecognitionState>(EMPTY_STATE);
  const [isLoading, setIsLoading] = useState(false);
  const [isStarting, setIsStarting] = useState(false);
  const [isConfirming, setIsConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (silent = false) => {
    if (!projectId) return;
    if (!silent) setIsLoading(true);
    try {
      const [nextPipeline, nextRecognition] = await Promise.all([
        getPipeline(projectId),
        getRecognition(projectId),
      ]);
      setPipeline(nextPipeline);
      setRecognition(nextRecognition);
      setError(null);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "读取识别状态失败");
    } finally {
      if (!silent) setIsLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    setPipeline(null);
    setRecognition(EMPTY_STATE);
    setError(null);
    if (projectId) void load();
  }, [projectId, load]);

  useEffect(() => {
    const status = recognition.run?.status;
    if (!projectId || (status !== "queued" && status !== "running")) return;
    const timer = window.setInterval(() => void load(true), 1500);
    return () => window.clearInterval(timer);
  }, [projectId, recognition.run?.status, load]);

  const start = useCallback(async () => {
    if (!projectId) return;
    setIsStarting(true);
    try {
      const state = await requestRecognition(projectId);
      setRecognition(state);
      setPipeline(await getPipeline(projectId));
      setError(null);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "启动识别失败");
    } finally {
      setIsStarting(false);
    }
  }, [projectId]);

  const confirm = useCallback(async (assetId: string, candidateId: string) => {
    if (!projectId || !recognition.run) return;
    setIsConfirming(true);
    try {
      const state = await confirmRecognition(projectId, recognition.run.run_id, assetId, candidateId);
      setRecognition(state);
      setPipeline(await getPipeline(projectId));
      setError(null);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "确认识别结果失败");
    } finally {
      setIsConfirming(false);
    }
  }, [projectId, recognition.run]);

  return { pipeline, recognition, isLoading, isStarting, isConfirming, error, load, start, confirm };
}
