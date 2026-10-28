/** 前端的**URL 状态**（不引第三方路由）：让"所在视图 + 导演模式的 4 步"都能被 URL 表达。
 *
 * 方案 §3.1 要求「4 步每步一个独立页面 + 独立 URL」。本仓 web 只装了 react/react-dom（新增依赖要单独
 * 授权），所以这里用 `pushState` + `popstate` 满足它的**意图**：每一步都有**可寻址的 URL** ——
 * 可直接分享/刷新回到同一步，浏览器后退 / 前进也能走。
 *
 * 纯函数（解析 / 生成 / 合并）与副作用（读写地址栏）分开：前者有单测，后者只在浏览器里跑。
 */
import { DIRECTOR_STEPS, type DirectorStepKey } from "./director";

// 「商品链接」不再占一个侧边栏入口：它是工作台内的一个 tab（同一页不必开两个门）。
// 旧的 `?view=workbench-url` 仍落到托管工作台，不会白屏。
// 默认视图是首页（iter18）。图片广告、品牌空间、发布、工作室四步各自一个 view，
// 不复用导演模式的 step，避免「出图」再变成视频的必经步骤。
export const SHELL_VIEWS = ["home", "brand", "image", "projects", "connect", "prepare", "review", "generate", "delivery"] as const;
export type ShellView = (typeof SHELL_VIEWS)[number];
export type UrlView = ShellView | "workbench" | "director" | "characters";

export function isShellView(view: UrlView): view is ShellView {
  return (SHELL_VIEWS as readonly string[]).includes(view);
}

export interface UrlState {
  view: UrlView;
  projectId: string | null;
  step: DirectorStepKey;
}

export const DEFAULT_URL_STATE: UrlState = { view: "home", projectId: null, step: "storyboard" };

const VIEWS: UrlView[] = [...SHELL_VIEWS, "workbench", "director", "characters"];
const STEPS: DirectorStepKey[] = DIRECTOR_STEPS.map((item) => item.key);

/** 解析地址栏查询串；**不认识的值一律退回默认**（手改 URL 不该把页面弄崩）。 */
export function parseUrlState(search: string): UrlState {
  const params = new URLSearchParams(search.startsWith("?") ? search : `?${search}`);
  const rawView = params.get("view");
  const step = params.get("step");
  const projectId = params.get("project") || null;
  const parsedStep = STEPS.includes(step as DirectorStepKey) ? (step as DirectorStepKey) : DEFAULT_URL_STATE.step;
  // 旧链接：商品链接曾单独占一个 view，入口删除后仍打开托管工作台。
  if (rawView === "workbench-url") return { view: "workbench", projectId, step: parsedStep };
  return {
    view: VIEWS.includes(rawView as UrlView) ? (rawView as UrlView) : DEFAULT_URL_STATE.view,
    projectId,
    step: parsedStep,
  };
}

/** 生成查询串：默认首页不写进 URL；`step` 只在导演模式里有意义。 */
export function buildUrlSearch(state: UrlState): string {
  const params = new URLSearchParams();
  if (state.view !== DEFAULT_URL_STATE.view) params.set("view", state.view);
  if (state.projectId) params.set("project", state.projectId);
  if (state.view === "director" && state.step !== DEFAULT_URL_STATE.step) params.set("step", state.step);
  return params.toString();
}

export function patchUrlState(current: UrlState, patch: Partial<UrlState>): UrlState {
  return { ...current, ...patch };
}

/** 读当前地址栏；非浏览器环境（单测）返回默认值 —— 不抛错。 */
export function readUrlState(search?: string): UrlState {
  if (search === undefined) {
    return parseUrlState(typeof window === "undefined" ? "" : window.location.search);
  }
  return parseUrlState(search);
}

/** 把状态写进地址栏（产生一条历史记录，后退可回）。 */
export function pushUrlState(state: UrlState): void {
  if (typeof window === "undefined") return;
  const search = buildUrlSearch(state);
  window.history.pushState(null, "", `${window.location.pathname}${search ? `?${search}` : ""}`);
}

/** 订阅浏览器后退 / 前进；返回取消订阅。 */
export function subscribeUrlState(onChange: (state: UrlState) => void): () => void {
  if (typeof window === "undefined") return () => {};
  const handler = () => onChange(readUrlState());
  window.addEventListener("popstate", handler);
  return () => window.removeEventListener("popstate", handler);
}
