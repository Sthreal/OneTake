import { useCallback, useEffect, useState } from "react";

import { confirmScript, editScript, generateScript, getScript } from "../../shared/api/scriptApi";
import { getPipeline } from "../../shared/api/recognitionApi";
import type { PipelineState } from "../recognition/types";
import type { EditScriptInput, GenerateScriptInput, ScriptState } from "./types";

const EMPTY_STATE: ScriptState = { version: null };
const ACTIVE_STATUSES = new Set(["queued", "generating"]);

export function useScript(projectId: string | null) {
  const [state, setState] = useState<ScriptState>(EMPTY_STATE);
  const [pipeline, setPipeline] = useState<PipelineState | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isStarting, setIsStarting] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isConfirming, setIsConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (silent = false) => {
    if (!projectId) return;
    if (!silent) setIsLoading(true);
    try {
      const [nextState, nextPipeline] = await Promise.all([getScript(projectId), getPipeline(projectId)]);
      setState(nextState);
      setPipeline(nextPipeline);
      setError(null);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "读取文案状态失败");
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

  const start = useCallback(async (input: GenerateScriptInput) => {
    if (!projectId) return;
    setIsStarting(true);
    try {
      const nextState = await generateScript(projectId, input);
      setState(nextState);
      setPipeline(await getPipeline(projectId));
      setError(null);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "生成文案失败");
    } finally {
      setIsStarting(false);
    }
  }, [projectId]);

  const save = useCallback(async (input: EditScriptInput) => {
    if (!projectId) return;
    setIsSaving(true);
    try {
      const nextState = await editScript(projectId, input);
      setState(nextState);
      setPipeline(await getPipeline(projectId));
      setError(null);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "保存文案失败");
    } finally {
      setIsSaving(false);
    }
  }, [projectId]);

  const confirm = useCallback(async () => {
    if (!projectId) return;
    setIsConfirming(true);
    try {
      const nextState = await confirmScript(projectId);
      setState(nextState);
      setPipeline(await getPipeline(projectId));
      setError(null);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "确认文案失败");
    } finally {
      setIsConfirming(false);
    }
  }, [projectId]);

  return { state, pipeline, isLoading, isStarting, isSaving, isConfirming, error, load, start, save, confirm };
}
