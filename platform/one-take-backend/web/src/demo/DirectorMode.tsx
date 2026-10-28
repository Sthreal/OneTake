/** 导演模式（S4）：**4 步可自由穿行** + 合成页「左时间线 / 右参数卡」。
 *
 * 口径（见 `docs/导演模式与分段可用性总体方案.md` §2/§3）：
 * - 导演模式 = 逐镜生成（分段）；**不提供"切回一次成片"的开关**（那是小白模式专属）；
 * - 4 步每步都能点回 —— 因为每一步的产物都落在服务端，回退不丢东西；
 * - 贵便宜分离：② 素材/逐段出片是**付费**；③ 的整片参数是**免费**（改完只重合成）；
 * - 这里**不自动跑任何修复动作**：修复计划只展示，动作由人点（`repair_plan.py` 的纪律）。
 */
import { useCallback, useEffect, useState } from "react";

import type { ContentPlan, ContentPlanOption, ContentScene } from "../features/content-plan/types";
import type { ComposeOptions, VideoEstimate } from "../features/video/types";
import type {
  GateReport,
  KeyframeState,
  ModelPreflight,
  OutputArtifact,
  RepairPlan,
  RetakeSymptom,
  VideoPlan,
  VideoSegment,
} from "../features/video/types";
import {
  confirmContentPlan,
  generateContentPlan,
  getContentPlan,
  getContentPlanOptions,
  updateSceneCamera,
} from "../shared/api/contentPlanApi";
import { approveCost, startAutoRun } from "./api";
import { ApiError } from "../shared/api/client";
import {
  acceptKeyframe,
  createVideoPlan,
  generateKeyframeCandidates,
  getComposeOptions,
  getGateReport,
  getKeyframes,
  getVideoEstimate,
  getModelPreflight,
  getOutput,
  getVideo,
  getVideoRepairs,
  getVideoSegments,
  retakeSegment,
  setSegmentSeamMode,
  startVideoBatch,
  updateVideoPlanSettings,
} from "../shared/api/videoApi";
import {
  DIRECTOR_STEPS,
  REALISM_LABELS,
  formatElapsed,
  segmentStatusLabel,
  stepProgressHint,
  SEAM_MODE_LABELS,
  purposeBadge,
  qualitySummary,
  repairHeadline,
  stepEnabled,
  type DirectorStepKey,
} from "./director";
import { listProjects } from "../shared/api/projectApi";
import { getPipeline } from "../shared/api/recognitionApi";
import { FileDrop } from "./FileDrop";
import { runProjectIntake } from "./intake";
import { keyframeFloor, pickKeyframeCandidate } from "./policy";
import { patchUrlState, pushUrlState, readUrlState, subscribeUrlState } from "./urlState";
import "./demo.css";
import "./studio.css";

const SYMPTOMS: { value: RetakeSymptom; label: string }[] = [
  { value: "product_warped", label: "商品变形" },
  { value: "text_blurry", label: "文字模糊" },
  { value: "background_dead", label: "背景死板" },
  { value: "light_wrong", label: "光线不对" },
  { value: "blurry", label: "画面模糊" },
  { value: "object_drift", label: "物体漂移" },
];


