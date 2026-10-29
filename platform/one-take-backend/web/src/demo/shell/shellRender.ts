/** 壳层生成步提交渲染：复用托管工作台同一套入口，不另起一条出片栈。
 *
 * 工作台 `DemoApp.produce` 在费用批准之后：
 * - `one_shot` → `requestVideo`（`POST /video`，与 `POST /compose` 同一服务方法）
 * - `segmented` → `startVideoBatch`（`POST /video/batch`）
 *
 * 两条都会先过审稿闸和费用闸（服务端 `_require_paid_entry`）。自动链 `auto_run`
 * 停在人工闸前，不会替我们入队付费渲染，所以这里不调用它。
 * 不走关键帧 UI，也不调用关键帧接口。
 */
import type { VideoPlan, VideoState } from "../../features/video/types";
import { approveCost } from "../api";
import {
  createVideoPlan,
  getOutput,
  getVideo,
  getVideoEstimate,
  requestVideo,
  startVideoBatch,
} from "../../shared/api/videoApi";

const defaultClient = {
  getVideo,
  createVideoPlan,
  getVideoEstimate,
  approveCost,
  requestVideo,
  startVideoBatch,
  getOutput,
};

export type ShellRenderClient = typeof defaultClient;

export type ShellRenderPhase = "idle" | "queued" | "playable" | "failed";

export interface ShellRenderView {
  phase: ShellRenderPhase;
  /** 三态文案：排队中 / 可播预览 / 失败可重试。空闲时是尚未提交。 */
  headline: "排队中" | "可播预览" | "失败可重试" | "尚未提交渲染";
  detail: string;
  playableUrl: string | null;
  /** MOCK_PROVIDERS / provider 名含 mock 的成片。文案必须写明不是 live Wan。 */
  mockReady: boolean;
  errorCode: string | null;
}

export interface ShellVoiceCopy {
  label: "TTS + 库选数字人" | "旁白字幕";
  detail: string;
}

const IDLE_VIEW: ShellRenderView = {
  phase: "idle",
  headline: "尚未提交渲染",
  detail: "确认过闸后会提交与托管工作台相同的渲染任务。",
  playableUrl: null,
  mockReady: false,
  errorCode: null,
};

const inflight = new Map<string, Promise<ShellRenderView>>();

export function resetShellRenderFlight(): void {
  inflight.clear();
}

export function presenterIsAbsent(presenterId: string | null | undefined): boolean {
  if (presenterId == null) return true;
  const trimmed = presenterId.trim();
  return trimmed.length === 0 || trimmed === "none" || trimmed === "无人";
}

/** 有出镜人：TTS + 库选。没有人：旁白字幕。两边都不承诺克隆或原声对口型。 */
export function shellVoiceCopy(presenterId: string | null | undefined): ShellVoiceCopy {
  if (presenterIsAbsent(presenterId)) {
    return {
      label: "旁白字幕",
      detail: "没有出镜人。成片是旁白加字幕，不是克隆声，也不做原声对口型。",
    };
  }
  return {
    label: "TTS + 库选数字人",
    detail: "配音走 TTS，出镜人来自库选。不是克隆声，也不做原声对口型。",
  };
}

export function isMockProvider(provider: string | null | undefined): boolean {
  return Boolean(provider && /mock/i.test(provider));
}

function isLive(plan: VideoPlan): boolean {
  return (
    plan.status === "video_generating"
    || plan.status === "video_ready"
    || plan.status === "rendering"
    || plan.batch_status === "running"
  );
}

function isDone(plan: VideoPlan): boolean {
  return plan.status === "completed" || plan.batch_status === "done";
}

function isFailed(plan: VideoPlan): boolean {
  return (
    plan.status === "failed"
    || plan.batch_status === "failed"
    || plan.batch_status === "interrupted"
    || plan.batch_status === "stopped"
  );
}

export function describeShellRender(plan: VideoPlan | null, downloadUrl: string | null): ShellRenderView {
  if (!plan) return IDLE_VIEW;
  const mock = isMockProvider(plan.provider);
  const url = downloadUrl || plan.video_url || null;
  if (isFailed(plan)) {
    const code = plan.error_code;
    return {
      phase: "failed",
      headline: "失败可重试",
      detail: code ? `渲染失败（${code}）。可以重试，这里不会显示成片。` : "渲染失败。可以重试，这里不会显示成片。",
      playableUrl: null,
      mockReady: false,
      errorCode: code,
    };
  }
  if (isDone(plan)) {
    return {
      phase: "playable",
      headline: "可播预览",
      detail: mock ? "Mock 成片就绪。这不是 live Wan。" : "成片可以预览。",
      playableUrl: url,
      mockReady: mock,
      errorCode: null,
    };
  }
  if (isLive(plan)) {
    return {
      phase: "queued",
      headline: "排队中",
      detail: mock ? "Mock 渲染已入队。完成前不能当作成片。" : "渲染已提交，排队中。完成前这里不是成片。",
      playableUrl: null,
      mockReady: false,
      errorCode: null,
    };
  }
  return IDLE_VIEW;
}

async function playbackUrl(client: ShellRenderClient, projectId: string, plan: VideoPlan | null): Promise<string | null> {
  try {
    const output = await client.getOutput(projectId);
    if (output?.download_url) return output.download_url;
  } catch {
    /* 没有产物就退回方案上的地址 */
  }
  return plan?.video_url ?? null;
}

async function runEnqueue(projectId: string, client: ShellRenderClient, force: boolean): Promise<ShellRenderView> {
  const current = await client.getVideo(projectId);
  let plan = current.plan;
  if (plan && !force && (isLive(plan) || isDone(plan) || isFailed(plan))) {
    return describeShellRender(plan, await playbackUrl(client, projectId, plan));
  }
  if (!plan) {
    const created = await client.createVideoPlan(projectId, "product", "clean", "one_shot");
    plan = created.plan;
    if (!plan) throw new Error("视频方案创建失败");
  }
  await client.getVideoEstimate(projectId, plan.plan_id);
  await client.approveCost(projectId, plan.plan_id);
  const dispatched: VideoState = plan.path === "segmented"
    ? await client.startVideoBatch(projectId)
    : await client.requestVideo(projectId);
  const next = dispatched.plan ?? plan;
  return describeShellRender(next, await playbackUrl(client, projectId, next));
}

/** 入队。同一项目并发调用共用一个 promise，避免连点打出两单。 */
export function enqueueShellRender(
  projectId: string,
  client: ShellRenderClient = defaultClient,
  options?: { force?: boolean },
): Promise<ShellRenderView> {
  const force = options?.force === true;
  if (!force) {
    const pending = inflight.get(projectId);
    if (pending) return pending;
  }
  const task = runEnqueue(projectId, client, force);
  inflight.set(projectId, task);
  return task.finally(() => {
    if (inflight.get(projectId) === task) inflight.delete(projectId);
  });
}

export function readShellRender(
  projectId: string,
  client: ShellRenderClient = defaultClient,
): Promise<ShellRenderView> {
  return client.getVideo(projectId).then(async (video) => (
    describeShellRender(video.plan, await playbackUrl(client, projectId, video.plan))
  ));
}
