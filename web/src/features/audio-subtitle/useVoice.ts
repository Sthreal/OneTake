import { useCallback, useEffect, useState } from "react";

import { getPipeline } from "../../shared/api/recognitionApi";
import { getVoice, requestVoice } from "../../shared/api/voiceApi";
import type { PipelineState } from "../recognition/types";
import type { VoiceRequestInput, VoiceState } from "./types";

const EMPTY_STATE: VoiceState = { run: null };
const ACTIVE_STATUSES = new Set(["queued", "generating"]);
const ACTIVE_PIPELINE = new Set(["voice_queued", "voice_generating", "subtitle_queued", "subtitle_generating"]);
const CHANGE_EVENT = "onetake:audio-subtitle-changed";

export function useVoice(projectId: string | null) {
  const [state, setState] = useState<VoiceState>(EMPTY_STATE);
  const [pipeline, setPipeline] = useState<PipelineState | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isStarting, setIsStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (silent = false) => {
    if (!projectId) return;
    if (!silent) setIsLoading(true);
    try {
      const [nextState, nextPipeline] = await Promise.all([getVoice(projectId), getPipeline(projectId)]);
      setState(nextState);
      setPipeline(nextPipeline);
      setError(null);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "读取配音状态失败");
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
    const status = state.run?.status;
    const pipelineStatus = pipeline?.status;
    const active = status && ACTIVE_STATUSES.has(status) || pipelineStatus && ACTIVE_PIPELINE.has(pipelineStatus);
    if (!projectId || !active) return;
    const timer = window.setInterval(() => void load(true), 1500);
    return () => window.clearInterval(timer);
  }, [projectId, state.run?.status, pipeline?.status, load]);

  useEffect(() => {
    const refresh = () => void load(true);
    window.addEventListener(CHANGE_EVENT, refresh);
    return () => window.removeEventListener(CHANGE_EVENT, refresh);
  }, [load]);

  const start = useCallback(async (input: VoiceRequestInput) => {
    if (!projectId) return;
    setIsStarting(true);
    try {
      const nextState = await requestVoice(projectId, input);
      setState(nextState);
      setPipeline(await getPipeline(projectId));
      setError(null);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "生成配音失败");
    } finally {
      setIsStarting(false);
    }
  }, [projectId]);

  return { state, pipeline, isLoading, isStarting, error, load, start };
}
