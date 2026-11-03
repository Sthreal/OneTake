/** iter18 外壳：首页上手、图片广告、品牌空间、有机发布、工作室四步。
 *
 * 工作室只走 准备 → 审稿 → 提交渲染 → 交付。确认过闸后，渲染步提交与托管工作台
 * 相同的渲染任务。图片广告页的「另开工作室」是可选出口，不把选中的静图写进工作室草稿。
 */
import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

import { ApiError } from "../../shared/api/client";
import { listCharacters, type Character } from "../../shared/api/characterApi";
import { createProject, listProjects, updateProject } from "../../shared/api/projectApi";
import { getScript } from "../../shared/api/scriptApi";
import type { Project } from "../../features/input/types";
import type { ShellView, UrlView } from "../urlState";
import {
  GS_STEPS,
  IMAGE_AD_CELLS,
  IMAGE_AD_RATIOS,
  STUDIO_STEPS,
  clearSessionImages,
  PATH_CHANGED_HINT,
  PRESENTER_CLEAR_FAILED,
  TALKING_HEAD_LIBRARY_PRESENTER_REQUIRED,
  deliveryPresenterCheck,
  generatePresenterCheck,
  imageAdExportPayload,
  isStudioView,
  libraryPresenterStartError,
  talkingHeadStartError,
  markGsDone,
  nextStudioView,
  presenterById,
  projectCharacterSync,
  switchStudioPath,
  readBrands,
  readGsDone,
  readSkuEnrichment,
  readStudioDraft,
  resolveSelectedProduct,
  skuEnrichmentSummary,
  writeBrands,
  writeStudioDraft,
  type ImageAdRatio,
  type PresenterOption,
  type StudioCreationPath,
  type StudioDraft,
} from "./model";
import { PrepareStep } from "./PrepareStep";
import { ScriptReviewStep, useScriptGateGuard } from "./ScriptReviewStep";
import { hasReusableScript } from "./scriptGate";
import { ensureShellMainImage } from "./mainImagePrelude";
import {
  AudioSubtitleConfirmationRequiredError,
  confirmShellAudioSubtitle,
  enqueueShellRender,
  readShellRender,
  SHELL_RENDER_POLL_FAILURE_LIMIT,
  shellRenderProgressUnavailable,
  shellVoiceCopy,
  type ShellRenderView,
} from "./shellRender";
import "./shell.css";

export function ShellApp({
  view,
  projectId,
  onNavigate,
}: {
  view: ShellView;
  projectId: string | null;
  onNavigate: (view: UrlView, projectId?: string | null) => void;
}) {
  const [openGs, setOpenGs] = useState(2);
  const [gsDone, setGsDone] = useState<number[]>(() => readGsDone());
  const [draft, setDraft] = useState<StudioDraft>(() => readStudioDraft(projectId));
  const [brands, setBrands] = useState(() => readBrands());
  const [products, setProducts] = useState<Project[]>([]);
  const [productsError, setProductsError] = useState<string | null>(null);
  const [productsLoading, setProductsLoading] = useState(false);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [charactersLoading, setCharactersLoading] = useState(() => isStudioView(view));
  const [charactersError, setCharactersError] = useState<string | null>(null);
  const [castOpen, setCastOpen] = useState(false);
  const [imageCellId, setImageCellId] = useState<string>(IMAGE_AD_CELLS[0].id);
  const [imageRatio, setImageRatio] = useState<ImageAdRatio>("1:1");
  const [exportNote, setExportNote] = useState<string | null>(null);
  const [addingProduct, setAddingProduct] = useState(false);
  const [addingBrand, setAddingBrand] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const needsProducts = view === "brand" || view === "image" || view === "projects" || isStudioView(view);

  const reloadProducts = useCallback(async () => {
    setProductsLoading(true);
    try {
      setProducts(await listProjects(50));
      setProductsError(null);
    } catch (error) {
      const raw = error instanceof Error ? error.message : "";
      setProductsError(/fetch|network|load failed/i.test(raw) ? "暂时连不上商品库" : raw || "读取商品失败");
    } finally {
      setProductsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!needsProducts) return;
    void reloadProducts();
  }, [needsProducts, reloadProducts]);

  useEffect(() => {
    if (!projectId) return;
    setDraft((current) => {
      if (current.projectId === projectId) return current;
      clearSessionImages();
      return writeStudioDraft({
        ...current,
        projectId,
        pain_point: null,
        selling_points: null,
        usage_scenario: null,
        offer: null,
      });
    });
  }, [projectId]);

  const reloadCharacters = useCallback(async () => {
    setCharactersLoading(true);
    setCharactersError(null);
    try {
      const list = await listCharacters();
      setCharacters(list.characters);
    } catch (error) {
      setCharacters([]);
      setCharactersError(error instanceof Error && error.message ? error.message : "暂时无法读取出镜人库");
    } finally {
      setCharactersLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!isStudioView(view)) return;
    void reloadCharacters();
  }, [view, reloadCharacters]);

  function patchDraft(partial: Partial<StudioDraft>) {
    setDraft((current) => writeStudioDraft({ ...current, ...partial }));
  }

  function goGs(id: number, dest: UrlView) {
    setGsDone(markGsDone(id));
    onNavigate(dest, dest === "prepare" ? draft.projectId : null);
  }

  const studioProduct = resolveSelectedProduct(projectId, products);
  const presenter = presenterById(draft.presenterId, characters);
  const explicitImageProduct = resolveSelectedProduct(draft.projectId, products);
  const imageName = (explicitImageProduct ?? products[0])?.product_name ?? "春季护肤精华液";

  return (
    <div className="ot" data-view={view}>
      {isStudioView(view) ? (
        <StudioRail projectId={projectId} onNavigate={onNavigate} />
      ) : (
        <Sidebar view={view} recentProjectId={draft.projectId} onNavigate={onNavigate} />
      )}
      <div className="ot-main">
        {view === "home" ? (
          <Home
            openGs={openGs}
            done={gsDone.length}
            recentProjectId={draft.projectId}
            onOpen={setOpenGs}
            onGo={goGs}
            onNavigate={onNavigate}
          />
        ) : null}
        {view === "image" ? (
          <ImageAds
            productName={imageName}
            ratio={imageRatio}
            cellId={imageCellId}
            exportNote={exportNote}
            onRatio={setImageRatio}
            onCell={setImageCellId}
            onExport={() => {
              const cell = IMAGE_AD_CELLS.find((item) => item.id === imageCellId) ?? IMAGE_AD_CELLS[0];
              const payload = imageAdExportPayload({ caption: cell.caption, ratio: imageRatio, productName: imageName });
              downloadText(payload.filename, payload.text);
              setExportNote(`已下载预览说明（不是图片）：${cell.caption}`);
            }}
            onNavigate={(next) => onNavigate(next, next === "prepare" ? explicitImageProduct?.project_id ?? null : null)}
          />
        ) : null}
        {view === "brand" ? (
          <BrandSpace
            brands={brands}
            products={products}
            loading={productsLoading}
            error={productsError ?? formError}
            addingBrand={addingBrand}
            addingProduct={addingProduct}
            saving={saving}
            onToggleBrand={() => { setAddingBrand((open) => !open); setFormError(null); }}
            onToggleProduct={() => { setAddingProduct((open) => !open); setFormError(null); }}
            onAddBrand={(name) => {
              const next = writeBrands([...brands, { id: `brand-${Date.now()}`, name }]);
              setBrands(next);
              setAddingBrand(false);
            }}
            onAddProduct={async (name, note) => {
              setSaving(true);
              setFormError(null);
              try {
                await createProject({ productName: name, productNote: note || undefined });
                setAddingProduct(false);
                await reloadProducts();
              } catch (error) {
                setFormError(error instanceof Error ? error.message : "添加商品失败");
              } finally {
                setSaving(false);
              }
            }}
            onNavigate={onNavigate}
          />
        ) : null}
        {view === "projects" ? (
          <Projects
            products={products}
            loading={productsLoading}
            error={productsError}
            recentProjectId={draft.projectId}
            onNavigate={onNavigate}
          />
        ) : null}
        {view === "connect" ? <Connect onNavigate={onNavigate} /> : null}
        {isStudioView(view) ? (
          <Studio
            view={view}
            draft={draft}
            requestedProjectId={projectId}
            loading={productsLoading}
            error={productsError}
            product={studioProduct}
            presenter={presenter}
            characters={characters}
            charactersLoading={charactersLoading}
            charactersError={charactersError}
            castOpen={castOpen}
            onCastOpen={setCastOpen}
            onReloadCharacters={() => { void reloadCharacters(); }}
            onDraft={patchDraft}
            onNavigate={onNavigate}
          />
        ) : null}
      </div>
    </div>
  );
}

