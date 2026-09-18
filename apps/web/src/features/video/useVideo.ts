import { useCallback, useEffect, useState } from "react";

import { getPipeline } from "../../shared/api/recognitionApi";
import { createVideoPlan, getOutput, getVideo, requestVideo } from "../../shared/api/videoApi";
import type { PipelineState } from "../recognition/types";
import type { OutputArtifact, ProductTemplateId, VideoMode, VideoState } from "./types";

const EMPTY_STATE: VideoState = { plan: null };
const ACTIVE_VIDEO = new Set(["video_generating", "video_ready", "rendering"]);

export function useVideo(projectId: string | null) {
  const [state, setState] = useState<VideoState>(EMPTY_STATE);
  const [output, setOutput] = useState<OutputArtifact | null>(null);
  const [pipeline, setPipeline] = useState<PipelineState | null>(null);
  const [isStarting, setIsStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (silent = false) => {
    if (!projectId) return;
    try {
      const [nextState, nextOutput, nextPipeline] = await Promise.all([
        getVideo(projectId),
        getOutput(projectId),
        getPipeline(projectId),
      ]);
      setState(nextState);
      setOutput(nextOutput);
      setPipeline(nextPipeline);
      if (!silent) setError(null);
    } catch (requestError) {
      if (!silent) setError(requestError instanceof Error ? requestError.message : "读取视频状态失败");
    }
  }, [projectId]);

  useEffect(() => {
    setState(EMPTY_STATE);
    setOutput(null);
    setPipeline(null);
    setError(null);
    if (projectId) void load();
  }, [projectId, load]);

  useEffect(() => {
    const status = state.plan?.status;
    if (!projectId || !status || !ACTIVE_VIDEO.has(status)) return;
    const timer = window.setInterval(() => void load(true), 1500);
    return () => window.clearInterval(timer);
  }, [projectId, state.plan?.status, load]);

  const generate = useCallback(async (mode: VideoMode, templateId: ProductTemplateId | null) => {
    if (!projectId) return;
    setIsStarting(true);
    setError(null);
    try {
      const created = await createVideoPlan(projectId, mode, templateId);
      setState(created);
      const started = await requestVideo(projectId);
      setState(started);
      setOutput(null);
      setPipeline(await getPipeline(projectId));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "启动视频生成失败");
    } finally {
      setIsStarting(false);
    }
  }, [projectId]);

  return { state, output, pipeline, isStarting, error, load, generate };
}