export function DirectorMode({ projectId }: { projectId: string | null }) {
  // 项目可以**外部带进来**（从项目列表进导演模式），也可以**在这一步自己造出来**
  // （上传商品图 / 贴商品链接）—— 导演模式与小白是**并存的两个入口**，不是它的下游分支。
  const [activeProjectId, setActiveProjectId] = useState<string | null>(projectId);
  useEffect(() => setActiveProjectId(projectId), [projectId]);
  const [intakeMode, setIntakeMode] = useState<"file" | "url">("file");
  const [intakeFile, setIntakeFile] = useState<File | null>(null);
  const [intakeUrl, setIntakeUrl] = useState("");
  const [intakeName, setIntakeName] = useState("");
  const [intakeNote, setIntakeNote] = useState("");
  const [intakeBusy, setIntakeBusy] = useState(false);
  const [knownProjects, setKnownProjects] = useState<{ project_id: string; product_name: string }[]>([]);
  // ① URL 化（方案 §3.1）：步骤从地址栏恢复，切步骤时写回地址栏 —— 可分享、可刷新、可后退
  const [step, setStep] = useState<DirectorStepKey>(() => (readUrlState().projectId ? readUrlState().step : "intake"));
  const [cameraOptions, setCameraOptions] = useState<ContentPlanOption[]>([]);
  const [cameraDraft, setCameraDraft] = useState<Record<string, string>>({});
  const [plan, setPlan] = useState<VideoPlan | null>(null);
  const [estimate, setEstimate] = useState<VideoEstimate | null>(null);
  // 闸②：**真正的闸在服务端**（未批准 → 409 COST_APPROVAL_REQUIRED）。
  // 这里刻意**乐观初值 false**：批准记录只有一个不带读接口的后端事实，前端猜不了；
  // 猜成"未批准"会让刚批准过的人一刷新就面对一排灰按钮（2026-10-16 实测的摩擦），
  // 所以：先让点，撞到 409 再置 true 并给出明确指路。
  const [needsApproval, setNeedsApproval] = useState(false);
  const [contentPlan, setContentPlan] = useState<ContentPlan | null>(null);
  /** 自动链（前 4 段）的真实状态：**导演模式必须自己看得见**，否则链停在文案失败时，
   *  用户只会在闸②按钮上撞一句"请先确认配音和字幕"（2026-10-17 实测）。 */
  const [pipelineStatus, setPipelineStatus] = useState<string | null>(null);
  const [pipelineStage, setPipelineStage] = useState<string | null>(null);
  const [segments, setSegments] = useState<VideoSegment[]>([]);
  const [keyframes, setKeyframes] = useState<KeyframeState | null>(null);
  const [output, setOutput] = useState<OutputArtifact | null>(null);
  const [gate, setGate] = useState<GateReport | null>(null);
  const [repairs, setRepairs] = useState<RepairPlan | null>(null);
  const [preflight, setPreflight] = useState<ModelPreflight | null>(null);
  const [composeOptions, setComposeOptions] = useState<ComposeOptions | null>(null);
  const [symptom, setSymptom] = useState<RetakeSymptom>("text_blurry");
  const [busy, setBusy] = useState(false);
  // 「正在做什么」必须可见：真实生成一段要 30~90 秒，只说"按钮变灰"用户会以为坏了（2026-10-16）
  const [pending, setPending] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async (overrideId?: string) => {
    const pid = overrideId ?? activeProjectId;
    if (!pid) {
      // 导演模式的输入步：还没有项目 → 不发请求、也不报错
      return;
    }
    setError(null);
    try {
      const video = await getVideo(pid);
      setPlan(video.plan);
      const pipeline = await getPipeline(pid).catch(() => null);
      setPipelineStatus(pipeline?.status ?? null);
      setPipelineStage((pipeline as { current_step?: number; stage?: string } | null)?.stage ?? null);
      const [content, seg, out, gateReport] = await Promise.all([
        getContentPlan(pid).catch(() => null),
        getVideoSegments(pid).catch(() => ({ plan_id: null, segments: [] })),
        getOutput(pid).catch(() => null),
        getGateReport(pid).catch(() => null),
      ]);
      setContentPlan(content);
      // 导演模式的闸②：没有视频方案就先建一个（**免费**），并取回预估 —— 费用卡才有数可显示
      let activePlan = video.plan;
      if (!activePlan && content?.status === "confirmed") {
        const created = await createVideoPlan(pid, "product", "clean", "segmented").catch(() => null);
        activePlan = created?.plan ?? null;
        if (activePlan) setPlan(activePlan);
      }
      if (activePlan) setEstimate(await getVideoEstimate(pid, activePlan.plan_id).catch(() => null));
      setSegments(seg.segments);
      setOutput(out);
      setGate(gateReport);
      // 下面两个是 S6 的只读端点：拿不到就不显示，不编内容
      setRepairs(await getVideoRepairs(pid).catch(() => null));
      // ② 逐镜运镜：选项表来自后端的唯一真源（`/content-plan/options`），前端不自己写一份
      setCameraOptions((await getContentPlanOptions(pid).catch(() => ({ camera_moves: [] }))).camera_moves);
      setComposeOptions(await getComposeOptions(pid).catch(() => null));
      setPreflight(
        await getModelPreflight(pid, {
          path: video.plan?.path,
          seamMode: video.plan?.seam_mode,
        }).catch(() => null),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "读取项目失败");
    }
  }, [activeProjectId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (step !== "assets" || !activeProjectId) return;
    let cancelled = false;
    getKeyframes(activeProjectId)
      .then((state) => {
        if (!cancelled) setKeyframes(state);
      })
      .catch(() => {
        /* 关键帧拿不到不影响其它步骤 */
      });
    return () => {
      cancelled = true;
    };
  }, [activeProjectId, step]);

  /** 导演模式**自己的输入**：商品图 / 商品链接 → 建项目 → 自动链跑前 4 段 → 交给人。 */
  const submitIntake = async () => {
    setError(null);
    setNote(null);
    setIntakeBusy(true);
    try {
      const id = await runProjectIntake(
        { mode: intakeMode, file: intakeFile, productUrl: intakeUrl, name: intakeName, note: intakeNote },
        { log: (text, err) => (err ? setError(text) : setNote(text)) },
      );
      setActiveProjectId(id);
      pushUrlState({ view: "director", projectId: id, step: "storyboard" });
      setStep("storyboard");
      // 自动链只跑到闸①前：内容方案（规则生成、免费）在这里补出来，导演模式才能"看分镜"
      await generateContentPlan(id).catch(() => null);
      await refresh(id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "输入失败");
    } finally {
      setIntakeBusy(false);
    }
  };

  /** 也可以从已有项目进（同一个模式，另一种进入方式）。 */
  const openExisting = async (id: string) => {
    setActiveProjectId(id);
    pushUrlState({ view: "director", projectId: id, step: "storyboard" });
    setStep("storyboard");
    await refresh(id);
  };

  useEffect(() => {
    if (activeProjectId) return;
    void listProjects(6).then(setKnownProjects).catch(() => setKnownProjects([]));
  }, [activeProjectId]);

  /** 切步骤 = 改地址栏（可后退、可分享）。同一步不重复 push，避免历史里堆一堆相同项。 */
  const goStep = (next: DirectorStepKey) => {
    setStep(next);
    const current = readUrlState();
    if (current.step !== next) pushUrlState(patchUrlState(current, { step: next }));
  };

  useEffect(() => subscribeUrlState((next) => setStep(next.step)), []);

  /** ② 逐镜运镜：保存到分镜（方案已确认也允许），**对下一次生成该镜生效**。 */
  const saveCamera = async (sceneId: string, cameraMove: string) => {
    const value = cameraMove.trim();
    if (!value) {
      setError("运镜描述不能为空");
      return;
    }
    await run("运镜已保存（下一次生成该镜时生效）", (pid) => updateSceneCamera(pid, sceneId, value));
  };

  /** 步骤级动作**都要求已经有项目**（输入步之后）。没有就拦下并指路，绝不把空 id 传下去。 */
  const run = async (label: string, action: (pid: string) => Promise<unknown>, pendingText?: string) => {
    if (!activeProjectId) {
      setError("这一步需要先有项目：回到「输入」步给素材（商品图或链接）");
      return;
    }
    const pid = activeProjectId;
    setBusy(true);
    setPending(pendingText ?? label);
    setError(null);
    try {
      await action(pid);
      setNote(label);
      await refresh(pid);
      if (step === "assets") setKeyframes(await getKeyframes(pid).catch(() => keyframes));
    } catch (err) {
      if (err instanceof ApiError && err.code === "COST_APPROVAL_REQUIRED") {
        setNeedsApproval(true);
        setError("这笔钱还没批准：回「分镜」步点「确认分镜并批准这笔费用」");
      } else {
        setError(err instanceof Error ? err.message : "操作失败");
      }
    } finally {
      setBusy(false);
      setPending(null);
      setElapsed(0);
    }
  };

  /** 闸①+闸②：确认分镜 → 建方案（若无）→ 取预估 → **批准费用** → 放行后续付费步骤。 */
  const approveAndContinue = async () => {
    if (!activeProjectId) {
      setError("先给素材（商品图或链接）");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const pid = activeProjectId;
      await confirmContentPlan(pid);
      let current = plan;
      if (!current) {
        const created = await createVideoPlan(pid, "product", "clean", "segmented");
        current = created.plan;
        setPlan(current);
      }
      if (!current) throw new Error("视频方案创建失败");
      const nextEstimate = await getVideoEstimate(pid, current.plan_id);
      setEstimate(nextEstimate);
      await approveCost(pid, current.plan_id);
      setNeedsApproval(false);
      setNote("费用已批准（一次批准覆盖全部付费步骤）");
      await refresh(pid);
      goStep("assets");
    } catch (err) {
      setError(err instanceof Error ? err.message : "批准失败");
    } finally {
      setBusy(false);
    }
  };

  const scenes: ContentScene[] = contentPlan?.variants?.[contentPlan.selected_variant_index]?.scenes ?? [];
  const sceneById = new Map(scenes.map((scene) => [scene.scene_id, scene]));
  const facts = { hasPlan: Boolean(plan), hasSegments: segments.length > 0, hasFinal: Boolean(output) };
  const stepIndex = DIRECTOR_STEPS.findIndex((item) => item.key === step);
  const prevStep = stepIndex > 0 ? DIRECTOR_STEPS[stepIndex - 1] : null;
  const nextStep = stepIndex >= 0 && stepIndex < DIRECTOR_STEPS.length - 1 ? DIRECTOR_STEPS[stepIndex + 1] : null;
  /** 等待中的秒表：只要在跑就每秒 +1（让"在动"看得见）。 */
  useEffect(() => {
    if (!pending) return;
    const timer = setInterval(() => setElapsed((value) => value + 1), 1000);
    return () => clearInterval(timer);
  }, [pending]);

  /** 等待真实调用返回时，每 3 秒把"分段/关键帧的真实状态"拉回来（后端会把在生成的那段写成 generating）。 */
  useEffect(() => {
    if (!pending || !activeProjectId) return;
    const pid = activeProjectId;
    let cancelled = false;
    const timer = setInterval(() => {
      void (async () => {
        const [seg, kf] = await Promise.all([
          getVideoSegments(pid).catch(() => null),
          getKeyframes(pid).catch(() => null),
        ]);
        if (cancelled) return;
        if (seg) setSegments(seg.segments);
        if (kf) setKeyframes(kf);
      })();
    }, 3000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [pending, activeProjectId]);

  const pendingSegment = segments.find((item) => !item.accepted_candidate_id) ?? null;
  const keyframeSlots = keyframes?.keyframes ?? [];
  const keyframeAcceptedCount = keyframeSlots.filter((slot) => slot.accepted).length;
  const progressHint = stepProgressHint({
    step,
    hasProject: Boolean(activeProjectId),
    contentPlanStatus: contentPlan?.status ?? null,
    keyframeTotal: keyframeSlots.length,
    keyframeAccepted: keyframeAcceptedCount,
    segmentTotal: segments.length,
    segmentAccepted: segments.filter((item) => item.accepted_candidate_id).length,
    hasOutput: Boolean(output?.download_url),
  });

  return (
    <div className="studio-page dir-page">
      <h1>导演模式</h1>
      <p className="studio-note" style={{ padding: 0 }}>
        逐镜生成：每一镜单独出片、可单镜重拍；每步都能点回去改，产物都落在服务端。
      </p>

      <div className="dir-steps">
        {DIRECTOR_STEPS.map((item, index) => (
          <button
            key={item.key}
            className={"dir-step" + (item.key === step ? " on" : "")}
            disabled={!stepEnabled(item.key, facts)}
            title={stepEnabled(item.key, facts) ? item.hint : "前置还没就绪"}
            onClick={() => goStep(item.key)}
          >
            <span className="dir-step-no">{index + 1}</span>
            {item.label}
          </button>
        ))}
      </div>

      {note ? <p className="studio-hint">✓ {note}</p> : null}
      {error ? <p className="studio-error">{error}</p> : null}

      {pending ? (
        <div className="dir-busy" role="status">
          <span className="dir-spin" aria-hidden="true" />
          <b>{pending}</b>
          <span className="demo-muted">
            已等待 {formatElapsed(elapsed)}｜真实调用**不会立刻返回**（出片一段实测约 70 秒），请别关页面；
            完成后这一步会自动刷新。
          </span>
        </div>
      ) : null}

      {step === "intake" ? (
        <div className="demo-card" style={{ marginTop: 14 }}>
          <h2>给素材就能开始</h2>
          <p className="demo-muted">
            商品图或商品链接都行；从这里往后**每一步都能人为干预**（分镜 → 素材 → 合成 → 交付）。
          </p>
          <div className="demo-row">
            <button
              className={"demo-btn" + (intakeMode === "file" ? " primary" : "")}
              disabled={intakeBusy}
              onClick={() => setIntakeMode("file")}
            >
              上传商品图
            </button>
            <button
              className={"demo-btn" + (intakeMode === "url" ? " primary" : "")}
              disabled={intakeBusy}
              onClick={() => setIntakeMode("url")}
            >
              贴商品链接
            </button>
          </div>
          {intakeMode === "file" ? (
            <FileDrop file={intakeFile} onPick={setIntakeFile} disabled={intakeBusy} />
          ) : (
            <div className="demo-row">
              <input
                type="text"
                placeholder="贴商品链接（淘宝/京东/拼多多/独立站…）"
                value={intakeUrl}
                disabled={intakeBusy}
                onChange={(event) => setIntakeUrl(event.target.value)}
              />
            </div>
          )}
          <div className="demo-row">
            <input
              type="text"
              placeholder="商品名（可留空）"
              value={intakeName}
              disabled={intakeBusy}
              onChange={(event) => setIntakeName(event.target.value)}
            />
            <input
              type="text"
              placeholder="卖点 / 补充说明（可留空）"
              value={intakeNote}
              disabled={intakeBusy}
              onChange={(event) => setIntakeNote(event.target.value)}
            />
          </div>
          <div className="demo-row">
            <button
              className="demo-btn primary"
              disabled={intakeBusy || (intakeMode === "file" ? !intakeFile : !intakeUrl.trim())}
              onClick={() => void submitIntake()}
            >
              {intakeBusy ? "正在跑前 4 段（分钟级，请不要关页面）…" : "开始（到分镜）"}
            </button>
          </div>
          <p className="demo-muted">识别 → 主图 → 文案 → 配音字幕 由后端自动链跑完；到「分镜」那一步就交给你。</p>
          {knownProjects.length > 0 ? (
            <>
              <p className="demo-muted" style={{ marginTop: 10 }}>或从已有项目继续：</p>
              <div className="demo-row">
                {knownProjects.map((project) => (
                  <button
                    key={project.project_id}
                    className="demo-btn"
                    disabled={intakeBusy}
                    onClick={() => void openExisting(project.project_id)}
                  >
                    {project.product_name}
                  </button>
                ))}
              </div>
            </>
          ) : null}
        </div>
      ) : null}

      {step === "storyboard" ? (
        <div className="demo-card" style={{ marginTop: 14 }}>
          <h2>这一版分镜</h2>
          {/* 前 4 段没跑完时必须**先说清卡在哪、并给出重试入口** —— 否则用户只会撞闸②的 409 提示 */}
          {pipelineStatus && !["audio_subtitle_confirmed", "content_plan_ready", "content_plan_confirmed", "content_qa_passed"].includes(pipelineStatus) ? (
            <div className="dir-busy" style={{ borderColor: "rgba(248,113,113,.35)", background: "rgba(248,113,113,.08)" }}>
              <b style={{ color: "#fca5a5" }}>前 4 段没跑完：当前状态「{pipelineStatus}」</b>
              <span className="demo-muted">
                {pipelineStage ? `停在「${pipelineStage}」这一步。` : ""}
                点右边按钮重跑一次（已成功的步骤不会重复付费；文案不合格时会重新生成）。
              </span>
              <button
                className="demo-btn primary"
                disabled={busy}
                onClick={() =>
                  void run("自动链已重试（跑到没问题的状态就会继续）", (pid) => startAutoRun(pid))
                }
              >
                重试自动链（前 4 段）
              </button>
            </div>
          ) : null}
          <div className="dir-card" style={{ marginTop: 10 }}>
            <b>方案与费用（闸②：批准后才开始花钱）</b>
            {estimate ? (
              <>
                <p className="demo-muted">
                  预估费用：<b>¥{estimate.estimated_known_cost}</b>
                  {estimate.estimated_cost_max && estimate.estimated_cost_max !== estimate.estimated_known_cost
                    ? `（最坏 ¥${estimate.estimated_cost_max}）`
                    : ""}
                  　·　时长约 {estimate.duration_seconds}s
                </p>
                {estimate.missing_price_config.length > 0 ? (
                  <p className="demo-muted" style={{ color: "#fcd34d" }}>
                    ⚠ 有单价未配置：{estimate.missing_price_config.join("、")}
                  </p>
                ) : null}
                <ul className="demo-log">
                  {estimate.price_notes.map((note) => (
                    <li key={note}>{note}</li>
                  ))}
                </ul>
                <div className="demo-row">
                  <button className="demo-btn primary" disabled={busy} onClick={() => void approveAndContinue()}>
                    确认分镜并批准这笔费用（重复点不会重复扣费）→ 进入素材
                  </button>
                  <span className="demo-muted">一次批准覆盖全部付费步骤；改方案/路径会失效、需重新批准</span>
                </div>
              </>
            ) : (
              <>
                {/* 死路过一次（用户实测 2026-10-16「到分镜卡住、没有往下的按钮」）：
                    新项目的分镜是 ready（还没确认）→ 方案还没建 → 预估为空，而按钮原来只在"有预估"那支里
                    → 整页没有任何可以点的东西。按钮必须**任何状态**都在。 */}
                <p className="demo-muted">
                  {scenes.length === 0
                    ? "还没有分镜方案。"
                    : "还没有费用预估：点下面按钮会先确认分镜（闸①），再自动建方案、取预估并登记这笔批准（闸②）。"}
                </p>
                {scenes.length > 0 ? (
                  <div className="demo-row">
                    <button className="demo-btn primary" disabled={busy} onClick={() => void approveAndContinue()}>
                      确认分镜并批准这笔费用（重复点不会重复扣费）→ 进入素材
                    </button>
                    <span className="demo-muted">一次批准覆盖全部付费步骤；改方案/路径会失效、需重新批准</span>
                  </div>
                ) : null}
              </>
            )}
          </div>

          {scenes.length === 0 ? (
            <p className="demo-muted">还没有分镜。回「出片」主路生成一版，或在这里继续之前那版。</p>
          ) : (
            <div className="demo-scenes">
              {scenes.map((scene) => (
                <div className="demo-scene" key={scene.scene_id}>
                  <span className="ord">{scene.order}</span>
                  <div>
                    <div className="sp-text">{scene.script_excerpt || "（本镜无口播）"}</div>
                    <div className="meta">
                      {scene.start_seconds}s – {scene.end_seconds}s · {scene.camera_move} · 商品
                      {scene.product_mode === "absent" ? "不出现" : "入画"}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : null}

      {step === "assets" ? (
        <div className="demo-card" style={{ marginTop: 14 }}>
          <h2>每一镜的关键帧</h2>
          <p className="demo-muted">{`进度：${keyframeAcceptedCount}/${keyframeSlots.length} 镜已采纳`}</p>
          <p className="demo-muted">
            关键帧是逐镜生成的**首帧**：它决定商品长什么样、光从哪来。逐镜重拍只换这一镜。
          </p>
          {/* 闸② 是硬约束：不让按钮"点了没反应"，直接把该去哪一步说清楚 */}
          {needsApproval ? (
            <p className="dir-warn">费用还没批准：回「分镜」步点一次「确认分镜并批准这笔费用」，这里就能开跑。</p>
          ) : null}
          {(keyframes?.keyframes ?? []).length === 0 ? (
            <p className="demo-muted">还没有关键帧。</p>
          ) : (
            <div className="dir-assets">
              {keyframes?.keyframes.map((slot) => (
                <div className="dir-asset" key={slot.scene_id}>
                  {slot.accepted?.image_url ? (
                    <img className="dir-thumb" src={slot.accepted.image_url} alt="" />
                  ) : (
                    <div className="dir-thumb empty">未生成</div>
                  )}
                  <div className="dir-asset-body">
                    <b>第 {slot.order} 镜</b>
                    <span className={`dir-badge tone-${purposeBadge(slot.purpose).tone}`}>
                      {purposeBadge(slot.purpose).label}
                    </span>
                    {slot.accepted ? (
                      <span className="demo-muted">
                        相似度 {slot.accepted.product_match?.toFixed(3) ?? "未测"} ·{" "}
                        {slot.accepted.text_intact === false ? "文字可能受损" : "文字完好"}
                      </span>
                    ) : (
                      <span className="demo-muted">尚未采纳</span>
                    )}
                    {slot.prompt_warning ? <p className="dir-warn">{slot.prompt_warning}</p> : null}
                    <div className="demo-row">
                      <button
                        className="demo-btn"
                        disabled={busy || needsApproval || keyframes?.generation_available === false}
                        onClick={() =>
                          void run(`第 ${slot.order} 镜在生成候选…`, (pid) =>
                            generateKeyframeCandidates(pid, slot.scene_id, { n: 2 }),
                          )
                        }
                      >
                        生成候选
                      </button>
                      <button
                        className="demo-btn primary"
                        disabled={busy || !keyframes}
                        onClick={() =>
                          void run(`第 ${slot.order} 镜已采用`, async (pid) => {
                            const decision = pickKeyframeCandidate(slot, keyframes?.mode ?? "integrated");
                            if (!decision.auto) throw new Error(`第 ${slot.order} 镜：${decision.reason}`);
                            await acceptKeyframe(pid, slot.scene_id, decision.value.keyframe_id);
                          })
                        }
                      >
                        采用过线候选
                      </button>
                    </div>
                    {/* 人要不要越过质量门槛，是人的决定：自动挑不过线时**不静默**，也不堵死 —— 
                        逐张给出相似度与门槛，人可以显式采用某一张（后端 accept 本来就只校验 ready）。 */}
                    {(slot.candidates ?? []).length > 0 ? (
                      <div className="dir-cands">
                        {slot.candidates.map((candidate) => {
                          const floor = keyframeFloor(keyframes?.mode ?? "integrated");
                          const scored = candidate.product_match;
                          const belowFloor =
                            candidate.status === "ready" &&
                            (candidate.text_intact === false || (scored ?? 0) < floor);
                          return (
                            <div className="dir-cand" key={candidate.keyframe_id}>
                              {candidate.image_url ? (
                                <img className="dir-thumb sm" src={candidate.image_url} alt="" />
                              ) : (
                                <div className="dir-thumb sm empty">无图</div>
                              )}
                              <span className="demo-muted">
                                相似度 {scored === null || scored === undefined ? "未测" : scored.toFixed(3)}
                                {belowFloor ? `（低于门槛 ${floor}）` : ""}
                              </span>
                              <button
                                className="demo-btn"
                                disabled={busy || candidate.status !== "ready"}
                                onClick={() =>
                                  void run(`第 ${slot.order} 镜已采用你挑的那张`, (pid) =>
                                    acceptKeyframe(pid, slot.scene_id, candidate.keyframe_id),
                                  )
                                }
                              >
                                {candidate.status === "ready" ? "采用这张" : candidate.status}
                              </button>
                            </div>
                          );
                        })}
                      </div>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : null}

      {step === "compose" ? (
        <div className="dir-grid">
          <div className="dir-timeline">
            <div className="dir-head">
              <b>时间线</b>
              <span className="demo-muted">
                {segments.length} 段 · 共 {segments.reduce((sum, item) => sum + item.duration_seconds, 0).toFixed(1)}s
              </span>
              <button
                className="demo-btn primary"
                disabled={busy || needsApproval}
                onClick={() =>
                  void run("已生成一段（保持运行中，可继续）", (pid) => startVideoBatch(pid, 1),
                    `正在生成第 ${pendingSegment?.order_index ?? "下一"} 段（真实调用，约 30~90 秒）`)
                }
              >
                {pending && pendingSegment ? `正在生成第 ${pendingSegment.order_index} 段…` : "逐段推进一段"}
              </button>
              {needsApproval ? (
                <span className="demo-muted">费用还没批准：回「分镜」步批准后才能开跑</span>
              ) : null}
            </div>
            {segments.length === 0 ? (
              <p className="demo-muted">还没有分段。先确认分镜与关键帧，再点「逐段推进一段」。</p>
            ) : (
              segments
                .slice()
                .sort((a, b) => a.order_index - b.order_index)
                .map((segment) => {
                  const scene = sceneById.get(segment.scene_id);
                  const badge = purposeBadge(scene?.purpose);
                  const accepted = segment.candidates.find((item) => item.candidate_id === segment.accepted_candidate_id);
                  // 正在生成的那一段：后端会把 status 写成 generating，但请求还没返回时本页也要**立刻**
                  // 显示"生成中"（用户实测：看不到状态就以为坏了）
                  const displayStatus =
                    pending && pendingSegment?.segment_id === segment.segment_id ? "generating" : segment.status;
                  return (
                    <div className="dir-seg" key={segment.segment_id}>
                      {segment.thumbnail_url ? (
                        <img className="dir-thumb" src={segment.thumbnail_url} alt="" />
                      ) : (
                        <div className="dir-thumb empty">待生成</div>
                      )}
                      <div className="dir-seg-body">
                        <div className="dir-seg-head">
                          <span className={`dir-badge tone-${badge.tone}`}>{badge.label}</span>
                          <span className="demo-muted">
                            {segment.duration_seconds}s · 第 {segment.order_index} 段
                          </span>
                          <span className={`dir-state state-${displayStatus}`}>
                            {segmentStatusLabel(displayStatus)}
                          </span>
                        </div>
                        <div className="sp-text">{scene?.script_excerpt || "（本镜无口播）"}</div>
                        <div className="demo-muted">{qualitySummary(segment.quality).join(" · ")}</div>
                        <div className="dir-camera">
                          <span className="demo-muted">接缝</span>
                          <select
                            className="dir-select"
                            value={segment.seam_mode ?? "__inherit"}
                            disabled={busy}
                            onChange={(event) => {
                              const value = event.target.value;
                              void run(
                                value === "__inherit" ? "本段接缝已改回继承整片" : "本段接缝已更新（费用预估随之变化，需重新批准）",
                                (pid) =>
                                  setSegmentSeamMode(
                                    pid, segment.segment_id,
                                    value === "__inherit" ? null : (value as "pin" | "tail" | "off"),
                                  ),
                              );
                            }}
                          >
                            <option value="__inherit">
                              继承整片（{SEAM_MODE_LABELS[plan?.seam_mode ?? "pin"]}）
                            </option>
                            <option value="pin">钉帧（钉到下一镜关键帧）</option>
                            <option value="tail">续拍（从上一段真实尾帧继续）</option>
                            <option value="off">关（这一镜独立生成）</option>
                          </select>
                          <span className="demo-muted">{segment.seam_mode ? "本段单独设置" : "跟整片"}</span>
                        </div>
                        {scene ? (
                          <div className="dir-camera">
                            <span className="demo-muted">运镜</span>
                            <select
                              className="dir-select"
                              value={cameraOptions.some((item) => item.id === scene.camera_move) ? scene.camera_move : "__custom"}
                              disabled={busy}
                              onChange={(event) => {
                                const value = event.target.value;
                                if (value === "__custom") return;
                                void saveCamera(scene.scene_id, value);
                              }}
                            >
                              {!cameraOptions.some((item) => item.id === scene.camera_move) ? (
                                <option value="__custom">{scene.camera_move || "（未设置）"}</option>
                              ) : null}
                              {cameraOptions.map((item) => (
                                <option key={item.id} value={item.id}>
                                  {item.label}
                                </option>
                              ))}
                            </select>
                            <input
                              className="dir-select"
                              placeholder="或写一句自定义运镜（≤200 字）"
                              value={cameraDraft[segment.segment_id] ?? ""}
                              disabled={busy}
                              onChange={(event) =>
                                setCameraDraft((prev) => ({ ...prev, [segment.segment_id]: event.target.value }))
                              }
                            />
                            <button
                              className="demo-btn"
                              disabled={busy || !(cameraDraft[segment.segment_id] ?? "").trim()}
                              onClick={() => void saveCamera(scene.scene_id, cameraDraft[segment.segment_id] ?? "")}
                            >
                              保存运镜
                            </button>
                            <span className="demo-muted">对**下一次**生成该镜生效</span>
                          </div>
                        ) : null}
                        <div className="demo-row">
                          <select
                            className="dir-select"
                            value={symptom}
                            onChange={(event) => setSymptom(event.target.value as RetakeSymptom)}
                          >
                            {SYMPTOMS.map((item) => (
                              <option key={item.value} value={item.value}>
                                {item.label}
                              </option>
                            ))}
                          </select>
                          <button
                            className="demo-btn"
                            disabled={busy || needsApproval}
                            onClick={() =>
                              void run(`第 ${segment.order_index} 段已按症状重跑`, (pid) =>
                                retakeSegment(pid, segment.segment_id, symptom),
                              )
                            }
                          >
                            重跑这一段（只改这一处）
                          </button>
                          {segment.preview_url ? (
                            <a className="demo-btn" href={segment.preview_url} target="_blank" rel="noreferrer">
                              看这一段
                            </a>
                          ) : null}
                        </div>
                        {accepted?.symptom ? (
                          <p className="demo-muted">当前这条是「{accepted.symptom}」症状返修的产物</p>
                        ) : null}
                      </div>
                    </div>
                  );
                })
            )}
          </div>

          <div className="dir-panel">
            <div className="dir-card">
              <b>整片参数（改完只重合成，不花钱）</b>
              <label className="dir-field">
                真实感
                <select
                  className="dir-select"
                  value={plan?.motion_realism ?? "off"}
                  disabled={busy || !plan}
                  onChange={(event) =>
                    void run("真实感档已更新", (pid) =>
                      updateVideoPlanSettings(pid, {
                        motion_realism: event.target.value as "auto" | "constraints" | "off",
                      }),
                    )
                  }
                >
                  {Object.entries(REALISM_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="dir-field">
                接缝
                <select
                  className="dir-select"
                  value={plan?.seam_mode ?? "pin"}
                  disabled={busy || !plan}
                  onChange={(event) =>
                    void run("接缝模式已更新（费用预估随之变化，需重新批准）", (pid) =>
                      updateVideoPlanSettings(pid, { seam_mode: event.target.value as "pin" | "tail" | "off" }),
                    )
                  }
                >
                  {Object.entries(SEAM_MODE_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <p className="demo-muted">
                配音 {plan?.voice_enabled ? "开" : "关"} · 字幕 {plan?.subtitle_enabled ? "开" : "关"} · 合成{" "}
                {plan?.provider ?? "—"}（这几项由流水线配置决定，本页只读）
              </p>
            </div>

            <div className="dir-card">
              <b>字幕与配乐（改完只重合成，不花钱）</b>
              <label className="dir-field">
                字幕样式
                <select
                  className="dir-select"
                  value={plan?.caption_style ?? ""}
                  disabled={busy || !plan}
                  onChange={(event) =>
                    void run("字幕样式已更新（重合成后生效）", (pid) =>
                      updateVideoPlanSettings(pid, { caption_style: event.target.value || null }),
                    )
                  }
                >
                  <option value="">
                    跟全局（{composeOptions?.caption_styles.find((item) => item.id === composeOptions.default_caption_style)?.label ?? "标准"}）
                  </option>
                  {(composeOptions?.caption_styles ?? []).map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="dir-field">
                配乐
                <select
                  className="dir-select"
                  value={plan?.bgm_enabled === null || plan?.bgm_enabled === undefined ? "" : plan.bgm_enabled ? "on" : "off"}
                  disabled={busy || !plan}
                  onChange={(event) =>
                    void run("配乐设置已更新（重合成后生效）", (pid) =>
                      updateVideoPlanSettings(pid, {
                        bgm_enabled: event.target.value === "" ? null : event.target.value === "on",
                      }),
                    )
                  }
                >
                  <option value="">
                    跟全局（{composeOptions?.bgm.default_enabled ? "开" : "关"}）
                  </option>
                  <option value="on">开</option>
                  <option value="off">关</option>
                </select>
              </label>
              <label className="dir-field">
                配乐强度（{plan?.bgm_gain_db ?? composeOptions?.bgm.default_gain_db ?? -20} dB）
                <input
                  type="range"
                  min={composeOptions?.bgm.gain_db_min ?? -40}
                  max={composeOptions?.bgm.gain_db_max ?? 0}
                  step={1}
                  value={plan?.bgm_gain_db ?? composeOptions?.bgm.default_gain_db ?? -20}
                  disabled={busy || !plan}
                  onChange={(event) => {
                    const value = Number(event.target.value);
                    void run("配乐强度已更新（重合成后生效）", (pid) =>
                      updateVideoPlanSettings(pid, { bgm_gain_db: value }),
                    );
                  }}
                />
              </label>
            </div>

            <div className="dir-card">
              <b>这次会走哪个模型</b>
              {preflight ? (
                <>
                  <p className="demo-muted">
                    {preflight.capabilities.label}（{preflight.model_kind}）
                  </p>
                  <ul className="demo-log">
                    {preflight.checks.map((item) => (
                      <li key={item.code}>
                        {item.level === "warn" ? "⚠ " : "· "}
                        {item.message}
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                <p className="demo-muted">暂不可用</p>
              )}
            </div>

            <div className="dir-card">
              <b>需要处理的问题</b>
              <p className="demo-muted">{repairHeadline(repairs)}</p>
              {repairs && repairs.actions.length > 0 ? (
                <ul className="demo-log">
                  {repairs.actions.map((item) => (
                    <li key={`${item.check_id}-${item.target_ref ?? ""}`}>
                      [{item.level}] {item.label}：{item.reason}
                      {item.action === "human_ack" ? "（需人工确认）" : `（可执行：${item.action}）`}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

      {step === "delivery" ? (
        <div className="demo-card" style={{ marginTop: 14 }}>
          <h2>成片与交付门</h2>
          {output?.download_url ? (
            <>
              <video className="dir-player" src={output.download_url} controls />
              <div className="demo-row">
                <a className="demo-btn primary" href={output.download_url} target="_blank" rel="noreferrer">
                  下载成片
                </a>
                <span className="demo-muted">
                  {output.video_width}×{output.video_height} · {output.fps}fps · {output.video_codec}
                </span>
              </div>
            </>
          ) : (
            <p className="demo-muted">还没有成片。合成走完后回到这一步。</p>
          )}
          {gate ? (
            <>
              <p className="demo-muted" style={{ marginTop: 10 }}>
                交付门：{gate.status}（{gate.checks.length} 项检查）
              </p>
              <ul className="demo-log">
                {gate.checks.map((check) => (
                  <li key={check.id}>
                    [{check.level}] {check.label}：{check.message}
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </div>
      ) : null}

      {/* 每一步底部的导航与"做完没有"（用户连着三次卡在"没有往下的按钮"，2026-10-16）*/}
      {stepIndex >= 0 ? (
        <div className="dir-nav">
          <button
            className="demo-btn"
            disabled={!prevStep}
            onClick={() => prevStep && goStep(prevStep.key)}
          >
            ← 上一步{prevStep ? `（${prevStep.label}）` : ""}
          </button>
          <span className="demo-muted">{progressHint}</span>
          {nextStep ? (
            <button
              className="demo-btn primary"
              disabled={!stepEnabled(nextStep.key, facts)}
              title={stepEnabled(nextStep.key, facts) ? nextStep.hint : "前置还没就绪"}
              onClick={() => goStep(nextStep.key)}
            >
              下一步（{nextStep.label}）→
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
