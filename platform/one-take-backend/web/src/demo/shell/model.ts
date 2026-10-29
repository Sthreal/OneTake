/** iter18 信息架构（纯数据，可单测）。
 *
 * 图片广告是独立交付，不在工作室四步里，也不能当「下一步」的条件。
 * 上手四步只指路，每步去不同的页面。
 */
import type { ShellView } from "../urlState";

export const STUDIO_STEPS = [
  { view: "prepare", label: "准备素材", short: "准备" },
  { view: "review", label: "审稿确认", short: "审稿" },
  { view: "generate", label: "生成成片", short: "生成" },
  { view: "delivery", label: "成片交付", short: "交付" },
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
    description: "打开工作室：选角、过审稿闸，确认后提交渲染。不必先打开导演页。",
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

/** 本场创作路径。只活在工作室草稿里，不写回商品，也不进服务端项目。 */
export const STUDIO_PATHS = [
  { id: "talking_head", name: "口播出镜", description: "库选出镜人讲解卖点，适合种草口播" },
  { id: "product_only", name: "纯商品无人", description: "不出镜人，商品镜头 + 旁白/字幕" },
  { id: "multi_angle", name: "多角度口播", description: "一次出 3 套文案角度，选中后再审稿" },
] as const;

export type StudioCreationPath = (typeof STUDIO_PATHS)[number]["id"];

export const PATH_SECTION_TITLE = "创作路径";
export const PATH_SECTION_SUB = "同一商品信息，选不同成片方式 · 不增加费用";
export const PATH_CHANGED_HINT = "路径已变，如需按新路径重出稿请点重新生成";
export const TALKING_HEAD_PRESENTER_REQUIRED = "口播出镜路径请选择一位出镜人";
export const PRODUCT_ONLY_CAST_TITLE = "本路径不出镜人";
export const PRODUCT_ONLY_CAST_HINT = "如需出镜请改选「口播出镜」或「多角度口播」";

export function isStudioPath(value: unknown): value is StudioCreationPath {
  return STUDIO_PATHS.some((item) => item.id === value);
}

export function studioPathName(path: StudioCreationPath): string {
  return STUDIO_PATHS.find((item) => item.id === path)?.name ?? "纯商品无人";
}

export const PREMADE_PRESENTER = {
  id: "premade:linxiao",
  name: "林晓",
  role: "女声 · 温和种草 · 预制",
  initial: "林",
} as const;

/** 显式「无出镜人」。id 用 null，不用哨兵字符串，避免再被当成库 id 写进项目。 */
export const NO_PRESENTER = {
  id: null,
  name: "无出镜人",
  role: "商品镜头为主，不出现人物",
  initial: "",
  source: "none",
} as const;

export interface PresenterOption {
  id: string | null;
  name: string;
  role: string;
  initial: string;
  source: "none" | "premade" | "library";
}

export function presenterOptions(characters: { character_id: string; name: string; voice_style: string | null }[]): PresenterOption[] {
  return [
    { ...NO_PRESENTER },
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
  if (id === null || id === "") return options.find((item) => item.source === "none") ?? { ...NO_PRESENTER };
  return options.find((item) => item.id === id) ?? { ...PREMADE_PRESENTER, source: "premade" };
}

export function isLibraryPresenterId(presenterId: string | null): presenterId is string {
  return typeof presenterId === "string" && presenterId.length > 0 && !presenterId.startsWith("premade:");
}

/**
 * 开始制作 / 进入生成前要写回项目的 character_id。
 * null = 显式清空。预制人不是人物库 id，不能写进项目，也不能在没选人时拿来顶上。
 * 关键帧 / 分镜在 character_id 为空时走已有无人物分支。
 */
export function projectCharacterSync(presenterId: string | null): { characterId: string | null } | null {
  if (presenterId === null) return { characterId: null };
  if (isLibraryPresenterId(presenterId)) return { characterId: presenterId };
  return null;
}

export const PRESENTER_CLEAR_FAILED = "没能清空项目里的出镜人，已停止。不会改用预制出镜人。";

/** 审稿费用旁注。闸门两句（确认前不扣积分 / 未过闸不会进入付费生成）有人和无人都保留。 */
export function reviewFeeHint(presenter: { source: PresenterOption["source"]; name: string }): string {
  const voice = presenter.source === "none"
    ? "本场无出镜人 · 口播将以配音/字幕呈现"
    : `配音人 ${presenter.name}`;
  return `确认前不扣积分。${voice}。未过闸不会进入付费生成。`;
}

export function generatePresenterCheck(presenter: { source: PresenterOption["source"]; name: string; role: string }): string {
  if (presenter.source === "none") return "出镜：无（纯商品）";
  return `出镜人：${presenter.name} · ${presenter.role}`;
}

/** 无人时交付页不渲染人才卡，只留纯商品说明。 */
export function deliveryPresenterCheck(presenter: { source: PresenterOption["source"]; name: string }): string {
  if (presenter.source === "none") return "纯商品镜头 · 无人出镜";
  return `出镜人：${presenter.name}`;
}

export function deliveryShowsTalent(presenter: { source: PresenterOption["source"] }): boolean {
  return presenter.source !== "none";
}

export interface ShelfProduct {
  project_id: string;
  product_name: string;
}

/** 没有 project id，或 id 不在库里，都不偷换另一件商品（包括不拿 products[0]）。 */
export function resolveSelectedProduct<T extends ShelfProduct>(projectId: string | null, products: T[]): T | null {
  if (!projectId) return null;
  return products.find((item) => item.project_id === projectId) ?? null;
}

export interface StudioDraft {
  projectId: string | null;
  /** 本场成片方式。缺省（旧稿没有这个字段）是纯商品无人。 */
  path: StudioCreationPath;
  /**
   * null = 无出镜人。空字符串也会收成 null，不再回退预制人。
   * 纯商品路径强制 null。口播路径可以暂时为 null，但开始制作会拦住。
   */
  presenterId: string | null;
  /**
   * 切到口播出镜、而当前又无人时，用来预填。纯商品会清掉 presenterId，但把上一次人选留在这里。
   */
  lastPresenterId: string | null;
  ratio: StudioRatio;
  duration: StudioDuration;
  /** 勾选后，下面的文本只覆盖这一次出片，不写回商品草稿。 */
  sessionOnly: boolean;
  /** null = 没有本场覆盖，用商品草稿。空字符串 = 本场明确清空。 */
  pain_point: string | null;
  selling_points: string[] | null;
  usage_scenario: string | null;
  offer: string | null;
  specs: string | null;
}

const DRAFT_KEY_V3 = "onetake.studioDraft.v3";
const DRAFT_KEY_V2 = "onetake.studioDraft.v2";
const DRAFT_KEY_V1 = "onetake.studioDraft.v1";
const GS_KEY = "onetake.gsDone.v1";
const BRAND_KEY = "onetake.brands.v1";

export const DEFAULT_STUDIO_DRAFT: StudioDraft = {
  projectId: null,
  path: "product_only",
  presenterId: null,
  lastPresenterId: null,
  ratio: "9:16",
  duration: "30s",
  sessionOnly: false,
  pain_point: null,
  selling_points: null,
  usage_scenario: null,
  offer: null,
  specs: null,
};

function isRatio(value: unknown): value is StudioRatio {
  return STUDIO_RATIOS.includes(value as StudioRatio);
}

function isDuration(value: unknown): value is StudioDuration {
  return STUDIO_DURATIONS.includes(value as StudioDuration);
}

function nullableText(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function nullablePoints(value: unknown): string[] | null {
  if (value == null) return null;
  if (!Array.isArray(value)) return null;
  return value.filter((item): item is string => typeof item === "string").slice(0, 5);
}

/** 有字才算人选。null、空串、哨兵 `none` 都是无出镜人。字段缺失时返回 undefined。 */
function readPresenterField(raw: object, key: "presenterId" | "lastPresenterId"): string | null | undefined {
  if (!Object.prototype.hasOwnProperty.call(raw, key)) return undefined;
  const value = (raw as Record<string, unknown>)[key];
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (!trimmed || trimmed === "none") return null;
  return trimmed;
}

/**
 * 按路径收出镜人。
 * 纯商品强制无人，但把旧的非空人选留在 lastPresenterId。
 * 口播缺字段时用上次人选或预制；显式 null 先留着，交给开始制作拦截，避免把用户刚点的「无出镜人」立刻填回去。
 * 多角度缺字段默认无人，显式人选保留。
 */
function alignPresenter(
  path: StudioCreationPath,
  raw: object,
): { presenterId: string | null; lastPresenterId: string | null } {
  const presenterField = readPresenterField(raw, "presenterId");
  const lastField = readPresenterField(raw, "lastPresenterId") ?? null;
  const explicit = presenterField === undefined ? null : presenterField;
  if (path === "product_only") {
    return { presenterId: null, lastPresenterId: explicit ?? lastField };
  }
  if (path === "talking_head") {
    const presenterId = presenterField === undefined ? (lastField ?? PREMADE_PRESENTER.id) : presenterField;
    return { presenterId, lastPresenterId: presenterId ?? lastField };
  }
  const presenterId = presenterField === undefined ? null : presenterField;
  return { presenterId, lastPresenterId: presenterId ?? lastField };
}

/** 旧 v1 的 `points`（checkbox id）直接丢掉，不映射成卖点文案。无 path 的旧稿按纯商品无人。 */
export function normalizeStudioDraft(raw: (Partial<StudioDraft> & { points?: unknown }) | null | undefined): StudioDraft {
  const record = raw && typeof raw === "object" ? raw : {};
  const path = isStudioPath(record.path) ? record.path : "product_only";
  const presenter = alignPresenter(path, record);
  return {
    projectId: typeof record.projectId === "string" && record.projectId ? record.projectId : null,
    path,
    presenterId: presenter.presenterId,
    lastPresenterId: presenter.lastPresenterId,
    ratio: isRatio(record.ratio) ? record.ratio : DEFAULT_STUDIO_DRAFT.ratio,
    duration: isDuration(record.duration) ? record.duration : DEFAULT_STUDIO_DRAFT.duration,
    sessionOnly: record.sessionOnly === true,
    pain_point: nullableText(record.pain_point),
    selling_points: nullablePoints(record.selling_points),
    usage_scenario: nullableText(record.usage_scenario),
    offer: nullableText(record.offer),
    specs: nullableText(record.specs),
  };
}

/** 换路径只动路径和出镜，不动痛点 / 卖点 / 场景，也不重新出稿。 */
export function switchStudioPath(draft: StudioDraft, path: StudioCreationPath): StudioDraft {
  if (path === draft.path) return draft;
  const remembered = draft.presenterId ?? draft.lastPresenterId;
  if (path === "product_only") {
    return { ...draft, path, presenterId: null, lastPresenterId: remembered };
  }
  if (path === "talking_head") {
    const presenterId = draft.presenterId ?? remembered ?? PREMADE_PRESENTER.id;
    return { ...draft, path, presenterId, lastPresenterId: presenterId };
  }
  return { ...draft, path, presenterId: draft.presenterId, lastPresenterId: remembered };
}

/** 库里点一个人。纯商品路径忽略人选，保持无人。点「无出镜人」不会忘掉上一次库选。 */
export function assignPresenter(draft: StudioDraft, presenterId: string | null): StudioDraft {
  if (draft.path === "product_only") return { ...draft, presenterId: null };
  const next = presenterId && presenterId.trim() && presenterId.trim() !== "none" ? presenterId.trim() : null;
  return {
    ...draft,
    presenterId: next,
    lastPresenterId: next ?? draft.lastPresenterId,
  };
}

export function talkingHeadStartError(draft: Pick<StudioDraft, "path" | "presenterId">): string | null {
  if (draft.path !== "talking_head") return null;
  if (draft.presenterId == null || draft.presenterId === "none") return TALKING_HEAD_PRESENTER_REQUIRED;
  return null;
}

export function readStudioDraft(urlProjectId: string | null): StudioDraft {
  let stored: unknown = null;
  let migrated = false;
  try {
    const current = localStorage.getItem(DRAFT_KEY_V3);
    if (current) {
      stored = JSON.parse(current) as unknown;
    } else {
      const previous = localStorage.getItem(DRAFT_KEY_V2) ?? localStorage.getItem(DRAFT_KEY_V1);
      if (previous) {
        stored = JSON.parse(previous) as unknown;
        migrated = true;
      }
    }
  } catch {
    stored = null;
  }
  const record = stored && typeof stored === "object" ? (stored as Partial<StudioDraft> & { points?: unknown }) : null;
  const draft = normalizeStudioDraft(record);
  if (urlProjectId && draft.projectId !== urlProjectId) {
    draft.pain_point = null;
    draft.selling_points = null;
    draft.usage_scenario = null;
    draft.offer = null;
    draft.specs = null;
  }
  if (urlProjectId) draft.projectId = urlProjectId;
  if (migrated) writeStudioDraft(draft);
  return draft;
}

export function writeStudioDraft(draft: StudioDraft): StudioDraft {
  const next = normalizeStudioDraft(draft);
  localStorage.setItem(DRAFT_KEY_V3, JSON.stringify(next));
  localStorage.removeItem(DRAFT_KEY_V2);
  localStorage.removeItem(DRAFT_KEY_V1);
  return next;
}

/** 商品富化还没进 Product API。文本记在本机；图片只活在本次页面内存里。PR-B 再换成真正的商品字段。 */
const SKU_KEY = "onetake.skuEnrichment.v1";

export const PREPARE_IMAGE_MAX_BYTES = 10 * 1024 * 1024;
export const PREPARE_IMAGE_ACCEPT = ".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp";

export const PREPARE_REQUIRED_COPY = {
  image: "请至少上传 1 张商品图",
  pain: "请填写痛点",
  points: "请至少添加 1 条卖点（最多 5 条）",
  scene: "请填写使用场景",
} as const;

export interface PrepareImage {
  id: string;
  name: string;
  mime: string;
  size: number;
  preview: string;
}

export interface SkuEnrichment {
  pain_point: string;
  selling_points: string[];
  usage_scenario: string;
  specs: string;
  offer: string;
  images: PrepareImage[];
}

interface StoredSkuText {
  pain_point: string;
  selling_points: string[];
  usage_scenario: string;
  specs: string;
  offer: string;
}

const EMPTY_SKU_TEXT: StoredSkuText = {
  pain_point: "",
  selling_points: [],
  usage_scenario: "",
  specs: "",
  offer: "",
};

let skuTextCache: Map<string, StoredSkuText> | null = null;
const skuImages = new Map<string, PrepareImage[]>();
const sessionImages = new Map<string, PrepareImage[]>();

export function resetPrepareMemory(): void {
  skuTextCache = null;
  skuImages.clear();
  sessionImages.clear();
}

function loadSkuText(): Map<string, StoredSkuText> {
  const map = new Map<string, StoredSkuText>();
  try {
    const raw = localStorage.getItem(SKU_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : null;
    if (!parsed || typeof parsed !== "object") return map;
    for (const [id, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (!value || typeof value !== "object") continue;
      const record = value as Partial<StoredSkuText>;
      map.set(id, {
        pain_point: typeof record.pain_point === "string" ? record.pain_point : "",
        selling_points: Array.isArray(record.selling_points)
          ? record.selling_points.filter((item): item is string => typeof item === "string").slice(0, 5)
          : [],
        usage_scenario: typeof record.usage_scenario === "string" ? record.usage_scenario : "",
        specs: typeof record.specs === "string" ? record.specs : "",
        offer: typeof record.offer === "string" ? record.offer : "",
      });
    }
  } catch {
    /* 坏草稿就当没有 */
  }
  return map;
}

function skuTexts(): Map<string, StoredSkuText> {
  if (!skuTextCache) skuTextCache = loadSkuText();
  return skuTextCache;
}

function persistSkuText(): void {
  const payload: Record<string, StoredSkuText> = {};
  for (const [id, value] of skuTexts()) payload[id] = value;
  try {
    localStorage.setItem(SKU_KEY, JSON.stringify(payload));
  } catch {
    /* 配额不够就只留内存，刷新后要重填 */
  }
}

function cloneImages(images: PrepareImage[]): PrepareImage[] {
  return images.map((image) => ({ ...image }));
}

export function emptySkuEnrichment(): SkuEnrichment {
  return { ...EMPTY_SKU_TEXT, selling_points: [], images: [] };
}

export function readSkuEnrichment(projectId: string): SkuEnrichment {
  const text = skuTexts().get(projectId) ?? EMPTY_SKU_TEXT;
  return {
    pain_point: text.pain_point,
    selling_points: [...text.selling_points],
    usage_scenario: text.usage_scenario,
    specs: text.specs,
    offer: text.offer,
    images: cloneImages(skuImages.get(projectId) ?? []),
  };
}

export function writeSkuEnrichment(projectId: string, fields: SkuEnrichment): SkuEnrichment {
  const selling = fields.selling_points.map((item) => item.trim()).filter(Boolean).slice(0, 5);
  const text: StoredSkuText = {
    pain_point: fields.pain_point,
    selling_points: selling,
    usage_scenario: fields.usage_scenario,
    specs: fields.specs,
    offer: fields.offer,
  };
  skuTexts().set(projectId, text);
  skuImages.set(projectId, cloneImages(fields.images));
  persistSkuText();
  return readSkuEnrichment(projectId);
}

export function clearSessionImages(projectId?: string): void {
  if (projectId) sessionImages.delete(projectId);
  else sessionImages.clear();
}

export function effectivePrepareFields(projectId: string, draft: StudioDraft): SkuEnrichment {
  const sku = readSkuEnrichment(projectId);
  const session = draft.sessionOnly && draft.projectId === projectId;
  if (!session) return sku;
  return {
    pain_point: draft.pain_point ?? sku.pain_point,
    selling_points: draft.selling_points ?? sku.selling_points,
    usage_scenario: draft.usage_scenario ?? sku.usage_scenario,
    specs: draft.specs ?? sku.specs,
    offer: draft.offer ?? sku.offer,
    images: sessionImages.has(projectId) ? cloneImages(sessionImages.get(projectId) ?? []) : sku.images,
  };
}

/** 默认写回商品草稿；勾了「仅用于本次出片」就只改本场覆盖。 */
export function applyPrepareEdit(projectId: string, draft: StudioDraft, fields: SkuEnrichment): StudioDraft {
  const selling = fields.selling_points.map((item) => item.trim()).filter(Boolean).slice(0, 5);
  if (draft.sessionOnly) {
    sessionImages.set(projectId, cloneImages(fields.images));
    return {
      ...draft,
      projectId,
      pain_point: fields.pain_point,
      selling_points: selling,
      usage_scenario: fields.usage_scenario,
      specs: fields.specs,
      offer: fields.offer,
    };
  }
  sessionImages.delete(projectId);
  writeSkuEnrichment(projectId, { ...fields, selling_points: selling });
  return {
    ...draft,
    projectId,
    pain_point: null,
    selling_points: null,
    usage_scenario: null,
    offer: null,
    specs: null,
  };
}

export function setPrepareSessionOnly(projectId: string, draft: StudioDraft, sessionOnly: boolean, fields: SkuEnrichment): StudioDraft {
  return applyPrepareEdit(projectId, { ...draft, projectId, sessionOnly }, fields);
}

const IMAGE_EXT = /\.(png|jpe?g|webp)$/i;

function imageMimeAllowed(type: string): boolean {
  return type === "image/png" || type === "image/jpeg" || type === "image/webp";
}

/** PNG / JPEG / JPG / WEBP，单张 ≤10MB。HEIC 先不收。 */
export function prepareImageRejection(file: { name: string; type: string; size: number }): string | null {
  const type = file.type.trim().toLowerCase();
  const name = file.name.trim();
  const extOk = IMAGE_EXT.test(name);
  const heic = type === "image/heic" || type === "image/heif" || /\.heic$/i.test(name) || /\.heif$/i.test(name);
  if (heic || (!imageMimeAllowed(type) && !(type === "" && extOk)) || (imageMimeAllowed(type) && name.includes(".") && !extOk)) {
    return "仅支持 PNG / JPEG / JPG / WEBP";
  }
  if (file.size > PREPARE_IMAGE_MAX_BYTES) return "单张不能超过 10MB";
  if (file.size <= 0) return "图片不能为空";
  return null;
}

export function prepareSubmitErrors(input: {
  imageCount: number;
  painPoint: string;
  sellingPoints: string[];
  usageScenario: string;
}): string[] {
  const errors: string[] = [];
  if (input.imageCount < 1) errors.push(PREPARE_REQUIRED_COPY.image);
  if (input.painPoint.trim().length < 2) errors.push(PREPARE_REQUIRED_COPY.pain);
  const points = input.sellingPoints.map((item) => item.trim()).filter(Boolean);
  if (points.length < 1 || points.length > 5) errors.push(PREPARE_REQUIRED_COPY.points);
  if (input.usageScenario.trim().length < 2) errors.push(PREPARE_REQUIRED_COPY.scene);
  return errors;
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
