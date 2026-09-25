import { useCallback, useEffect, useState } from "react";

import { getPipeline } from "../../shared/api/recognitionApi";
import { confirmAudioSubtitle, getSubtitle, updateSubtitle } from "../../shared/api/subtitleApi";
import type { PipelineState } from "../recognition/types";
import type { SubtitleSegment, SubtitleState } from "./types";

const EMPTY_STATE: SubtitleState = { version: null };
const ACTIVE_SUBTITLE = new Set(["queued", "generating"]);
const ACTIVE_PIPELINE = new Set(["voice_queued", "voice_generating", "subtitle_queued", "subtitle_generating"]);
const CHANGE_EVENT = "onetake:audio-subtitle-changed";

export function useSubtitle(projectId: string | null) {
  const [state, setState] = useState<SubtitleState>(EMPTY_STATE);
  const [pipeline, setPipeline] = useState<PipelineState | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isConfirming, setIsConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (silent = false) => {
    if (!projectId) return;
    try {
      const [nextState, nextPipeline] = await Promise.all([getSubtitle(projectId), getPipeline(projectId)]);
      setState(nextState); setPipeline(nextPipeline); setError(null);
    } catch (requestError) {
      if (!silent) setError(requestError instanceof Error ? requestError.message : "读取字幕状态失败");
    }
  }, [projectId]);

  useEffect(() => { setState(EMPTY_STATE); setPipeline(null); setError(null); if (projectId) void load(); }, [projectId, load]);

  useEffect(() => {
    const subtitleStatus = state.version?.status;
    const pipelineStatus = pipeline?.status;
    if (!projectId || (!subtitleStatus && !pipelineStatus)) return;
    const active = (subtitleStatus && ACTIVE_SUBTITLE.has(subtitleStatus)) || (pipelineStatus && ACTIVE_PIPELINE.has(pipelineStatus));
    if (!active) return;
    const timer = window.setInterval(() => void load(true), 1500);
    return () => window.clearInterval(timer);
  }, [projectId, state.version?.status, pipeline?.status, load]);

  const save = useCallback(async (segments: SubtitleSegment[]) => {
    if (!projectId) return;
    setIsSaving(true);
    try {
      const nextState = await updateSubtitle(projectId, segments);
      setState(nextState); setPipeline(await getPipeline(projectId)); window.dispatchEvent(new Event(CHANGE_EVENT)); setError(null);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "保存字幕失败");
    } finally { setIsSaving(false); }
  }, [projectId]);

  const confirm = useCallback(async () => {
    if (!projectId) return;
    setIsConfirming(true);
    try {
      await confirmAudioSubtitle(projectId);
      await load(true);
      window.dispatchEvent(new Event(CHANGE_EVENT));
      setError(null);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "确认字幕失败");
    } finally { setIsConfirming(false); }
  }, [projectId, load]);

  return { state, pipeline, isSaving, isConfirming, error, load, save, confirm };
}
