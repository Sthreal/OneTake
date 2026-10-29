/** iter18 信息架构（纯数据，可单测）。
 *
 * 图片广告是独立交付，不在工作室四步里，也不能当「下一步」的条件。
 * 上手四步只指路，每步去不同的页面。
 */
import type { ShellView } from "../urlState";

export const STUDIO_STEPS = [
  { view: "prepare", label: "准备素材", short: "准备" },
  { view: "review", label: "审稿确认", short: "审稿" },
  { view: "generate", label: "编排预览", short: "编排" },
  { view: "delivery", label: "交付说明", short: "说明" },
] as const;

export type StudioView = (typeof STUDIO_STEPS)[number]["view"];

export function isStudioView(view: string): view is StudioView {
  return STUDIO_STEPS.some((step) => step.view === view);
}

/** 工作室的下一步。图片广告 / 首页 / 品牌都不在这条链上。 */
export function nextStudioView(current: string): StudioView | null {
  const order = STUDIO_STEPS.map((step) => step.view);
  const index = order.indexOf(current as StudioView);
  if (index < 0 || index >= order.length - 1) return null;
  return order[index + 1];
}

export interface GsStep {
  id: 1 | 2 | 3 | 4;
  name: string;
  dest: ShellView;
  cta: string;
  title: string;
  description: string;
  optional?: boolean;
}

export const GS_STEPS: readonly GsStep[] = [
  {
    id: 1,
    name: "加商品",
    dest: "brand",
    cta: "去品牌空间",
    title: "加商品",
    description: "在品牌空间上传主图与卖点，后续图片广告 / 出片可直接选用。",
  },
  {
    id: 2,
    name: "图片广告",
    dest: "image",
    cta: "去图片广告",
    title: "图片广告",
    description: "独立能力：3×3 九宫格是演示占位，不是真实出图。与工作室出片互不依赖。",
  },
  {
    id: 3,
    name: "生成视频",
    dest: "prepare",
    cta: "进入工作室",
    title: "生成视频",
    description: "打开工作室做编排预览。付费成片在托管工作台，外壳单独走完不会出视频。",
  },
  {
    id: 4,
    name: "发布广告",
    dest: "connect",
    cta: "连接并发布",
    title: "发布广告",
    description: "入口保留。抖音 / 小红书有机发布尚未接线，打开后也不能发出去。可跳过。",
    optional: true,
  },
];

export function gsDestinations(): ShellView[] {
  return GS_STEPS.map((step) => step.dest);
}

export const IMAGE_AD_RATIOS = ["1:1", "4:5", "9:16"] as const;
export type ImageAdRatio = (typeof IMAGE_AD_RATIOS)[number];

export const IMAGE_AD_CELLS = [
  { id: "1", caption: "白底棚拍", tone: "g1" },
  { id: "2", caption: "质地特写", tone: "g2" },
  { id: "3", caption: "瓶身 45°", tone: "g3" },
  { id: "4", caption: "手部持瓶", tone: "g4" },
  { id: "5", caption: "场景平铺", tone: "g5" },
  { id: "6", caption: "卖点排版", tone: "g6" },
  { id: "7", caption: "对比前后", tone: "g7" },
  { id: "8", caption: "礼盒合影", tone: "g8" },
  { id: "9", caption: "社媒封面", tone: "g9" },
] as const;

export type ImageAdCell = (typeof IMAGE_AD_CELLS)[number];

export const REVIEW_CELLS = [
  { id: "1", caption: "开场特写", dur: "3.2s", tone: "g1", group: "开场" },
  { id: "2", caption: "瓶身展示", dur: "3.0s", tone: "g2", group: "开场" },
  { id: "3", caption: "质地滴落", dur: "3.5s", tone: "g3", group: "卖点" },
  { id: "4", caption: "涂抹手部", dur: "3.8s", tone: "g4", group: "卖点" },
  { id: "5", caption: "面部特写", dur: "3.5s", tone: "g5", group: "卖点" },
  { id: "6", caption: "卖点字幕", dur: "3.0s", tone: "g6", group: "卖点" },
  { id: "7", caption: "护肤日常", dur: "3.2s", tone: "g7", group: "收尾" },
  { id: "8", caption: "产品合影", dur: "3.0s", tone: "g8", group: "收尾" },
  { id: "9", caption: "CTA 收尾", dur: "3.8s", tone: "g9", group: "收尾" },
] as const;

export const REVIEW_FILTERS = ["全部", "开场", "卖点", "收尾"] as const;

export function visibleReviewCells(filter: (typeof REVIEW_FILTERS)[number]) {
  if (filter === "全部") return REVIEW_CELLS;
  return REVIEW_CELLS.filter((cell) => cell.group === filter);
}

export const STUDIO_RATIOS = ["9:16", "1:1", "16:9"] as const;
export const STUDIO_DURATIONS = ["15s", "30s", "60s"] as const;
export type StudioRatio = (typeof STUDIO_RATIOS)[number];
export type StudioDuration = (typeof STUDIO_DURATIONS)[number];

export const SELLING_POINTS = [
  { id: "texture", title: "突出材质与质感", desc: "轻薄不粘腻、一抹吸收" },
  { id: "sensitive", title: "强调敏感肌友好", desc: "三重保湿 · 安心配方" },
  { id: "promo", title: "限时促销话术", desc: "下单赠小样 · 可选" },
] as const;

export const PREMADE_PRESENTER = {
  id: "premade:linxiao",
  name: "林晓",
  role: "女声 · 温和种草 · 预制",
  initial: "林",
} as const;

