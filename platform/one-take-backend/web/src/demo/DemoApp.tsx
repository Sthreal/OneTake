/** 托管主路（演示用）：一次输入 → 2 次点击 → 拿到成片。
 *
 * 设计依据：docs/前端重建方案-核心链路契约与结构.md §10（用户可见 3 屏 + 托管模式代按策略）。
 * 这里**只调用既有端点**，不改后端；复杂阶段（前 4 段）交给后端自动链 POST /auto-run。
 *
 * 访问方式：`?demo=1`（现有 ?legacy=1 与默认工作台都不受影响）。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { approveCost, startAutoRun } from "./api";
import "./demo.css";
import { PIPELINE_STEPS, gateNeedsHuman, keyframeReadyFor, oneShotEligibility, pickKeyframeCandidate, resumeStageFromStatus, stepIndexFromStatus, summarizeKeyframes, voiceSubtitleAutoApprovable } from "./policy";
import { confirmContentPlan, generateContentPlan, getContentPlan } from "../shared/api/contentPlanApi";
import { getPipeline, getRecognition } from "../shared/api/recognitionApi";
import { listCharacters } from "../shared/api/characterApi";
import { FileDrop } from "./FileDrop";
import { runProjectIntake, until } from "./intake";
import { getScript } from "../shared/api/scriptApi";
import { confirmAudioSubtitle, getSubtitle } from "../shared/api/subtitleApi";
import { getVoice } from "../shared/api/voiceApi";
import {
  acceptKeyframe,
  acknowledgeGateWarnings,
  createVideoPlan,
  generateKeyframeCandidates,
  getGateReport,
  getKeyframes,
  getOutput,
  getVideo,
  getVideoEstimate,
  requestVideo,
  startVideoBatch,
} from "../shared/api/videoApi";
import { getCompliance } from "../shared/api/videoApi";

type Phase = "input" | "running" | "review" | "producing" | "done" | "stopped";

interface LogLine {
  text: string;
  err?: boolean;
}

export function DemoApp({ initialPath = "one_shot", initialProjectId = null }: { initialPath?: "one_shot" | "segmented"; initialProjectId?: string | null } = {}) {
  const [phase, setPhase] = useState<Phase>("input");
  const [log, setLog] = useState<LogLine[]>([]);
  const [name, setName] = useState("演示商品");
  const [sellingPoint, setSellingPoint] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [inputMode, setInputMode] = useState<"file" | "url">("file");
  const [productUrl, setProductUrl] = useState("");
  const [progressIndex, setProgressIndex] = useState(-1);
  const [path, setPath] = useState<"one_shot" | "segmented">(initialPath);
  const [resumed, setResumed] = useState(false);
  const [needsConfirm, setNeedsConfirm] = useState(false);
  const [voiceInfo, setVoiceInfo] = useState<{ status: string; seconds: number | null; voiceId: string; audioUrl: string | null } | null>(null);
  const [subtitleInfo, setSubtitleInfo] = useState<{ status: string; segments: number } | null>(null);
  const [live, setLive] = useState<{ status: string; step: number; at: string; jobRunning: boolean } | null>(null);
  const [kfState, setKfState] = useState<{ mode: string; gridUrl: string | null; gridUnusable: boolean; keyframes: Parameters<typeof summarizeKeyframes>[0] } | null>(null);
  const [publishText, setPublishText] = useState("");
  const [aigcText, setAigcText] = useState("");
  const [projectId, setProjectId] = useState<string | null>(null);
  // 出镜人（人物库）：选一个人 → 成片里的人物由母版锁住同一个人；复用已有母版不额外花钱
  const [characters, setCharacters] = useState<{ character_id: string; name: string; source: string }[]>([]);
  const [characterId, setCharacterId] = useState<string>("");
  const [stopReason, setStopReason] = useState<string | null>(null);
  const [scriptText, setScriptText] = useState<string>("");
  const [scenes, setScenes] = useState<{ scene_id: string; order: number; start_seconds: number; end_seconds: number; script_excerpt: string }[]>([]);
  const [estimate, setEstimate] = useState<{ plan_id: string; estimated_known_cost: number; estimated_cost_max: number | null; missing_price_config: string[]; price_notes: string[]; path: string } | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [gate, setGate] = useState<{ status: string; download_allowed: boolean; checks: { id: string; level: string; label: string; message: string }[] } | null>(null);
  const busy = phase === "running" || phase === "producing";
  // S3：小白模式「一次生成整片」的能力上限。时长取"分镜时间轴"与"配音时长"的较大者 ——
  // 后端 `plan.duration_seconds` 是跟随配音时长的，两边口径对齐才不会出现"前端说行、后端说不行"。
  const timelineSeconds = scenes.reduce((max, scene) => Math.max(max, scene.end_seconds), 0);
  const oneShot = oneShotEligibility({
    durationSeconds: Math.max(timelineSeconds, voiceInfo?.seconds ?? 0),
    shotCount: scenes.length,
  });
  const blockedByLimit = path === "one_shot" && !oneShot.allowed;
  useEffect(() => {
    // 人物库读不到不该挡住主路（可选功能），所以只记一句提示
    void listCharacters()
      .then((list) => setCharacters(list.characters))
      .catch(() => setCharacters([]));
  }, []);
  const logRef = useRef<HTMLUListElement | null>(null);

  const say = useCallback((text: string, err = false) => {
    setLog((prev) => [...prev, { text, err }]);
    queueMicrotask(() => logRef.current?.scrollTo({ top: 999999 }));
  }, []);

  const stop = useCallback((reason: string) => {
    setStopReason(reason);
    setPhase("stopped");
    say("已停下等你处理：" + reason, true);
  }, [say]);

  /** 第 1 次点击：输入 → 自动跑前 4 段 → 到闸口① 停 */
  const runUntilReview = useCallback(async () => {
    if (busy) return;
    if (inputMode === "file" && !file) return;
    if (inputMode === "url" && !productUrl.trim()) return;
    setPhase("running");
    setStopReason(null);
    setProgressIndex(-1);
    try {
      // 输入链**只有一份实现**（`./intake`）：小白托管主路与导演模式共用，
      // 区别只在之后要不要人为干预。
      const id = await runProjectIntake(
        { mode: inputMode, file, productUrl, name, note: sellingPoint, characterId: characterId || undefined },
        { log: (text, err) => say(text, err), onStage: setProgressIndex },
      );
      setProjectId(id);

      await loadReviewData(id);
      say("到闸口①了：请看文案 + 分镜 + 费用，确认后出片。");
      setPhase("review");
    } catch (error) {
      stop(error instanceof Error ? error.message : "未知错误");
    }
  }, [busy, file, inputMode, name, path, productUrl, say, stop]);

  /** 读评审页需要的三样：文案 / 分镜 / 视频方案与预估（首次流程与"按 project_id 恢复"共用）。 */
  const loadReviewData = useCallback(async (id: string) => {
      // 1) 分镜方案：没有就生成一个（恢复流程里方案通常已存在，不重复生成）
      let plan = await getContentPlan(id);
      if (!plan) {
        say("生成分镜方案…");
        plan = await generateContentPlan(id);
      }
      if (plan?.variants?.length) {
        const variant = plan.variants[plan.selected_variant_index ?? 0];
        setScenes(variant.scenes.map((scene) => ({
          scene_id: scene.scene_id, order: scene.order, start_seconds: scene.start_seconds,
          end_seconds: scene.end_seconds, script_excerpt: scene.script_excerpt,
        })));
      }
      // 1.5) 配音/字幕确认（A4 策略）：后端 create_plan 会校验"配音/字幕已确认"，
      //      缺了就会抛"请先确认配音和字幕"——这时必须自动按或给用户一个按钮，不能只报错。
      const voice = await getVoice(id);
      const subtitle = await getSubtitle(id);
      const run = voice.run;
      const subtitleVersion = subtitle.version;
      setVoiceInfo(run ? { status: run.status, seconds: run.duration_seconds, voiceId: run.voice_id, audioUrl: run.audio_url } : null);
      setSubtitleInfo(subtitleVersion ? { status: subtitleVersion.status, segments: (subtitleVersion.segments ?? []).length } : null);
      if (run && run.status !== "confirmed") {
        const decision = voiceSubtitleAutoApprovable(
          run.duration_seconds, (subtitleVersion?.segments ?? []).length, null,
        );
        if (decision.auto) {
          await confirmAudioSubtitle(id);
          say(`配音与字幕已自动确认（时长 ${run.duration_seconds}s）。`);
        } else {
          setNeedsConfirm(true);
          throw new Error(`需要你确认配音与字幕：${decision.reason}`);
        }
      } else if (subtitleVersion && subtitleVersion.status !== "confirmed") {
        await confirmAudioSubtitle(id);
        say("字幕已自动确认。");
      }

      // 2) 文案 + 合规声明
      const script = await getScript(id);
      const version = script.version as Record<string, unknown> | null;
      setScriptText(String(version?.full_text ?? version?.hook ?? "（文案未返回，请在导演模式查看）"));
      setPublishText(
        [String(version?.hook ?? ""), String(version?.cta ?? ""), String(version?.full_text ?? "")]
          .filter((part) => part.trim().length > 0).join("\n"),
      );
      try {
        const compliance = await getCompliance(id);
        setAigcText(
          compliance.aigc_label_enabled
            ? `本视频由 AI 生成（${compliance.aigc_label_text}），已按 ${compliance.rules_version} 在片内标注。`
            : "（当前未开启 AIGC 标识，发布前请自行确认平台要求）",
        );
      } catch { /* 合规信息拿不到不影响主流程 */ }

      say("准备视频方案与费用预估…");
      // 复用**已有方案**：每次新建都会换 plan_id → base 视频路径跟着变 → 已生成的最贵产物（r2v 视频）
      // 就找不到了，等于白花一次钱还可能再失败（2026-10-15 实测）。只有"没有方案"或"路径不同"才新建。
      const current = await getVideo(id);
      const existing = current.plan;
      let planId: string | null = existing?.plan_id ?? null;
      if (!planId || existing?.path !== path) {
        let created;
        try {
          created = await createVideoPlan(id, "product", "clean", path);
        } catch (error) {
          const text = error instanceof Error ? error.message : "";
          if (text.includes("配音") || text.includes("字幕")) {
            setNeedsConfirm(true);
            throw new Error("需要你确认配音与字幕：点下面那张「配音与字幕」卡片上的按钮即可（不花钱）");
          }
          throw error;
        }
        if (!created.plan) throw new Error("视频方案创建失败");
        planId = created.plan.plan_id;
        say(`已创建视频方案 ${planId}（路径 ${path}）。`);
      } else {
        say(`复用已有视频方案 ${planId}（路径 ${existing?.path}）—— 已生成的视频会直接复用，不重复付费。`);
      }
      void 0;
      const nextEstimate = await getVideoEstimate(id, planId);
      setEstimate({
        plan_id: nextEstimate.plan_id, estimated_known_cost: nextEstimate.estimated_known_cost,
        estimated_cost_max: nextEstimate.estimated_cost_max,
        missing_price_config: nextEstimate.missing_price_config, price_notes: nextEstimate.price_notes,
        path: nextEstimate.path,
      });
      if (nextEstimate.missing_price_config.length > 0) {
        say(`⚠️ 有单价未配置：${nextEstimate.missing_price_config.join("、")}`, true);
      }
  }, [say]);

  /** 常驻轮询：项目一打开就每 5s 读一次 /pipeline 与 /video，把"现在到哪一段"显示出来。 */
  useEffect(() => {
    if (!projectId) return;
    let stopped = false;
    const tick = async () => {
      try {
        const pipeline = await getPipeline(projectId);
        const video = await getVideo(projectId);
        if (stopped) return;
        const status = video.plan?.status ?? "";
        const planLive = ["video_generating", "rendering", "video_ready"].includes(status);
        const busyStatus = /(queued|generating|recognizing|editing|matting|rendering)/.test(pipeline.status) || planLive;
        setLive({
          status: planLive ? `${pipeline.status} / 视频 ${status}` : pipeline.status,
          step: pipeline.current_step ?? 0,
          at: new Date().toLocaleTimeString(),
          jobRunning: busyStatus,
        });
        setProgressIndex(stepIndexFromStatus(pipeline.status));
        if (resumeStageFromStatus(pipeline.status) === "done" && phase !== "done" && phase !== "review") {
          const artifact = await getOutput(projectId);
          if (stopped) return;
          setVideoUrl((artifact as unknown as { download_url?: string; url?: string } | null)?.download_url ?? null);
          setGate(await getGateReport(projectId));
          setPhase("done");
        }
      } catch { /* 轮询失败不打扰用户，下一轮再试 */ }
    };
    void tick();
    const timer = window.setInterval(tick, 5000);
    return () => { stopped = true; window.clearInterval(timer); };
  }, [phase, projectId]);

  /** 按 project_id 恢复：从后端读回进度，决定进"继续轮询 / 审核页 / 成片页"。 */
  useEffect(() => {
    if (!initialProjectId || resumed) return;
    setResumed(true);
    const id = initialProjectId;
    setProjectId(id);
    setPhase("running");
    void (async () => {
      try {
        say(`已打开项目 ${id}，正在从后端读取进度…`);
        const pipeline = await until(
          async () => {
            const value = await getPipeline(id);
            setProgressIndex(stepIndexFromStatus(value.status));
            return value;
          },
          (value) => resumeStageFromStatus(value.status) !== "poll",
          { intervalMs: 3000 },
        );
        const stage = resumeStageFromStatus(pipeline.status);
        say(`后端状态：${pipeline.status} → ${stage === "done" ? "成片页" : stage === "review" ? "审核页" : "未知状态"}`);
        if (stage === "done") {
          try {
            const kf = await getKeyframes(id);
            setKfState({ mode: kf.mode, gridUrl: kf.grid_image_url ?? null, gridUnusable: Boolean(kf.grid_unusable), keyframes: kf.keyframes as unknown as Parameters<typeof summarizeKeyframes>[0] });
          } catch { /* 展示用 */ }
          const artifact = await getOutput(id);
          setVideoUrl((artifact as unknown as { download_url?: string; url?: string } | null)?.download_url ?? null);
          const report = await getGateReport(id);
          setGate(report);
          setPhase(gateNeedsHuman(report).auto ? "done" : "stopped");
          if (!gateNeedsHuman(report).auto) setStopReason(gateNeedsHuman(report).auto === false ? "交付门需要你确认" : null);
          return;
        }
        if (stage === "review" || stage === "retry") {
          await loadReviewData(id);
          setPhase("review");
          if (stage === "retry") {
            setStopReason("上一次运行失败了（failed / interrupted）。已重新读取方案与费用："
              + "点「就用这个，出片」即可从断点继续 —— 视频若已生成会直接复用，不再重复付费。");
          }
          return;
        }
        stop(`无法从状态 "${pipeline.status}" 判断进度，请在页面刷新后重试或告诉我`);
      } catch (error) {
        stop(error instanceof Error ? error.message : "读取项目失败");
      }
    })();
  }, [initialProjectId, loadReviewData, resumed, say, stop]);

  /** 第 2 次点击：批准费用 → 关键帧自动采纳 → 出片 */
  const produce = useCallback(async () => {
    if (!projectId || !estimate || busy) return;
    setPhase("producing");
    try {
      say("确认分镜（闸口①）…");
      await confirmContentPlan(projectId);

      say("登记费用批准（闸口②，绑定当前方案 payload_hash）…");
      await approveCost(projectId, estimate.plan_id);

      say("关键帧：逐镜生成、过线就自动采纳…");
      const state = await until(() => getKeyframes(projectId), () => true, { intervalMs: 1000 });
      const mode = state.mode;
      for (const slot of state.keyframes) {
        if (slot.accepted) continue;
        await generateKeyframeCandidates(projectId, slot.scene_id, { n: 2 });
        // 只等"这一镜"的候选（原先要求所有镜都有候选 → 第 1 镜就永远等不到，页面卡死）
        const refreshed = await until(
          () => getKeyframes(projectId),
          (value) => keyframeReadyFor(value.keyframes, slot.scene_id),
          { intervalMs: 4000, timeoutMs: 15 * 60 * 1000 },
        );
        const target = refreshed.keyframes.find((item) => item.scene_id === slot.scene_id);
        if (!target) continue;
        const decision = pickKeyframeCandidate(
          { scene_id: target.scene_id, order: target.order, mode, candidates: target.candidates },
          mode,
        );
        if (!decision.auto) {
          stop(`关键帧：${decision.reason}`);
          return;
        }
        await acceptKeyframe(projectId, target.scene_id, decision.value.keyframe_id);
        say(`第 ${target.order} 镜关键帧已自动采纳（相似度 ${(decision.value.product_match ?? 0).toFixed(3)}）`);
      }

      if (path === "segmented") {
        say("逐镜生成：每一镜单独出候选 → 按序自动采纳 → 本地合成（分钟级，请不要关页面）…");
        await startVideoBatch(projectId);
      } else {
        try {
        const afterKeyframes = await getKeyframes(projectId);
        setKfState({ mode: afterKeyframes.mode, gridUrl: afterKeyframes.grid_image_url ?? null, gridUnusable: Boolean(afterKeyframes.grid_unusable), keyframes: afterKeyframes.keyframes as unknown as Parameters<typeof summarizeKeyframes>[0] });
      } catch { /* 卡片是展示用，拿不到不影响出片 */ }
      say("开始出片（整片一次生成 / r2v，可能要十几分钟，请不要关页面）…");
        await requestVideo(projectId);
      }
      const plan = await until(
        () => getVideo(projectId),
        (value) => value.plan !== null && ["completed", "failed"].includes(value.plan.status),
      );
      if (plan.plan?.status === "failed") {
        stop(`视频生成失败：${plan.plan.error_code ?? "未知原因"}`);
        return;
      }
      say("成片完成，读取产物与交付门结论…");
      const artifact = await getOutput(projectId);
      setVideoUrl((artifact as unknown as { download_url?: string; url?: string } | null)?.download_url
        ?? (artifact as unknown as { url?: string } | null)?.url ?? plan.plan?.video_url ?? null);
      const report = await getGateReport(projectId);
      setGate(report);
      const gateDecision = gateNeedsHuman(report);
      if (!gateDecision.auto) {
        stop(gateDecision.reason);
        return;
      }
      say("交付门全过，可以下载。");
      setPhase("done");
    } catch (error) {
      stop(error instanceof Error ? error.message : "未知错误");
    }
  }, [busy, estimate, path, projectId, say, stop]);

  /** 审核页「换一版」：重新生成分镜（免费），并重建视频方案 + 预估（改方案 → 旧批准自动失效）。 */
  /** 切出片路径：必须**重建视频方案 + 重新预估**（后端 payload_hash 绑定整份预估，改路径即失效）。 */
  const selectPath = useCallback(async (next: "one_shot" | "segmented") => {
    if (!projectId || busy) return;
    // 点「已经选中的那条路」也要有反应：重建方案 + 重新预估（原先这里直接 return，用户看到"点了没反应"，
    // 而旧方案可能卡在 video_generating —— 重建是唯一的自救方式）。
    say(next === path
      ? "这条路已经是当前选择；按新方案重建 + 重新预估（用于方案卡住时重来）。"
      : "切换生成路径…");
    setPath(next);
    try {
      const created = await createVideoPlan(projectId, "product", "clean", next);
      if (!created.plan) return;
      const nextEstimate = await getVideoEstimate(projectId, created.plan.plan_id);
      setEstimate({
        plan_id: nextEstimate.plan_id, estimated_known_cost: nextEstimate.estimated_known_cost,
        estimated_cost_max: nextEstimate.estimated_cost_max,
        missing_price_config: nextEstimate.missing_price_config, price_notes: nextEstimate.price_notes,
        path: nextEstimate.path,
      });
      say(`已切换到${next === "one_shot" ? "整片一次生成" : "逐镜生成"}，费用按新方案重新预估。`);
    } catch (error) {
      say(error instanceof Error ? error.message : "切换路径失败", true);
    }
  }, [busy, path, projectId, say]);

  const regenerateReview = useCallback(async () => {
    if (!projectId || busy) return;
    try {
      say("重新生成分镜方案…");
      // 重新生成走同一个 POST（服务端会产出新方案），随后必须重建视频方案与预估
      await generateContentPlan(projectId);
      const plan = await getContentPlan(projectId);
      const variant = plan?.variants?.[plan.selected_variant_index ?? 0];
      if (variant) {
        setScenes(variant.scenes.map((scene) => ({
          scene_id: scene.scene_id, order: scene.order, start_seconds: scene.start_seconds,
          end_seconds: scene.end_seconds, script_excerpt: scene.script_excerpt,
        })));
      }
      const created = await createVideoPlan(projectId, "product", "clean", "one_shot");
      if (created.plan) {
        const nextEstimate = await getVideoEstimate(projectId, created.plan.plan_id);
        setEstimate({
          plan_id: nextEstimate.plan_id, estimated_known_cost: nextEstimate.estimated_known_cost,
          estimated_cost_max: nextEstimate.estimated_cost_max,
          missing_price_config: nextEstimate.missing_price_config, price_notes: nextEstimate.price_notes,
          path: nextEstimate.path,
        });
        say("已换一版分镜，费用按新方案重新预估（旧批准已失效）。");
      }
    } catch (error) {
      say(error instanceof Error ? error.message : "换一版失败", true);
    }
  }, [busy, projectId, say]);

  /** 重读成片产物 + 交付门（幂等、不花钱）：用于"合成完成但页面没拿到地址"的情况。 */
  const refreshOutput = useCallback(async () => {
    if (!projectId) return;
    try {
      const artifact = await getOutput(projectId);
      const url = (artifact as unknown as { download_url?: string; url?: string } | null)?.download_url
        ?? (artifact as unknown as { url?: string } | null)?.url ?? null;
      setVideoUrl(url);
      setGate(await getGateReport(projectId));
      say(url ? "已读到成片地址，可以下载了。" : "后端还没有成片产物（视频可能仍在合成）。");
    } catch (error) {
      say(error instanceof Error ? error.message : "读取成片失败", true);
    }
  }, [projectId, say]);

  /** 从"当前后端状态"继续出片：跳过已采纳关键帧，只补没过的镜，然后出片。
   *  用于页面卡住/刷新后自救（幂等：已采纳的不重复生成、费用批准可重复提交）。 */
  const retryRender = useCallback(async () => {
    if (!projectId) return;
    setStopReason(null);
    setNeedsConfirm(false);
    try {
      if (!estimate) {
        // 之前这里是静默 return（用户点了"没反应"）。改为：先重读方案与费用，再让用户点"出片"。
        say("没有当前方案的预估，先重新读取方案与费用…");
        await loadReviewData(projectId);
        setPhase("review");
        say("已读到方案与费用，请点「就用这个，出片」继续（已生成的视频会复用，不重复付费）。");
        return;
      }
      say("继续出片：读取已采纳的关键帧…");
      await produce();
    } catch (error) {
      stop(error instanceof Error ? error.message : "继续失败");
    }
  }, [estimate, loadReviewData, produce, projectId, say, stop]);

  /** 人工确认配音与字幕（A4 判定不通过时的兜底按钮）→ 继续到审核页。 */
  const confirmAudioSubtitleManually = useCallback(async () => {
    if (!projectId) return;
    try {
      await confirmAudioSubtitle(projectId);
      say("配音与字幕已确认。");
      setNeedsConfirm(false);
      setStopReason(null);
      await loadReviewData(projectId);
      setPhase("review");
    } catch (error) {
      say(error instanceof Error ? error.message : "确认失败", true);
    }
  }, [loadReviewData, projectId, say]);

  /** 重试继续：重新读一遍后端状态（前 4 段可能已经跑完了）。 */
  const retryContinue = useCallback(async () => {
    if (!projectId) return;
    try {
      setStopReason(null);
      setNeedsConfirm(false);
      const pipeline = await getPipeline(projectId);
      setProgressIndex(stepIndexFromStatus(pipeline.status));
      await loadReviewData(projectId);
      setPhase("review");
      say("已重新读取后端状态，继续到审核页。");
    } catch (error) {
      stop(error instanceof Error ? error.message : "重试失败");
    }
  }, [loadReviewData, projectId, say, stop]);

  const acknowledge = useCallback(async () => {
    if (!projectId || !gate) return;
    const ids = gate.checks.filter((item) => item.level !== "ok").map((item) => item.id);
    const updated = await acknowledgeGateWarnings(projectId, ids);
    setGate(updated);
    const decision = gateNeedsHuman(updated);
    if (decision.auto) {
      say("警告已逐条确认，交付门放行。");
      setPhase("done");
    } else if (updated.status === "fail" || !updated.download_allowed) {
      stop(decision.reason);
    }
  }, [gate, projectId, say, stop]);

  const stepIndex = useMemo(() => {
    if (phase === "input") return 0;
    if (phase === "running") return 1;
    if (phase === "review") return 2;
    return 3;
  }, [phase]);

  return (
    <div className="demo-shell">
      <div className="demo-wrap">
        <div className="demo-head">
          <div>
            <b>ONE TAKE · <em>演示主路</em></b>
            <small>商品图 → 2 次点击 → 成片（默认：九宫格关键帧 + one_shot）</small>
          </div>
          <div className="demo-steps">
            {["① 输入", "② 自动跑", "③ 确认出片", "④ 成片"].map((label, index) => (
              <span key={label} className={index === stepIndex ? "on" : undefined}>{label}</span>
            ))}
          </div>
        </div>

        {live ? (
          <div className="demo-live">
            <span className={`dot${live.jobRunning ? " busy" : ""}`} />
            <span>后端状态：<b>{live.status}</b></span>
            <span>第 {live.step}/9 段</span>
            <span>{live.at} 更新</span>
            {live.jobRunning ? <span>· 运行中，请勿关页面</span> : null}
          </div>
        ) : null}

        {phase === "input" ? (
          <div className="demo-card">
            <h2>给我一张商品图</h2>
            <p className="hint">点「开始生成」后，识别 / 去背主图 / 文案 / 配音字幕会全自动跑完，只在需要你拍板时停下。</p>
            <div className="demo-tabs">
              <button className={"demo-btn" + (inputMode === "file" ? " primary" : "")} onClick={() => setInputMode("file")}>上传商品图</button>
              <button className={"demo-btn" + (inputMode === "url" ? " primary" : "")} onClick={() => setInputMode("url")}>商品链接</button>
            </div>
            {characters.length > 0 ? (
              <div className="demo-row" style={{ marginTop: 10 }}>
                <select value={characterId} onChange={(event) => setCharacterId(event.target.value)}>
                  <option value="">不出镜人（纯商品）</option>
                  {characters.map((character) => (
                    <option key={character.character_id} value={character.character_id}>
                      {character.name}{character.source === "generated" ? "（四视角母版）" : "（照片）"}
                    </option>
                  ))}
                </select>
                <span className="demo-muted">出镜人来自「库 → 出镜人」：母版入库一次，任何项目复用都不再花钱</span>
              </div>
            ) : null}
            {inputMode === "file" ? (
              <>
                <FileDrop file={file} onPick={setFile} disabled={busy} />
                <div className="demo-row">
                  <input value={name} onChange={(event) => setName(event.target.value)} placeholder="商品名（写真实的，例如：冷萃橙汁）" />
                  <input
                    value={sellingPoint}
                    onChange={(event) => setSellingPoint(event.target.value)}
                    placeholder="核心卖点（选填，例如：0 糖解腻）"
                  />
                  <button className="demo-btn primary" disabled={!file || busy} onClick={() => void runUntilReview()}>开始生成</button>
                </div>
              </>
            ) : (
              <div className="demo-row">
                <input
                  value={productUrl}
                  onChange={(event) => setProductUrl(event.target.value)}
                  placeholder="贴商品链接（淘宝/京东/拼多多/独立站…）"
                />
                <button className="demo-btn primary" disabled={!productUrl.trim()} onClick={() => void runUntilReview()}>开始生成</button>
              </div>
            )}
          </div>
        ) : null}

        {phase === "review" && estimate ? (
          <div className="demo-card">
            <h2>就差你一句话：这版能用吗？</h2>
            <p className="hint">确认后开始计费并出片（一次批准覆盖全部付费步骤）。</p>
            <dl className="demo-kv">
              <dt>口播文案</dt><dd>{scriptText}</dd>
              <dt>出片方式</dt><dd>{path === "one_shot" ? "一次生成整片（镜头自然衔接）" : "逐镜生成（每一镜单独可控）"}</dd>
            </dl>
            <div className="demo-scenes">
              {scenes.map((scene) => (
                <div className="demo-scene" key={scene.scene_id}>
                  <span className="ord">{scene.order}</span>
                  <div>
                    <div className="sp-text">{scene.script_excerpt}</div>
                    <div className="meta">{scene.start_seconds}s – {scene.end_seconds}s</div>
                  </div>
                </div>
              ))}
            </div>
            <div className="demo-est">
              预估费用：<b>¥{estimate.estimated_known_cost}</b>
              {estimate.estimated_cost_max && estimate.estimated_cost_max !== estimate.estimated_known_cost
                ? <>（最坏 ¥{estimate.estimated_cost_max}）</> : null}
              <ul className="demo-log" style={{ marginTop: 6 }}>
                {estimate.price_notes.map((note) => <li key={note}>{note}</li>)}
              </ul>
            </div>
            {blockedByLimit ? (
              <div className="demo-est" style={{ marginTop: 12, borderColor: "#d97706" }}>
                <b>这条超过「一次生成整片」的上限</b>
                <p className="hint" style={{ marginTop: 6 }}>{oneShot.message}</p>
                <div className="demo-row" style={{ marginTop: 8 }}>
                  <button className="demo-btn primary" disabled={busy} onClick={() => void selectPath("segmented")}>
                    进导演模式做这条
                  </button>
                </div>
                <p className="hint" style={{ marginTop: 6 }}>
                  点了会把这一个项目改走逐镜生成：每一镜单独生成、可单镜重拍；逐镜控制台在后续版本提供。
                </p>
              </div>
            ) : null}
            <div className="demo-row" style={{ marginTop: 10 }}>
              <button className="demo-btn primary" disabled={busy || blockedByLimit} onClick={() => void produce()}>
                就用这个，出片
              </button>
              <button className="demo-btn" disabled={busy} onClick={() => void regenerateReview()}>
                换一版分镜（不花钱）
              </button>
              <span className="demo-muted">
                {blockedByLimit
                  ? "这条路超过「一次生成整片」的上限，先点上面的「进导演模式做这条」"
                  : "点下去 = 确认分镜 + 批准这笔费用 + 开始生成"}
              </span>
            </div>
          </div>
        ) : null}

        {phase === "done" ? (
          <div className="demo-card">
            <h2>成片好了</h2>
            {videoUrl ? (
              <video className="demo-video" src={videoUrl} controls />
            ) : (
              <p className="hint">还没拿到成片地址（可能仍在合成）。点下面的「刷新读取成片」重读一次后端。</p>
            )}
            <div className="demo-row" style={{ marginTop: 10 }}>
              {videoUrl ? <a className="demo-btn primary" href={videoUrl} download>下载 MP4</a> : null}
              {!videoUrl ? <button className="demo-btn primary" onClick={() => void refreshOutput()}>刷新读取成片</button> : null}
              <button className="demo-btn" onClick={() => window.location.reload()}>再做一条</button>
            </div>
            {kfState ? (() => {
              const summary = summarizeKeyframes(kfState.keyframes, kfState.mode);
              return (
                <div className="demo-card">
                  <h2>关键帧与九宫格</h2>
                  <div className="demo-kf-head">
                    <span className={"demo-badge" + (summary.gridMode ? " ok" : "")}>
                      {summary.gridMode ? "九宫格档（1 次调用出 4 格）" : "单帧档（每镜各 1 次）"}
                    </span>
                    <span className="demo-muted">
                      已采纳 {summary.accepted}/{summary.total}
                      {summary.averageMatch !== null ? ` ｜ 平均相似度 ${summary.averageMatch}` : ""}
                      {summary.fellBackScenes.length > 0 ? ` ｜ ${summary.fellBackScenes.join("、")} 镜走了单帧回退（网格该格未过线）` : ""}
                    </span>
                  </div>
                  {kfState.gridUrl ? (
                    <div className="demo-kf-sheet">
                      <img src={kfState.gridUrl} alt="九宫格整图" />
                      <span className="demo-muted">九宫格整图 · 一次调用出 4 格（模型原生切镜的基准）</span>
                    </div>
                  ) : null}
                  {kfState.gridUnusable ? (
                    <p className="demo-muted" style={{ margin: "0 0 10px" }}>
                      整片网格被判「不可用」（坏格过半）→ 后端已自动回退单帧档，不重复浪费
                    </p>
                  ) : null}
                  <div className="demo-kf-grid">
                    {kfState.keyframes.map((slot) => (
                      <div className="demo-kf" key={slot.scene_id}>
                        {slot.accepted?.image_url ? <img src={slot.accepted.image_url} alt={`第 ${slot.order} 镜关键帧`} /> : null}
                        <div className="meta">
                          <b>镜 {slot.order} · {slot.purpose ?? "—"}</b>
                          <span className="n">相似度 {typeof slot.accepted?.product_match === "number" ? slot.accepted.product_match.toFixed(3) : "—"}</span>
                          <span>{slot.accepted ? "已采纳" : "未采纳"}{slot.accepted?.mode && summary.gridMode && slot.accepted.mode !== "grid" ? " · 单帧回退" : ""}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })() : null}

            {publishText ? (
              <>
                <h2 style={{ marginTop: 16 }}>发布文案（可直接复制）</h2>
                <textarea
                  readOnly
                  className="demo-textarea"
                  value={publishText}
                />
                <div className="demo-row" style={{ marginTop: 8 }}>
                  <button className="demo-btn" onClick={() => void navigator.clipboard?.writeText(publishText)}>复制文案</button>
                  {aigcText ? <span className="demo-muted">AI 声明：{aigcText}</span> : null}
                </div>
              </>
            ) : null}
          </div>
        ) : null}

        {voiceInfo || subtitleInfo ? (
          <div className="demo-card">
            <h2>配音与字幕</h2>
            {voiceInfo ? (
              <div className="demo-row">
                <span className={`demo-badge ${voiceInfo.status === "confirmed" ? "ok" : "warn"}`}>
                  配音 {voiceInfo.status === "confirmed" ? "已确认" : "待确认"}
                </span>
                <span className="demo-muted">
                  {voiceInfo.voiceId} · {voiceInfo.seconds ? voiceInfo.seconds.toFixed(2) + "s" : "—"}
                </span>
                {voiceInfo.audioUrl ? <audio controls src={voiceInfo.audioUrl} className="demo-audio" /> : null}
              </div>
            ) : null}
            {subtitleInfo ? (
              <div className="demo-row" style={{ marginTop: 8 }}>
                <span className={`demo-badge ${subtitleInfo.status === "confirmed" ? "ok" : "warn"}`}>
                  字幕 {subtitleInfo.status === "confirmed" ? "已确认" : "待确认"}
                </span>
                <span className="demo-muted">{subtitleInfo.segments} 段</span>
              </div>
            ) : null}
            {voiceInfo?.status !== "confirmed" || subtitleInfo?.status !== "confirmed" ? (
              <div className="demo-row" style={{ marginTop: 12 }}>
                <button className="demo-btn primary" onClick={() => void confirmAudioSubtitleManually()}>
                  确认配音与字幕（不花钱）
                </button>
                <span className="demo-muted">确认后才能建视频方案并出片</span>
              </div>
            ) : null}
          </div>
        ) : null}

        {stopReason ? (
          <div className="demo-card">
            <h2>需要你处理</h2>
            <div className="demo-stop">{stopReason}</div>
            {gate ? (
              <div className="demo-row" style={{ marginTop: 10 }}>
                <button className="demo-btn primary" onClick={() => void acknowledge()}>已知悉，继续</button>
                <span className="demo-muted">交付门的警告必须逐条确认后才允许下载</span>
              </div>
            ) : null}
            {!gate && projectId ? (
              <div className="demo-row" style={{ marginTop: 10 }}>
                <button className="demo-btn primary" disabled={busy} onClick={() => void retryRender()}>
                  继续出片（关键帧未过的镜会重生成一次）
                </button>
                <span className="demo-muted">已采纳的关键帧与已确认的分镜不会重复花钱</span>
              </div>
            ) : null}
            {!gate ? (
              <div className="demo-row" style={{ marginTop: 10 }}>
                {needsConfirm ? (
                  <button className="demo-btn primary" onClick={() => void confirmAudioSubtitleManually()}>
                    确认配音与字幕（不花钱）
                  </button>
                ) : null}
                <button className="demo-btn" onClick={() => void retryContinue()}>重试继续</button>
              </div>
            ) : null}
            <ul className="demo-log" style={{ marginTop: 10 }}>
              {gate?.checks.filter((item) => item.level !== "ok").map((item) => (
                <li key={item.id}>{item.level.toUpperCase()} · {item.label}：{item.message}</li>
              ))}
            </ul>
          </div>
        ) : null}

        {phase !== "input" ? (
          <div className="demo-card">
            <h2>进度</h2>
            <ol className="demo-log demo-progress">
              {PIPELINE_STEPS.map((step, index) => (
                <li key={step.key} className={progressIndex > index ? "done" : index === progressIndex ? "cur" : undefined}>
                  {progressIndex > index ? "✓ " : index === progressIndex ? "… " : "○ "}{step.label}
                </li>
              ))}
            </ol>
          </div>
        ) : null}

        <details className="demo-card" open={busy}>
          <summary><span className="caret">▶</span>事件日志<span className="summary-note">{projectId ? `project_id：${projectId}` : "还没有开始"}</span></summary>
          <div className="demo-card-body">
            <ul className="demo-log" ref={logRef} style={{ maxHeight: 220, overflowY: "auto" }}>
              {log.length === 0 ? <li className="demo-muted">还没有开始。</li> : null}
              {log.map((line, index) => <li key={index} className={line.err ? "err" : undefined}>{line.text}</li>)}
            </ul>
            {projectId ? <p className="demo-muted" style={{ marginTop: 8 }}>用它可以在后端查每一段的输入输出</p> : null}
          </div>
        </details>
      </div>
    </div>
  );
}