function Logo({ size = 11 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path d="M8 5.14v13.72L19 12 8 5.14z" fill="currentColor" />
    </svg>
  );
}

function Ico({ children, size = 18, className }: { children: ReactNode; size?: number; className?: string }) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  );
}

function Sidebar({
  view,
  recentProjectId,
  onNavigate,
}: {
  view: ShellView;
  recentProjectId: string | null;
  onNavigate: (view: UrlView, projectId?: string | null) => void;
}) {
  return (
    <aside className="ot-side" aria-label="主导航">
      <button type="button" className="ot-brand" onClick={() => onNavigate("home")}>
        <span className="ot-logo"><Logo /></span>
        <span className="ot-name">OneTake</span>
      </button>
      <nav className="ot-nav">
        <button type="button" className={"ot-item" + (view === "home" ? " on" : "")} onClick={() => onNavigate("home")}>
          <Ico><path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1v-9.5z" /></Ico>
          首页
        </button>
        <button type="button" className={"ot-item" + (view === "projects" ? " on" : "")} onClick={() => onNavigate("projects")}>
          <Ico><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" /></Ico>
          项目
        </button>
        <button type="button" className={"ot-item" + (view === "brand" ? " on" : "")} onClick={() => onNavigate("brand")}>
          <Ico><path d="M12 2 2 7l10 5 10-5-10-5z" /><path d="M2 17l10 5 10-5" /><path d="M2 12l10 5 10-5" /></Ico>
          品牌空间
        </button>
      </nav>
      <div className="ot-group">
        <div className="ot-group-label">创作</div>
        <button type="button" className="ot-tool" onClick={() => onNavigate("prepare", recentProjectId)}>
          <Ico><rect x="2" y="6" width="20" height="12" rx="2" /><path d="M10 10l5 2-5 2v-4z" /></Ico>
          快速出片
        </button>
        <button type="button" className={"ot-tool" + (view === "image" ? " on" : "")} onClick={() => onNavigate("image")}>
          <Ico><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><path d="M21 15l-5-5L5 21" /></Ico>
          图片广告
        </button>
      </div>
      <div className="ot-group">
        <div className="ot-group-label">有机增长</div>
        <button type="button" className={"ot-tool" + (view === "connect" ? " on" : "")} onClick={() => onNavigate("connect")}>
          <Ico><path d="M4 12c2-4 6-6 8-6s6 2 8 6c-2 4-6 6-8 6s-6-2-8-6z" /><circle cx="12" cy="12" r="2.5" /></Ico>
          有机种草
        </button>
        <button type="button" className={"ot-tool" + (view === "connect" ? " on" : "")} onClick={() => onNavigate("connect")}>
          <Ico><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M7 9h10M7 13h6" /></Ico>
          社媒发布
        </button>
      </div>
      <div className="ot-spacer" />
      <div className="ot-user">
        <div className="ot-avatar">S</div>
        <div>
          <div className="ot-user-name">Sthreal</div>
          <div className="ot-user-mail">示意 · 未接计价</div>
        </div>
      </div>
    </aside>
  );
}

function StudioRail({
  projectId,
  onNavigate,
}: {
  projectId: string | null;
  onNavigate: (view: UrlView, projectId?: string | null) => void;
}) {
  return (
    <aside className="ot-rail" aria-label="工作室导航">
      <button type="button" className="ot-rail-brand" aria-label="返回首页" onClick={() => onNavigate("home")}>
        <Logo size={12} />
      </button>
      <button type="button" className="ot-rail-item on" onClick={() => onNavigate("prepare", projectId)}>
        <Ico><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></Ico>
        <span className="ot-tip">制作</span>
      </button>
      <button type="button" className="ot-rail-item" onClick={() => onNavigate("projects")}>
        <Ico><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" /></Ico>
        <span className="ot-tip">项目</span>
      </button>
      <button type="button" className="ot-rail-item" onClick={() => onNavigate("brand")}>
        <Ico><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z" /><line x1="7" y1="7" x2="7.01" y2="7" /></Ico>
        <span className="ot-tip">品牌空间</span>
      </button>
      <div className="ot-credits" aria-label="示意，未接计价"><i /><span>示意</span></div>
    </aside>
  );
}