export interface PresenterOption {
  id: string;
  name: string;
  role: string;
  initial: string;
  source: "premade" | "library";
}

export function presenterOptions(characters: { character_id: string; name: string; voice_style: string | null }[]): PresenterOption[] {
  return [
    { ...PREMADE_PRESENTER, source: "premade" },
    ...characters.map((character) => ({
      id: character.character_id,
      name: character.name,
      role: character.voice_style?.trim() || "出镜人库",
      initial: character.name.trim().slice(0, 1) || "人",
      source: "library" as const,
    })),
  ];
}

export function presenterById(id: string | null, characters: { character_id: string; name: string; voice_style: string | null }[]): PresenterOption {
  const options = presenterOptions(characters);
  return options.find((item) => item.id === id) ?? options[0];
}

export interface ShelfProduct {
  project_id: string;
  product_name: string;
}

/** 没有指定 id 时用品牌库第一条；指定了但库里没有，就不偷换另一件商品。 */
export function resolveSelectedProduct<T extends ShelfProduct>(projectId: string | null, products: T[]): T | null {
  if (projectId) return products.find((item) => item.project_id === projectId) ?? null;
  return products[0] ?? null;
}

export interface StudioDraft {
  projectId: string | null;
  presenterId: string;
  ratio: StudioRatio;
  duration: StudioDuration;
  points: string[];
}

const DRAFT_KEY = "onetake.studioDraft.v1";
const GS_KEY = "onetake.gsDone.v1";
const BRAND_KEY = "onetake.brands.v1";

export const DEFAULT_STUDIO_DRAFT: StudioDraft = {
  projectId: null,
  presenterId: PREMADE_PRESENTER.id,
  ratio: "9:16",
  duration: "30s",
  points: ["texture", "sensitive"],
};

function isRatio(value: unknown): value is StudioRatio {
  return STUDIO_RATIOS.includes(value as StudioRatio);
}

function isDuration(value: unknown): value is StudioDuration {
  return STUDIO_DURATIONS.includes(value as StudioDuration);
}

export function normalizeStudioDraft(raw: Partial<StudioDraft> | null | undefined): StudioDraft {
  const pointIds = new Set(SELLING_POINTS.map((item) => item.id));
  const points = Array.isArray(raw?.points)
    ? raw.points.filter((id): id is string => typeof id === "string" && pointIds.has(id as (typeof SELLING_POINTS)[number]["id"]))
    : [...DEFAULT_STUDIO_DRAFT.points];
  return {
    projectId: typeof raw?.projectId === "string" && raw.projectId ? raw.projectId : null,
    presenterId: typeof raw?.presenterId === "string" && raw.presenterId ? raw.presenterId : PREMADE_PRESENTER.id,
    ratio: isRatio(raw?.ratio) ? raw.ratio : DEFAULT_STUDIO_DRAFT.ratio,
    duration: isDuration(raw?.duration) ? raw.duration : DEFAULT_STUDIO_DRAFT.duration,
    points,
  };
}

export function readStudioDraft(urlProjectId: string | null): StudioDraft {
  let stored: Partial<StudioDraft> | null = null;
  try {
    const raw = localStorage.getItem(DRAFT_KEY);
    stored = raw ? (JSON.parse(raw) as Partial<StudioDraft>) : null;
  } catch {
    stored = null;
  }
  const draft = normalizeStudioDraft(stored);
  if (urlProjectId) draft.projectId = urlProjectId;
  return draft;
}

export function writeStudioDraft(draft: StudioDraft): StudioDraft {
  const next = normalizeStudioDraft(draft);
  localStorage.setItem(DRAFT_KEY, JSON.stringify(next));
  return next;
}

export function readGsDone(): number[] {
  try {
    const raw = localStorage.getItem(GS_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((id) => GS_STEPS.some((step) => step.id === id));
  } catch {
    return [];
  }
}

export function markGsDone(id: number): number[] {
  const next = [...new Set([...readGsDone(), id])].sort((a, b) => a - b);
  localStorage.setItem(GS_KEY, JSON.stringify(next));
  return next;
}

export interface BrandRecord {
  id: string;
  name: string;
}

export function readBrands(): BrandRecord[] {
  try {
    const raw = localStorage.getItem(BRAND_KEY);
    const parsed = raw ? (JSON.parse(raw) as BrandRecord[]) : [];
    if (Array.isArray(parsed) && parsed.length > 0 && parsed.every((item) => item && typeof item.name === "string")) {
      return parsed;
    }
  } catch {
    /* 坏数据就退回锁死的示例品牌 */
  }
  return [{ id: "brand-chunyan", name: "春研护肤" }];
}

export function writeBrands(brands: BrandRecord[]): BrandRecord[] {
  localStorage.setItem(BRAND_KEY, JSON.stringify(brands));
  return brands;
}

export function imageAdExportPayload(input: { caption: string; ratio: string; productName: string }): { filename: string; text: string } {
  const safe = input.caption.replace(/\s+/g, "");
  return {
    filename: `图片广告-${safe}.txt`,
    text: [
      "OneTake 图片广告 · 演示预览说明",
      `商品：${input.productName}`,
      `画幅：${input.ratio}`,
      `画面占位：${input.caption}`,
      "这不是真实图片，也不是导出的成图。",
      "独立说明。视频工作室不读取本文件，也不把图片广告当作前置步骤。",
    ].join("\n"),
  };
}

export const DEMO_CREDITS = 128;
export const DEMO_FEE = 12;
