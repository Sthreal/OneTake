/** 「输入 → 前 4 段跑完（停在闸①前）」的**唯一实现**：小白托管主路与导演模式共用。
 *
 * 为什么必须共用：两种模式的区别**只在之后要不要人为干预** —— 输入这一段完全一样
 * （商品图 / 商品链接 → 建项目 → 自动链跑到闸①前）。写两份必然漂移；本仓已经因为
 * "两处各写一份"栽过两次（九宫格、四视角母版），后来都靠"消除第二处实现"收拾。
 *
 * 复杂度全部交给后端自动链 `POST /auto-run`（前 4 段：识别 → 主图 → 文案 → 配音字幕）。
 */
import { inspectImageFile } from "../features/input/validation";
import { completeAsset, presignAsset } from "../shared/api/assetApi";
import { createProject, createProjectFromUrl, updateProject } from "../shared/api/projectApi";
import { getPipeline } from "../shared/api/recognitionApi";
import { startAutoRun } from "./api";
import { stepIndexFromStatus } from "./policy";

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** 前 4 段最多等多久。
 *
 * 这里**刻意不做**"卡住就自动重推"（2026-10-16 用户明确要求停掉）：旧实现每 5 秒重新 POST 一次
 * `/auto-run`（上限 20 次），实测对"没有素材 / 一直在排队"的项目**一次都推不动**，只是后台锤接口。
 * 现在：推一次、然后只轮询；等不到就停下来说清楚卡在哪、下一步点哪。
 */
const INTAKE_WAIT_MS = 10 * 60 * 1000;

/** 轮询到条件满足（DemoApp 与导演模式共用；原先是 DemoApp 里的局部函数）。 */
export async function until<T>(
  fetch: () => Promise<T>,
  done: (value: T) => boolean,
  { intervalMs = 2500, timeoutMs = 45 * 60 * 1000 }: { intervalMs?: number; timeoutMs?: number } = {},
): Promise<T> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const value = await fetch();
    if (done(value)) return value;
    if (Date.now() > deadline) throw new Error("等待超时（可以刷新页面看状态，任务仍在后台跑）");
    await sleep(intervalMs);
  }
}

/** 自动链跑完前 4 段后会停在这些状态之一（闸①之前都算"可以往下走"）。 */
export const INTAKE_READY_STATUSES = [
  "audio_subtitle_confirmed",
  "content_plan_ready",
  "content_plan_confirmed",
  "content_qa_passed",
];

export interface ProjectIntakeInput {
  mode: "file" | "url";
  file?: File | null;
  productUrl?: string;
  /** 商品名（file 模式必填其一时用；缺省用"演示商品"） */
  name?: string;
  /** 卖点/备注（可选） */
  note?: string;
  characterId?: string;
}

export interface ProjectIntakeEvents {
  /** 进度日志（err=true 表示需要用户注意） */
  log: (text: string, err?: boolean) => void;
  /** 前端进度清单的下标（可选；导演模式不需要清单） */
  onStage?: (index: number) => void;
}

/** 建项目（图/链接）→ 跑前 4 段 → 返回 projectId。失败抛错（调用方负责展示）。 */
export async function runProjectIntake(input: ProjectIntakeInput, events: ProjectIntakeEvents): Promise<string> {
  const { log } = events;
  log("创建项目…");
  events.onStage?.(0);

  let projectId: string;
  if (input.mode === "url") {
    const url = (input.productUrl ?? "").trim();
    if (!url) throw new Error("请先贴商品链接");
    // 这两类**在请求前**就拦掉：后端只能回「参数不合法（422）」，说不清是哪一步（2026-10-15 用户实测踩到）。
    if (!/^https?:\/\//i.test(url)) {
      throw new Error("链接要以 http:// 或 https:// 开头（从浏览器地址栏复制整条链接）");
    }
    if (url.length > 2048) {
      throw new Error(`链接太长（${url.length} 字符，上限 2048）：把问号后面的跟踪参数删掉再试`);
    }
    const imported = await createProjectFromUrl(url);
    projectId = imported.project_id;
    if (imported.warning) log("⚠️ " + imported.warning, true);
    log(`已从链接导入：${imported.product_name}（${imported.asset_ids.length} 张图）`);
    if (imported.asset_ids.length === 0) {
      // 一张图都没有 = 后面 4 段一步都跑不了（识别没有输入）。**不启动自动链、也不轮询**，
      // 直接把话说清楚 —— 旧实现会在这里转 45 分钟 + 后台重推 20 次（用户实测踩到）。
      throw new Error(
        "这个页面没抓到可用商品图（项目已建好，在「项目」里能找到它）。" +
          "请改用「上传商品图」补一张（商品主图截图即可）再点开始。",
      );
    }
  } else {
    const file = input.file ?? null;
    if (!file) throw new Error("请先选一张商品图");
    // **先校验图片 → 再建项目**（2026-10-16 实测）：原来顺序反了，图片不合格时会留下一个
    // **没有素材的空项目**，界面停在"上传商品图…"看着像卡死（用户连点三次 → 三个空项目）。
    let metadata;
    try {
      metadata = await inspectImageFile(file);
    } catch (error) {
      const reason = error instanceof Error ? error.message : "图片无法读取";
      throw new Error(
        `这张图不能用作商品图：${reason}。要求：JPG/PNG/WebP、≤10 MB、短边 ≥512、长边 ≤6000、比例 ≤5:1。`,
      );
    }
    const project = await createProject({
      productName: (input.name ?? "").trim() || "演示商品",
      productNote: (input.note ?? "").trim() || undefined,
    });
    projectId = project.project_id;
    log("上传商品图…");
    const presigned = await presignAsset(projectId, metadata);
    const put = await fetch(presigned.upload_url, {
      method: "PUT",
      headers: presigned.required_headers ?? {},
      body: file,
    });
    if (!put.ok) throw new Error(`图片上传失败（${put.status}）`);
    await completeAsset(projectId, presigned.asset_id, metadata);
  }
  events.onStage?.(1);

  if (input.characterId) {
    try {
      await updateProject(projectId, { characterId: input.characterId });
      log(`已选用出镜人 ${input.characterId}（身份锚点来自人物库母版，不额外花钱）。`);
    } catch (error) {
      log("⚠️ 出镜人绑定失败，本条不带头像锚点：" + (error instanceof Error ? error.message : "未知错误"), true);
    }
  }

  log("启动自动链（识别 → 主图 → 文案 → 配音字幕，全部自动）…");
  const run = await startAutoRun(projectId);
  log(`自动链返回：stopped_at=${run.stopped_at ?? "-"} / stopped_reason=${run.stopped_reason ?? "-"}`);

  log("等待前 4 段产出（识别/主图/文案/配音字幕，分钟级，请不要关页面）…");
  let lastStatus = "未知";
  const pipeline = await until(
    async () => {
      const value = await getPipeline(projectId);
      lastStatus = value.status;
      events.onStage?.(stepIndexFromStatus(value.status));
      return value;
    },
    (value) => INTAKE_READY_STATUSES.includes(value.status),
    { intervalMs: 5000, timeoutMs: INTAKE_WAIT_MS },
  ).catch((err: unknown) => {
    const reason = err instanceof Error ? err.message : "等待失败";
    throw new Error(
      `${reason}｜项目已建好（${projectId}），流水线停在：${lastStatus}。` +
        "可在「项目」里打开它继续，或补图后重试。",
    );
  });
  log(`流水线状态：${pipeline.status}`);
  return projectId;
}