function Home({
  openGs,
  done,
  recentProjectId,
  onOpen,
  onGo,
  onNavigate,
}: {
  openGs: number;
  done: number;
  recentProjectId: string | null;
  onOpen: (id: number) => void;
  onGo: (id: number, dest: UrlView) => void;
  onNavigate: (view: UrlView, projectId?: string | null) => void;
}) {
  return (
    <>
      <header className="ot-top">
        <h1 className="ot-title">首页</h1>
        <button type="button" className="ot-btn ot-btn-primary" onClick={() => onNavigate("prepare", recentProjectId)}>
          <Ico size={14}><path d="M12 5v14M5 12h14" /></Ico>
          开始出片
        </button>
      </header>
      <div className="ot-body">
        <section className="ot-gs" aria-label="开始上手">
          <div className="ot-gs-head">
            <div className="ot-gs-title">开始上手</div>
            <div className="ot-gs-prog">{done} / 4 已完成</div>
          </div>
          <div className="ot-gs-steps">
            {GS_STEPS.map((step) => (
              <div key={step.id} className={"ot-gs-step" + (openGs === step.id ? " open" : "")}>
                <button type="button" className="ot-gs-h" aria-expanded={openGs === step.id} onClick={() => onOpen(step.id)}>
                  <span className="ot-gs-num" aria-hidden="true">{step.id}</span>
                  <span className="ot-gs-name">
                    {step.name}
                    {step.optional ? <span className="ot-optional">可选</span> : null}
                  </span>
                  <Ico size={14} className="ot-gs-chev"><path d="M6 9l6 6 6-6" /></Ico>
                </button>
                <div className="ot-gs-body">
                  <div className="ot-gs-split">
                    <div className="ot-gs-left">
                      <div className="ot-gs-left-title">
                        {step.title}
                        {step.optional ? <span className="ot-optional">可选</span> : null}
                      </div>
                      <p className="ot-gs-desc">{step.description}</p>
                      <div className="ot-cta-row">
                        <button type="button" className={"ot-btn ot-btn-sm " + (step.dest === "prepare" ? "ot-btn-primary" : "ot-btn-secondary")} data-entry={`gs-${step.dest}`} onClick={() => onGo(step.id, step.dest)}>
                          {step.cta}
                        </button>
                        {step.optional ? (
                          <button type="button" className="ot-btn ot-btn-secondary ot-btn-sm" onClick={() => onNavigate("home")}>跳过</button>
                        ) : null}
                      </div>
                    </div>
                    <div className="ot-gs-right" aria-hidden="true">
                      <GsMock id={step.id} />
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
        <h2 className="ot-section">创作工具</h2>
        <div className="ot-tools" role="region" aria-label="创作工具">
          <ToolCard badge="主路径" name="快速出片" mode="模式 · 工作室" desc="选商品、审稿过闸，确认后提交渲染。不必打开导演页，也不经过图片广告。" onClick={() => onNavigate("prepare", recentProjectId)} icon={<Ico size={20}><rect x="2" y="6" width="20" height="12" rx="2" /><path d="M10 10l5 2-5 2v-4z" /></Ico>} />
          <ToolCard name="图片广告" mode="模式 · 图片" desc="演示预览：九宫格是占位，不是真实出图。与视频工作室解耦。" onClick={() => onNavigate("image")} icon={<Ico size={20}><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><path d="M21 15l-5-5L5 21" /></Ico>} />
          <ToolCard name="品牌空间" mode="模式 · 素材库" desc="管理品牌 DNA、商品主图与卖点，供工作室与图片广告复用。" onClick={() => onNavigate("brand")} icon={<Ico size={20}><path d="M12 2 2 7l10 5 10-5-10-5z" /><path d="M2 17l10 5 10-5" /><path d="M2 12l10 5 10-5" /></Ico>} />
          <ToolCard name="有机种草" mode="模式 · 发布" desc="入口保留。抖音 / 小红书有机发布尚未接线。" onClick={() => onNavigate("connect")} icon={<Ico size={20}><path d="M4 12c2-4 6-6 8-6s6 2 8 6c-2 4-6 6-8 6s-6-2-8-6z" /><circle cx="12" cy="12" r="2.5" /></Ico>} />
        </div>
        <div className="ot-advanced">
          <span className="ot-section">高级</span>
          <button type="button" className="ot-btn ot-btn-secondary ot-btn-sm" onClick={() => onNavigate("director", recentProjectId)}>高级 · 导演模式</button>
          <button type="button" className="ot-btn ot-btn-secondary ot-btn-sm" onClick={() => onNavigate("workbench", recentProjectId)}>高级 · 托管工作台</button>
        </div>
        <h2 className="ot-section">最近动态</h2>
        <div className="ot-wn">
          <article className="ot-wn-card"><div className="ot-wn-thumb" /><div className="ot-wn-title">图片广告独立成能力</div><div className="ot-wn-desc">静图广告与工作室出片解耦；出片不必先出图。</div></article>
          <article className="ot-wn-card"><div className="ot-wn-thumb" /><div className="ot-wn-title">确认后提交渲染</div><div className="ot-wn-desc">过闸后提交渲染。没有成片地址时不提供预览，本页也不报价。</div></article>
          <article className="ot-wn-card"><div className="ot-wn-thumb" /><div className="ot-wn-title">聚焦有机种草</div><div className="ot-wn-desc">入口在，发布还没接线。不做 Meta 投放主路径。</div></article>
        </div>
      </div>
    </>
  );
}

function GsMock({ id }: { id: number }) {
  if (id === 2) {
    return (
      <div className="ot-mock">
        <div className="ot-mock-frame" />
        <div className="ot-mock-meta"><span>1:1</span><span>图片广告</span><span>春季护肤精华液</span></div>
      </div>
    );
  }
  if (id === 3) {
    return (
      <div className="ot-mock-studio">
        <div className="ot-mock-rail"><i className="on" /><i /><i /></div>
        <div className="ot-mock-main">
          <div className="ot-mock-label">准备素材</div>
          <div className="ot-mock-drop"><b /><span>选用已有商品<br />与出镜人库</span></div>
        </div>
      </div>
    );
  }
  if (id === 4) {
    return (
      <div className="ot-mock-publish">
        <div className="ot-mock-row"><span className="ot-mock-chip">抖音</span><span className="ot-mock-chip ot-xhs">小红书</span></div>
        <span className="ot-mock-chip ghost">可选 · 非必需</span>
      </div>
    );
  }
  return (
    <div className="ot-mock">
      <div className="ot-mock-product">
        <div className="ot-mock-thumb" />
        <div>
          <div className="ot-mock-name">春季护肤精华液</div>
          <div className="ot-mock-line" />
          <div className="ot-mock-line s" />
        </div>
      </div>
      <div className="ot-mock-upload"><span>+ 上传商品主图</span></div>
    </div>
  );
}

function ToolCard({ badge, name, desc, mode, icon, onClick }: { badge?: string; name: string; desc: string; mode: string; icon: ReactNode; onClick: () => void }) {
  return (
    <button type="button" className="ot-toolcard" onClick={onClick}>
      {badge ? <span className="ot-badge">{badge}</span> : null}
      <span className="ot-art">{icon}</span>
      <span className="ot-toolbody">
        <span className="ot-tool-name">{name}</span>
        <span className="ot-tool-desc">{desc}</span>
        <span className="ot-mode">{mode}</span>
      </span>
    </button>
  );
}

function ImageAds({
  productName,
  ratio,
  cellId,
  exportNote,
  onRatio,
  onCell,
  onExport,
  onNavigate,
}: {
  productName: string;
  ratio: ImageAdRatio;
  cellId: string;
  exportNote: string | null;
  onRatio: (ratio: ImageAdRatio) => void;
  onCell: (id: string) => void;
  onExport: () => void;
  onNavigate: (view: UrlView) => void;
}) {
  return (
    <>
      <header className="ot-top">
        <h1 className="ot-title">图片广告</h1>
        <div className="ot-actions">
          <button type="button" className="ot-btn ot-btn-secondary" onClick={() => onNavigate("home")}>返回首页</button>
          <button type="button" className="ot-btn ot-btn-primary" onClick={onExport}>下载预览说明（演示）</button>
        </div>
      </header>
      <div className="ot-body">
        <div className="ot-image-layout">
          <section className="ot-card">
            <h2>商品 → 图片广告预览</h2>
            <p>演示预览：左侧 3×3 九宫格是占位，不会真实出图。与工作室视频流程解耦，不强制进台。</p>
            <div className="ot-specs">
              {IMAGE_AD_RATIOS.map((item) => (
                <button key={item} type="button" className={item === ratio ? "on" : ""} aria-pressed={item === ratio} onClick={() => onRatio(item)}>{item}</button>
              ))}
              <span className="ot-spec">图片广告</span>
              <span className="ot-spec">{productName}</span>
            </div>
            <div className="ot-nine" role="list" aria-label="图片广告九宫格">
              {IMAGE_AD_CELLS.map((cell) => (
                <div key={cell.id} role="listitem">
                  <button type="button" className={"ot-cell" + (cell.id === cellId ? " on" : "")} aria-pressed={cell.id === cellId} aria-label={`图 ${cell.id} ${cell.caption}`} onClick={() => onCell(cell.id)}>
                    <span className={"ot-cell-bg " + cell.tone} />
                    <span className="ot-cell-tag">图 {cell.id}</span>
                    <span className="ot-cell-cap">{cell.caption}</span>
                  </button>
                </div>
              ))}
            </div>
            <div className="ot-hint">演示预览 · 九宫格是占位 · 点击只是选中 · 不真实出图</div>
          </section>
          <section className="ot-card">
            <h2>只有预览，不能当成交图</h2>
            <p>下载的是一段文字说明，不是图片文件。工作室出片另走「快速出片」，不必先过本页。</p>
            <div className="ot-stack">
              <button type="button" className="ot-btn ot-btn-primary" data-entry="image-export-main" onClick={onExport}>导出预览说明（演示）</button>
              <button type="button" className="ot-btn ot-btn-secondary" onClick={() => onNavigate("brand")}>换商品</button>
              <button type="button" className="ot-btn ot-btn-secondary" onClick={() => onNavigate("connect")}>发布入口（未接线）</button>
              <button type="button" className="ot-btn ot-btn-secondary" data-entry="image-prepare-optional" onClick={() => onNavigate("prepare")}>可选 · 另开工作室出片</button>
            </div>
            <div className="ot-note">演示数据：{productName} · 本页无真实生成 · 工作室四步不依赖本页结果。</div>
            {exportNote ? <div className="ot-status" role="status">{exportNote}</div> : null}
          </section>
        </div>
      </div>
    </>
  );
}

function BrandSpace({
  brands,
  products,
  loading,
  error,
  addingBrand,
  addingProduct,
  saving,
  onToggleBrand,
  onToggleProduct,
  onAddBrand,
  onAddProduct,
  onNavigate,
}: {
  brands: { id: string; name: string }[];
  products: Project[];
  loading: boolean;
  error: string | null;
  addingBrand: boolean;
  addingProduct: boolean;
  saving: boolean;
  onToggleBrand: () => void;
  onToggleProduct: () => void;
  onAddBrand: (name: string) => void;
  onAddProduct: (name: string, note: string) => Promise<void>;
  onNavigate: (view: UrlView, projectId?: string | null) => void;
}) {
  const [openProductId, setOpenProductId] = useState<string | null>(null);
  const openProduct = products.find((item) => item.project_id === openProductId) ?? null;
  return (
    <>
      <header className="ot-top">
        <h1 className="ot-title">品牌空间</h1>
        <button type="button" className="ot-btn ot-btn-primary" onClick={() => onNavigate("prepare", products[0]?.project_id ?? null)}>用此品牌出片</button>
      </header>
      <div className="ot-body">
        <section className="ot-brand-block">
          <h2 className="ot-brand-h">品牌</h2>
          <div className="ot-brand-grid">
            <button type="button" className="ot-brand-card add" onClick={onToggleBrand}>
              <span className="ot-plus">+</span>
              <span className="ot-add-title">添加品牌</span>
              <span className="ot-add-sub">含 Logo、色板、语气等</span>
            </button>
            {addingBrand ? <NameForm label="品牌名称" submitLabel="保存品牌" onSubmit={onAddBrand} /> : null}
            {brands.map((brand) => (
              <article key={brand.id} className="ot-brand-card">
                <div className="ot-brand-thumb checker" />
                <div className="ot-brand-info">
                  <div className="ot-brand-name">{brand.name}</div>
                  <div className="ot-brand-status"><i className="ot-dot" />品牌 DNA 记在本机</div>
                </div>
              </article>
            ))}
          </div>
        </section>
        <section className="ot-brand-block">
          <h2 className="ot-brand-h">商品</h2>
          <p className="ot-hint">商品在这里添加。准备步只选用已有商品，不能在准备步从零新建。</p>
          {openProduct ? (
            <ProductDraftDetail
              product={openProduct}
              onBack={() => setOpenProductId(null)}
              onPrepare={() => onNavigate("prepare", openProduct.project_id)}
            />
          ) : (
            <div className="ot-brand-grid">
              <button type="button" className="ot-brand-card add" onClick={onToggleProduct}>
                <span className="ot-plus">+</span>
                <span className="ot-add-title">添加商品</span>
                <span className="ot-add-sub">含实物与数字商品</span>
              </button>
              {addingProduct ? (
                <ProductForm saving={saving} onSubmit={onAddProduct} />
              ) : null}
              {products.map((product) => {
                const sku = readSkuEnrichment(product.project_id);
                const thumb = sku.images[0]?.preview;
                return (
                  <button key={product.project_id} type="button" className="ot-brand-card" onClick={() => setOpenProductId(product.project_id)}>
                    <div className="ot-brand-thumb">
                      {thumb ? <img src={thumb} alt="" /> : null}
                    </div>
                    <div className="ot-brand-info">
                      <div className="ot-brand-name">{product.product_name}</div>
                      <div className="ot-brand-summary">{skuEnrichmentSummary(sku)}</div>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
          {loading ? <p className="ot-hint">正在读取商品…</p> : null}
          {error ? <p className="ot-error">{error}</p> : null}
        </section>
      </div>
    </>
  );
}

function ProductDraftDetail({
  product,
  onBack,
  onPrepare,
}: {
  product: Project;
  onBack: () => void;
  onPrepare: () => void;
}) {
  const sku = readSkuEnrichment(product.project_id);
  const points = sku.selling_points.map((item) => item.trim()).filter(Boolean);
  return (
    <section className="ot-panel ot-sku-detail" aria-label="商品详情">
      <div className="ot-label-row">
        <h3>{product.product_name}</h3>
        <button type="button" className="ot-link" onClick={onBack}>返回商品</button>
      </div>
      <ul className="ot-sku-facts">
        <li><b>痛点</b> {sku.pain_point.trim() || "未填写"}</li>
        <li><b>卖点</b> {points.length > 0 ? points.join("、") : "未填写"}</li>
        <li><b>使用场景</b> {sku.usage_scenario.trim() || "未填写"}</li>
        {sku.offer.trim() ? <li><b>优惠活动</b> {sku.offer.trim()}</li> : null}
      </ul>
      {sku.images.length > 0 ? (
        <div className="ot-image-grid">
          {sku.images.map((image) => (
            <div key={image.id} className="ot-image-tile">
              <img src={image.preview} alt={image.name} />
            </div>
          ))}
        </div>
      ) : (
        <p className="ot-hint">还没有商品图</p>
      )}
      <div className="ot-sku-actions">
        <button type="button" className="ot-btn ot-btn-primary" onClick={onPrepare}>继续准备出片</button>
      </div>
    </section>
  );
}

function NameForm({ label, submitLabel, onSubmit }: { label: string; submitLabel: string; onSubmit: (name: string) => void }) {
  const [name, setName] = useState("");
  return (
    <form className="ot-form" onSubmit={(event) => { event.preventDefault(); if (name.trim()) onSubmit(name.trim()); }}>
      <label className="ot-field">{label}</label>
      <input className="ot-input" value={name} onChange={(event) => setName(event.target.value)} />
      <button type="submit" className="ot-btn ot-btn-primary ot-btn-sm" disabled={!name.trim()}>{submitLabel}</button>
    </form>
  );
}

function ProductForm({ saving, onSubmit }: { saving: boolean; onSubmit: (name: string, note: string) => Promise<void> }) {
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!name.trim() || saving) return;
    await onSubmit(name.trim(), note.trim());
  }
  return (
    <form className="ot-form" onSubmit={(event) => void submit(event)}>
      <label className="ot-field" htmlFor="product-name">商品名称</label>
      <input id="product-name" className="ot-input" value={name} onChange={(event) => setName(event.target.value)} />
      <label className="ot-field" htmlFor="product-note">卖点备注</label>
      <input id="product-note" className="ot-input" value={note} onChange={(event) => setNote(event.target.value)} />
      <button type="submit" className="ot-btn ot-btn-primary ot-btn-sm" disabled={!name.trim() || saving}>{saving ? "保存中…" : "保存商品"}</button>
    </form>
  );
}

function Projects({
  products,
  loading,
  error,
  recentProjectId,
  onNavigate,
}: {
  products: Project[];
  loading: boolean;
  error: string | null;
  recentProjectId: string | null;
  onNavigate: (view: UrlView, projectId?: string | null) => void;
}) {
  return (
    <>
      <header className="ot-top">
        <h1 className="ot-title">项目</h1>
        <button type="button" className="ot-btn ot-btn-primary" onClick={() => onNavigate("prepare", recentProjectId)}>
          <Ico size={14}><path d="M12 5v14M5 12h14" /></Ico>
          新建
        </button>
      </header>
      <div className="ot-body" style={{ display: "flex", flexDirection: "column" }}>
        <div className="ot-filters"><span className="ot-pill">全部商品</span><span className="ot-pill">全部规格</span></div>
        {error ? <p className="ot-error">{error}</p> : null}
        {loading ? <p className="ot-hint">正在读取项目…</p> : null}
        {!loading && products.length === 0 ? (
          <div className="ot-empty">
            <div className="ot-ghosts" aria-hidden="true"><div className="ot-ghost" /><div className="ot-ghost" /><div className="ot-ghost" /><div className="ot-ghost" /></div>
            <div className="strong">把第一个想法做成成片</div>
            <p>生成后的项目会出现在这里 · 点右上角「新建」开始</p>
          </div>
        ) : (
          <ul className="ot-proj-list">
            {products.map((product) => (
              <li key={product.project_id} className="ot-proj">
                <div>
                  <b>{product.product_name}</b>
                  <small>{product.project_id}</small>
                </div>
                <div className="ot-proj-actions">
                  <button type="button" className="ot-btn ot-btn-primary ot-btn-sm" onClick={() => onNavigate("prepare", product.project_id)}>快速出片</button>
                  <button type="button" className="ot-btn ot-btn-secondary ot-btn-sm" onClick={() => onNavigate("director", product.project_id)}>高级 · 导演模式</button>
                  <button type="button" className="ot-btn ot-btn-secondary ot-btn-sm" onClick={() => onNavigate("workbench", product.project_id)}>高级 · 托管工作台</button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}

function Connect({ onNavigate }: { onNavigate: (view: UrlView, projectId?: string | null) => void }) {
  return (
    <>
      <header className="ot-top">
        <h1 className="ot-title">发布广告 <span className="ot-optional">可选</span></h1>
        <button type="button" className="ot-btn ot-btn-secondary" onClick={() => onNavigate("home")}>跳过，回首页</button>
      </header>
      <div className="ot-body">
        <div className="ot-placeholder">
          <h2>有机发布尚未接线</h2>
          <p>这个入口保留着，但抖音 / 小红书都还没接上。按钮点不了，也不会把成片发出去。没有 Meta，也没有付费投放主路径。</p>
          <div className="ot-channels">
            <span className="ot-channel">抖音 · 未接入</span>
            <span className="ot-channel">小红书 · 未接入</span>
          </div>
          <div className="ot-cta-row" style={{ justifyContent: "center" }}>
            <button type="button" className="ot-btn ot-btn-primary" disabled>连接并发布（尚未接入）</button>
            <button type="button" className="ot-btn ot-btn-secondary" onClick={() => onNavigate("home")}>跳过</button>
          </div>
        </div>
      </div>
    </>
  );
}

function Studio({
  view,
  draft,
  requestedProjectId,
  loading,
  error,
  product,
  presenter,
  characters,
  charactersLoading,
  charactersError,
  castOpen,
  onCastOpen,
  onReloadCharacters,
  onDraft,
  onNavigate,
}: {
  view: ShellView;
  draft: StudioDraft;
  requestedProjectId: string | null;
  loading: boolean;
  error: string | null;
  product: Project | null;
  presenter: PresenterOption;
  characters: Character[];
  charactersLoading: boolean;
  charactersError: string | null;
  castOpen: boolean;
  onCastOpen: (open: boolean) => void;
  onReloadCharacters: () => void;
  onDraft: (partial: Partial<StudioDraft>) => void;
  onNavigate: (view: UrlView, projectId?: string | null) => void;
}) {
  const stepIndex = STUDIO_STEPS.findIndex((step) => step.view === view);
  const productId = product?.project_id ?? null;
  const [presenterSyncing, setPresenterSyncing] = useState(false);
  const [presenterSyncError, setPresenterSyncError] = useState<string | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const [pathHint, setPathHint] = useState<string | null>(null);
  const pathHintRequest = useRef(0);
  const startInFlight = useRef(false);

  useEffect(() => {
    // 回到准备步时清掉残留。正在执行的 start 不在这里打断。
    if (view !== "prepare" || startInFlight.current) return;
    setPresenterSyncing(false);
  }, [view]);

  useEffect(() => {
    return () => {
      pathHintRequest.current += 1;
    };
  }, []);

  async function changePath(next: StudioCreationPath) {
    if (next === draft.path) return;
    onDraft(switchStudioPath(draft, next));
    const request = pathHintRequest.current + 1;
    pathHintRequest.current = request;
    const projectKey = product?.project_id ?? null;
    if (!projectKey) {
      setPathHint(null);
      return;
    }
    try {
      const state = await getScript(projectKey);
      if (pathHintRequest.current !== request) return;
      setPathHint(hasReusableScript(state) ? PATH_CHANGED_HINT : null);
    } catch {
      if (pathHintRequest.current !== request) return;
      setPathHint(PATH_CHANGED_HINT);
    }
  }

  const advance = () => {
    const next = nextStudioView(view);
    if (!next) return;
    if (view === "prepare" && product) onDraft({ projectId: product.project_id });
    onNavigate(next, product?.project_id ?? null);
  };

  async function syncPresenter(projectKey: string): Promise<boolean> {
    const sync = projectCharacterSync(draft.presenterId);
    if (!sync) {
      setPresenterSyncError(null);
      return true;
    }
    setPresenterSyncing(true);
    setPresenterSyncError(null);
    try {
      await updateProject(projectKey, { characterId: sync.characterId });
      return true;
    } catch {
      setPresenterSyncError(
        sync.characterId === null ? PRESENTER_CLEAR_FAILED : "出镜人没能写入项目，已停止。不会改用预制出镜人。",
      );
      return false;
    } finally {
      setPresenterSyncing(false);
    }
  }

  async function startProduction() {
    if (!product || presenterSyncing || startInFlight.current) return;
    startInFlight.current = true;
    setPresenterSyncing(true);
    setStartError(null);
    setPresenterSyncError(null);
    try {
      if (charactersLoading || charactersError) {
        setStartError(charactersError ? `出镜人库加载失败：${charactersError}` : "正在读取出镜人库，请稍后再开始。");
        return;
      }
      const presenterError = libraryPresenterStartError(draft, characters);
      if (presenterError) {
        setStartError(presenterError);
        if (draft.path === "talking_head") onCastOpen(true);
        return;
      }
      try {
        await ensureShellMainImage(product.project_id);
      } catch (error) {
        setStartError(error instanceof Error && error.message ? error.message : "主图校验失败");
        return;
      }
      const ok = await syncPresenter(product.project_id);
      if (!ok) return;
      onDraft({ projectId: product.project_id });
      onNavigate("review", product.project_id);
    } finally {
      // Studio 跨准备/审稿不卸载。成功跳转前也要清掉，否则回准备步按钮一直 disabled，点击被静默吃掉。
      startInFlight.current = false;
      setPresenterSyncing(false);
    }
  }

  return (
    <div className="ot-studio">
      <header className="ot-topbar">
        <div className="ot-topbar-left">
          <button type="button" className="ot-back" onClick={() => onNavigate("home")}>← 首页</button>
          <div className="ot-stepper" aria-label="工作室步骤">
            {STUDIO_STEPS.map((step, index) => (
              <span key={step.view} style={{ display: "contents" }}>
                {index > 0 ? <span className="ot-step-sep" /> : null}
                <button
                  type="button"
                  className={"ot-step" + (index === stepIndex ? " current" : index < stepIndex ? " done" : "")}
                  disabled={index > stepIndex}
                  onClick={() => onNavigate(step.view, productId)}
                >
                  <span className="ot-step-no">{index < stepIndex ? "✓" : index + 1}</span>
                  {step.label}
                </button>
              </span>
            ))}
          </div>
        </div>
        <div className="ot-meta">{product ? product.project_id : "新项目"}</div>
      </header>
      {view === "prepare" ? (
        <PrepareStep
          draft={draft}
          requestedProjectId={requestedProjectId}
          loading={loading}
          error={error}
          product={product}
          presenter={presenter}
          characters={characters}
          charactersLoading={charactersLoading}
          charactersError={charactersError}
          castOpen={castOpen}
          onCastOpen={onCastOpen}
          onReloadCharacters={onReloadCharacters}
          onDraft={onDraft}
          onPath={(path) => {
            if (path === "talking_head" && !draft.presenterId) onCastOpen(true);
            void changePath(path);
          }}
          pathHint={pathHint}
          onBrand={() => onNavigate("brand")}
          onCharacters={() => onNavigate("characters")}
          onStart={() => { void startProduction(); }}
          syncing={presenterSyncing}
          syncError={presenterSyncError ?? startError}
        />
      ) : null}
      {view === "review" ? (
        <ScriptReviewStep
          product={product}
          presenter={presenter}
          draft={draft}
          onAdvance={advance}
          onBackToPrepare={() => onNavigate("prepare", productId)}
          pathHint={pathHint}
          onDismissPathHint={() => setPathHint(null)}
        />
      ) : null}
      {view === "generate" ? (
        <Generate
          product={product}
          presenter={presenter}
          draft={draft}
          onNext={advance}
          onReview={() => onNavigate("review", productId)}
          onPrepare={() => onNavigate("prepare", productId)}
        />
      ) : null}
      {view === "delivery" ? (
        <Delivery product={product} presenter={presenter} draft={draft} onNavigate={onNavigate} />
      ) : null}
    </div>
  );
}


const SUBMITTING_RENDER: ShellRenderView = {
  phase: "queued",
  headline: "排队中",
  detail: "正在提交与托管工作台相同的渲染任务。",
  playableUrl: null,
  mockReady: false,
  errorCode: null,
};

interface ManualAudioSubtitle {
  reason: string;
  voiceDuration: number | null;
  subtitleSegments: { text: string }[];
}

function useShellRender(projectId: string | null) {
  const [view, setView] = useState<ShellRenderView>({
    phase: "idle",
    headline: "尚未提交渲染",
    detail: "尚未提交渲染。生成页需要你明确确认后才会提交。",
    playableUrl: null,
    mockReady: false,
    errorCode: null,
  });
  const [busy, setBusy] = useState(false);
  const [reading, setReading] = useState(Boolean(projectId));
  const [manualAudioSubtitle, setManualAudioSubtitle] = useState<ManualAudioSubtitle | null>(null);
  const pollFailures = useRef(0);

  const submit = useCallback(async (force = false) => {
    if (!projectId) return;
    setBusy(true);
    setManualAudioSubtitle(null);
    try {
      setView(await enqueueShellRender(projectId, undefined, { force }));
    } catch (error) {
      if (error instanceof AudioSubtitleConfirmationRequiredError) {
        setManualAudioSubtitle({
          reason: error.reason,
          voiceDuration: error.voice.duration_seconds,
          subtitleSegments: error.subtitle.segments,
        });
        setView({
          phase: "idle",
          headline: "尚未提交渲染",
          detail: "配音与字幕已生成，等待你确认后再提交。",
          playableUrl: null,
          mockReady: false,
          errorCode: error.code,
        });
        return;
      }
      const code = error instanceof ApiError ? error.code : null;
      const message = error instanceof Error && error.message ? error.message : "渲染提交失败";
      setView({
        phase: "failed",
        headline: "失败可重试",
        detail: code === "COST_APPROVAL_REQUIRED" ? `${message} 费用闸没有放行，不能当成片。` : message,
        playableUrl: null,
        mockReady: false,
        errorCode: code,
      });
    } finally {
      setBusy(false);
    }
  }, [projectId]);

  const refresh = useCallback(async () => {
    if (!projectId) return;
    setReading(true);
    try {
      const next = await readShellRender(projectId);
      pollFailures.current = 0;
      setView(next);
    } catch {
      setView(shellRenderProgressUnavailable(pollFailures.current || 1));
    } finally {
      setReading(false);
    }
  }, [projectId]);

  useEffect(() => {
    pollFailures.current = 0;
    setManualAudioSubtitle(null);
    setView({
      phase: "idle",
      headline: "尚未提交渲染",
      detail: "尚未提交渲染。生成页需要你明确确认后才会提交。",
      playableUrl: null,
      mockReady: false,
      errorCode: null,
    });
    setReading(Boolean(projectId));
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!projectId || view.phase !== "queued") return;
    let cancelled = false;
    const timer = window.setInterval(() => {
      void readShellRender(projectId)
        .then((next) => {
          if (cancelled) return;
          pollFailures.current = 0;
          setView(next);
        })
        .catch(() => {
          if (cancelled) return;
          pollFailures.current += 1;
          if (pollFailures.current >= SHELL_RENDER_POLL_FAILURE_LIMIT) {
            setView(shellRenderProgressUnavailable(pollFailures.current));
          }
        });
    }, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [projectId, view.phase]);

  const confirmAudioSubtitle = useCallback(async () => {
    if (!projectId || !manualAudioSubtitle) return;
    setBusy(true);
    try {
      await confirmShellAudioSubtitle(projectId);
      setManualAudioSubtitle(null);
      setView(await enqueueShellRender(projectId));
    } catch (error) {
      const code = error instanceof ApiError ? error.code : null;
      setView({
        phase: "failed",
        headline: "失败可重试",
        detail: error instanceof Error && error.message ? error.message : "确认配音字幕失败",
        playableUrl: null,
        mockReady: false,
        errorCode: code,
      });
    } finally {
      setBusy(false);
    }
  }, [projectId, manualAudioSubtitle]);

  return {
    view: busy && view.phase === "idle" ? SUBMITTING_RENDER : view,
    busy,
    reading,
    manualAudioSubtitle,
    submit: () => submit(false),
    retry: () => submit(true),
    refresh,
    confirmAudioSubtitle,
  };
}

function VoiceLine({ draft }: { draft: Pick<StudioDraft, "presenterId" | "path"> }) {
  const voice = shellVoiceCopy(draft.presenterId, draft.path);
  return (
    <>
      <div className="ot-checkline">声线：{voice.label}</div>
      <p className="ot-hint">{voice.detail}</p>
    </>
  );
}

function RenderSlot({
  renderJob,
  allowSubmit,
  onBackToGenerate,
}: {
  renderJob: ReturnType<typeof useShellRender>;
  /** 只有生成页能提交新渲染；交付页只读已有渲染。 */
  allowSubmit: boolean;
  onBackToGenerate?: () => void;
}) {
  const { view } = renderJob;
  return (
    <section className="ot-panel" aria-label="成片">
      <p role="status">
        {view.headline}
        {view.mockReady ? " · Mock 成片就绪" : ""}
      </p>
      <p className="ot-page-sub">{view.detail}</p>
      {view.playableUrl ? (
        <video className="ot-player" controls playsInline src={view.playableUrl} aria-label="成片播放" />
      ) : null}
      {renderJob.manualAudioSubtitle ? (
        <section className="ot-banner" role="alert" aria-label="人工确认配音与字幕">
          <h3>需要确认配音与字幕</h3>
          <p>{renderJob.manualAudioSubtitle.reason}</p>
          <p>配音时长：{renderJob.manualAudioSubtitle.voiceDuration == null ? "未知" : `${renderJob.manualAudioSubtitle.voiceDuration.toFixed(1)}s`}</p>
          <p>
            字幕：{renderJob.manualAudioSubtitle.subtitleSegments.length} 段
            {renderJob.manualAudioSubtitle.subtitleSegments[0]?.text ? ` · ${renderJob.manualAudioSubtitle.subtitleSegments[0].text}` : " · 暂无文字"}
          </p>
          <button type="button" className="ot-btn ot-btn-primary ot-btn-sm" disabled={renderJob.busy} onClick={() => void renderJob.confirmAudioSubtitle()}>
            {renderJob.busy ? "确认中…" : "确认配音与字幕并提交"}
          </button>
        </section>
      ) : null}
      {view.phase === "failed" && allowSubmit ? (
        <button type="button" className="ot-btn ot-btn-primary ot-btn-sm" disabled={renderJob.busy} onClick={() => void renderJob.retry()}>
          重试渲染
        </button>
      ) : null}
      {view.phase === "unavailable" ? (
        <button type="button" className="ot-btn ot-btn-secondary ot-btn-sm" disabled={renderJob.busy} onClick={() => void renderJob.refresh()}>
          刷新进度
        </button>
      ) : null}
      {view.phase === "idle" && allowSubmit && !renderJob.manualAudioSubtitle ? (
        <button type="button" className="ot-btn ot-btn-primary ot-btn-lg" disabled={renderJob.busy || renderJob.reading} onClick={() => void renderJob.submit()}>
          {renderJob.busy ? "提交中…" : renderJob.reading ? "读取已有渲染…" : "确认提交渲染"}
        </button>
      ) : null}
      {view.phase === "idle" && !allowSubmit && onBackToGenerate ? (
        <button type="button" className="ot-btn ot-btn-secondary ot-btn-sm" onClick={onBackToGenerate}>
          回生成页确认提交
        </button>
      ) : null}
    </section>
  );
}

function Generate({
  product,
  presenter,
  draft,
  onNext,
  onReview,
  onPrepare,
}: {
  product: Project | null;
  presenter: PresenterOption;
  draft: StudioDraft;
  onNext: () => void;
  onReview: () => void;
  onPrepare: () => void;
}) {
  const projectId = product?.project_id ?? null;
  const guard = useScriptGateGuard(projectId);
  const renderJob = useShellRender(projectId);
  const [syncing, setSyncing] = useState(() => projectCharacterSync(draft.presenterId) !== null && projectId !== null);
  const [syncError, setSyncError] = useState<string | null>(null);

  useEffect(() => {
    const sync = projectCharacterSync(draft.presenterId);
    if (!sync || !projectId) {
      setSyncing(false);
      return;
    }
    let cancelled = false;
    setSyncing(true);
    setSyncError(null);
    void updateProject(projectId, { characterId: sync.characterId })
      .then(() => {
        if (!cancelled) setSyncError(null);
      })
      .catch(() => {
        if (!cancelled) {
          setSyncError(sync.characterId === null ? PRESENTER_CLEAR_FAILED : "出镜人没能写入项目，已停止。不会改用预制出镜人。");
        }
      })
      .finally(() => {
        if (!cancelled) setSyncing(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, draft.presenterId]);

  const presenterError = draft.path === "talking_head" && presenter.source !== "library"
    ? TALKING_HEAD_LIBRARY_PRESENTER_REQUIRED
    : talkingHeadStartError(draft);
  const held = guard.loading || guard.blocked || syncing || syncError !== null || presenterError !== null;
  const ready = !held;
  const playable = renderJob.view.phase === "playable" && Boolean(renderJob.view.playableUrl);
  const nextLabel = playable ? "查看成片" : "查看进度";
  return (
    <>
      <div className="ot-content">
        <div>
          <h1 className="ot-page-title">提交渲染</h1>
          <p className="ot-page-sub">过闸后提交与托管工作台相同的渲染。没有成片地址时不提供预览。不经过图片广告。</p>
        </div>
        <section className="ot-panel">
          <div className="ot-checkline">商品：{product?.product_name ?? "未选择"}</div>
          <div className="ot-checkline">{generatePresenterCheck(presenter)}</div>
          <div className="ot-checkline">规格：{draft.ratio} · {draft.duration}</div>
          <VoiceLine draft={draft} />
          <div className="ot-checkline">图片广告：未使用，也不是本步的前置条件</div>
        </section>
        {presenterError ? (
          <section className="ot-panel" role="alert">
            <h2 className="ot-gate">出镜人未通过启动校验</h2>
            <p className="ot-page-sub">{presenterError}。请回准备步从当前出镜人库选择角色。</p>
            <button type="button" className="ot-btn ot-btn-primary" onClick={onPrepare}>回准备步选择</button>
          </section>
        ) : null}
        {syncError ? <p className="ot-error" role="alert">{syncError}</p> : null}
        {guard.loading ? <p className="ot-hint" role="status">正在核对审稿闸…</p> : null}
        {!guard.loading && guard.blocked ? (
          <section className="ot-panel" role="alert">
            <h2 className="ot-gate">付费生成已拦住</h2>
            <p className="ot-page-sub">{guard.message}</p>
            <button type="button" className="ot-btn ot-btn-primary" onClick={onReview}>回到审稿过闸</button>
          </section>
        ) : null}
        {ready ? <RenderSlot renderJob={renderJob} allowSubmit /> : null}
      </div>
      <footer className="ot-sticky">
        <div>
          <div className="ot-sticky-title">{guard.blocked ? "提交渲染前要先过审稿闸" : playable ? "成片可播" : "渲染提交后才能看到成片"}</div>
          <div className="ot-sticky-sub">
            {guard.blocked ? "未 apply / ack 不会提交渲染，付费视频会 409 SCRIPT_REVIEW_REQUIRED" : playable ? "可以进入交付页查看已有成片。" : "当前不是成片，进入交付页查看只读进度。"}
          </div>
        </div>
        <button type="button" className={"ot-btn ot-btn-lg " + (playable ? "ot-btn-primary" : "ot-btn-secondary")} disabled={held || !product} onClick={onNext}>
          {nextLabel}
        </button>
      </footer>
    </>
  );
}

function Delivery({
  product,
  presenter,
  draft,
  onNavigate,
}: {
  product: Project | null;
  presenter: PresenterOption;
  draft: StudioDraft;
  onNavigate: (view: UrlView, projectId?: string | null) => void;
}) {
  const projectId = product?.project_id ?? null;
  const guard = useScriptGateGuard(projectId);
  const renderJob = useShellRender(projectId);
  const ready = !guard.loading && !guard.blocked;
  return (
    <>
      <div className="ot-content">
        <div>
          <h1 className="ot-page-title">成片交付</h1>
          <p className="ot-page-sub">成片以渲染结果为准。未完成时是待渲染或排队，没有成片地址就不提供预览。有机发布尚未接线。</p>
        </div>
        {guard.loading ? <p className="ot-hint" role="status">正在核对审稿闸…</p> : null}
        {!guard.loading && guard.blocked ? (
          <section className="ot-panel" role="alert">
            <h2 className="ot-gate">付费生成已拦住</h2>
            <p className="ot-page-sub">{guard.message}</p>
          </section>
        ) : null}
        {product ? (
          <RenderSlot
            renderJob={renderJob}
            allowSubmit={false}
            onBackToGenerate={() => onNavigate("generate", projectId)}
          />
        ) : null}
        <section className="ot-panel">
          <div className="ot-checkline">商品：{product?.product_name ?? "未选择"}</div>
          <div className="ot-checkline">{deliveryPresenterCheck(presenter)}</div>
          <div className="ot-checkline">规格：{draft.ratio} · {draft.duration}</div>
          <VoiceLine draft={draft} />
          <div className="ot-checkline">发布：有机发布尚未接线，去了也发不出去</div>
        </section>
      </div>
      <footer className="ot-sticky">
        <div>
          <div className="ot-sticky-title">{ready ? "成片以渲染结果为准" : "还没有成片"}</div>
          <div className="ot-sticky-sub">导演模式和托管工作台仍可进入，但不是这条路径的必经步骤。</div>
        </div>
        <div className="ot-sticky-right">
          {product ? (
            <button type="button" className="ot-btn ot-btn-secondary" onClick={() => onNavigate("workbench", product.project_id)}>高级 · 托管工作台</button>
          ) : null}
          <button type="button" className="ot-btn ot-btn-secondary" onClick={() => onNavigate("connect")}>打开发布入口（未接线）</button>
          <button type="button" className="ot-btn ot-btn-primary ot-btn-lg" onClick={() => onNavigate("home")}>回到首页</button>
        </div>
      </footer>
    </>
  );
}

function downloadText(filename: string, text: string) {
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  // jsdom 没有实现非 hash 导航，点下载链会在控制台报 Not implemented。
  if (!/jsdom/i.test(navigator.userAgent)) anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
