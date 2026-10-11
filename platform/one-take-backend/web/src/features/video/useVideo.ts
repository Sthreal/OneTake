import { useCallback, useEffect, useState } from "react";

import { getPipeline } from "../../shared/api/recognitionApi";
import {
  acceptSegmentCandidate,
  createVideoPlan,
  generateSegmentCandidate,
  getOutput,
  getVideo,
  getVideoEstimate,
  getVideoSegments,
  rejectSegment,
  requestVideo,
  startVideoBatch,
  stopVideoBatch,
} from "../../shared/api/videoApi";
import type { PipelineState } from "../recognition/types";
import type { OutputArtifact, ProductTemplateId, VideoEstimate, VideoMode, VideoSegmentState, VideoState } from "./types";

const EMPTY_STATE: VideoState = { plan: null };
const EMPTY_SEGMENTS: VideoSegmentState = { plan_id: null, segments: [] };
const ACTIVE_VIDEO = new Set(["video_generating", "video_ready", "rendering"]);

export function useVideo(projectId: string | null) {
  const [state, setState] = useState<VideoState>(EMPTY_STATE);
  const [output, setOutput] = useState<OutputArtifact | null>(null);
  const [pipeline, setPipeline] = useState<PipelineState | null>(null);
  const [estimate, setEstimate] = useState<VideoEstimate | null>(null);
  const [segments, setSegments] = useState<VideoSegmentState>(EMPTY_SEGMENTS);
  const [segmentBusy, setSegmentBusy] = useState(false);
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
      if (nextState.plan?.mode === "product") {
        getVideoSegments(projectId).then(setSegments).catch(() => setSegments(EMPTY_SEGMENTS));
      } else {
        setSegments(EMPTY_SEGMENTS);
      }
      if (!silent) setError(null);
    } catch (requestError) {
      if (!silent) setError(requestError instanceof Error ? requestError.message : "读取视频状态失败");
    }
  }, [projectId]);

  useEffect(() => {
    setState(EMPTY_STATE);
    setOutput(null);
    setPipeline(null);
    setEstimate(null);
    setSegments(EMPTY_SEGMENTS);
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
      if (!created.plan) throw new Error("视频方案创建失败");
      const nextEstimate = await getVideoEstimate(projectId, created.plan.plan_id);
      setEstimate(nextEstimate);
      if (nextEstimate.requires_confirmation) return;
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

  const confirmGenerate = useCallback(async () => {
    if (!projectId) return;
    setIsStarting(true);
    setError(null);
    try {
      setEstimate(null);
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

  const cancelGenerate = useCallback(() => setEstimate(null), []);

  const refreshSegments = useCallback(async () => {
    if (!projectId) return;
    try {
      setSegments(await getVideoSegments(projectId));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "读取分段状态失败");
    }
  }, [projectId]);

  const generateSegment = useCallback(async (segmentId: string) => {
    if (!projectId) return;
    setSegmentBusy(true);
    setError(null);
    try {
      setSegments(await generateSegmentCandidate(projectId, segmentId));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "生成分段失败");
    } finally {
      setSegmentBusy(false);
    }
  }, [projectId]);

  const acceptSegment = useCallback(async (segmentId: string, candidateId: string) => {
    if (!projectId) return;
    setSegmentBusy(true);
    setError(null);
    try {
      setSegments(await acceptSegmentCandidate(projectId, segmentId, candidateId));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "接受分段失败");
    } finally {
      setSegmentBusy(false);
    }
  }, [projectId]);

  const rejectSegmentCandidate = useCallback(async (segmentId: string) => {
    if (!projectId) return;
    setSegmentBusy(true);
    setError(null);
    try {
      setSegments(await rejectSegment(projectId, segmentId));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "拒绝分段失败");
    } finally {
      setSegmentBusy(false);
    }
  }, [projectId]);

  const startBatch = useCallback(async () => {
    if (!projectId) return;
    setSegmentBusy(true);
    setError(null);
    try {
      setState(await startVideoBatch(projectId));
      await refreshSegments();
      setOutput(await getOutput(projectId));
      setPipeline(await getPipeline(projectId));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "批量生成失败");
    } finally {
      setSegmentBusy(false);
    }
  }, [projectId, refreshSegments]);

  const stopBatch = useCallback(async () => {
    if (!projectId) return;
    try {
      setState(await stopVideoBatch(projectId));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "停止批量失败");
    }
  }, [projectId]);

  return {
    state, output, pipeline, estimate, segments, isStarting, segmentBusy, error,
    load, generate, confirmGenerate, cancelGenerate,
    generateSegment, acceptSegment, rejectSegment: rejectSegmentCandidate, startBatch, stopBatch, refreshSegments,
  };
}
