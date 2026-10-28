/** iter18 外壳：首页上手、图片广告、品牌空间、有机发布、工作室四步。
 *
 * 工作室只走 准备 → 审稿 → 生成 → 成片。图片广告页的「另开工作室」是可选出口，
 * 不把选中的静图写进工作室草稿。
 */
import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";

import { listCharacters, type Character } from "../../shared/api/characterApi";
import { createProject, listProjects } from "../../shared/api/projectApi";
import type { Project } from "../../features/input/types";
import type { ShellView, UrlView } from "../urlState";
import {
  DEMO_CREDITS,
  DEMO_FEE,
  GS_STEPS,
  IMAGE_AD_CELLS,
  IMAGE_AD_RATIOS,
  PREMADE_PRESENTER,
  REVIEW_FILTERS,
  SELLING_POINTS,
  STUDIO_DURATIONS,
  STUDIO_RATIOS,
  STUDIO_STEPS,
  imageAdExportPayload,
  isStudioView,
  markGsDone,
  nextStudioView,
  presenterById,
  presenterOptions,
  readBrands,
  readGsDone,
  readStudioDraft,
  resolveSelectedProduct,
  reviewScript,
  visibleReviewCells,
  writeBrands,
  writeStudioDraft,
  type ImageAdRatio,
  type StudioDraft,
} from "./model";
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
  const [castOpen, setCastOpen] = useState(false);
  const [imageCellId, setImageCellId] = useState<string>(IMAGE_AD_CELLS[0].id);
  const [imageRatio, setImageRatio] = useState<ImageAdRatio>("1:1");
  const [exportNote, setExportNote] = useState<string | null>(null);
  const [reviewFilter, setReviewFilter] = useState<(typeof REVIEW_FILTERS)[number]>("全部");
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
    setDraft((current) => (current.projectId === projectId ? current : writeStudioDraft({ ...current, projectId })));
  }, [projectId]);

  useEffect(() => {
    if (!isStudioView(view)) return;
    let cancelled = false;
    void listCharacters()
      .then((list) => {
        if (!cancelled) setCharacters(list.characters);
      })
      .catch(() => {
        if (!cancelled) setCharacters([]);
      });
    return () => {
      cancelled = true;
    };
  }, [view]);

  function patchDraft(partial: Partial<StudioDraft>) {
    setDraft((current) => writeStudioDraft({ ...current, ...partial }));
  }

  function goGs(id: number, dest: UrlView) {
    setGsDone(markGsDone(id));
    onNavigate(dest);
  }

  const studioProduct = resolveSelectedProduct(draft.projectId, products);
  const presenter = presenterById(draft.presenterId, characters);
  const imageProduct = resolveSelectedProduct(draft.projectId, products);
  const imageName = imageProduct?.product_name ?? "春季护肤精华液";

  return (
    <div className="ot" data-view={view}>
      {isStudioView(view) ? (
        <StudioRail onNavigate={onNavigate} />
      ) : (
        <Sidebar view={view} onNavigate={onNavigate} />
      )}
      <div className="ot-main">
        {view === "home" ? (
          <Home
            openGs={openGs}
            done={gsDone.length}
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
              setExportNote(`已导出选中图：${cell.caption}`);
            }}
            onNavigate={(next) => onNavigate(next, next === "prepare" ? imageProduct?.project_id ?? null : null)}
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
            onNavigate={onNavigate}
          />
        ) : null}
        {view === "connect" ? <Connect onNavigate={onNavigate} /> : null}
        {isStudioView(view) ? (
          <Studio
            view={view}
            draft={draft}
            products={products}
            loading={productsLoading}
            error={productsError}
            product={studioProduct}
            presenter={presenter}
            characters={characters}
            castOpen={castOpen}
            reviewFilter={reviewFilter}
            onCastOpen={setCastOpen}
            onDraft={patchDraft}
            onFilter={setReviewFilter}
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

function Sidebar({ view, onNavigate }: { view: ShellView; onNavigate: (view: UrlView, projectId?: string | null) => void }) {
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
        <button type="button" className={"ot-tool" + (view === "image" ? " on" : "")} onClick={() => onNavigate("image")}>
          <Ico><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><path d="M21 15l-5-5L5 21" /></Ico>
          图片广告
        </button>
        <button type="button" className="ot-tool" onClick={() => onNavigate("prepare")}>
          <Ico><rect x="2" y="6" width="20" height="12" rx="2" /><path d="M10 10l5 2-5 2v-4z" /></Ico>
          快速出片
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
          <div className="ot-user-mail">积分 {DEMO_CREDITS}</div>
        </div>
      </div>
    </aside>
  );
}

function StudioRail({ onNavigate }: { onNavigate: (view: UrlView, projectId?: string | null) => void }) {
  return (
    <aside className="ot-rail" aria-label="工作室导航">
      <button type="button" className="ot-rail-brand" aria-label="返回首页" onClick={() => onNavigate("home")}>
        <Logo size={12} />
      </button>
      <button type="button" className="ot-rail-item on" onClick={() => onNavigate("prepare")}>
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
      <div className="ot-credits"><i /><span>{DEMO_CREDITS}</span></div>
    </aside>
  );
}

function Home({
  openGs,
  done,
  onOpen,
  onGo,
  onNavigate,
}: {
  openGs: number;
  done: number;
  onOpen: (id: number) => void;
  onGo: (id: number, dest: UrlView) => void;
  onNavigate: (view: UrlView, projectId?: string | null) => void;
}) {
  return (
    <>
      <header className="ot-top">
        <h1 className="ot-title">首页</h1>
        <button type="button" className="ot-btn ot-btn-primary" onClick={() => onNavigate("prepare")}>
          <Ico size={14}><path d="M12 5v14M5 12h14" /></Ico>
          新建
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
                        <button type="button" className="ot-btn ot-btn-primary ot-btn-sm" data-entry={`gs-${step.dest}`} onClick={() => onGo(step.id, step.dest)}>
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
          <ToolCard badge="主路径" name="快速出片" mode="模式 · 工作台" desc="选用商品与出镜人库，生成 9:16 种草成片。不经过图片广告。" onClick={() => onNavigate("prepare")} icon={<Ico size={20}><rect x="2" y="6" width="20" height="12" rx="2" /><path d="M10 10l5 2-5 2v-4z" /></Ico>} />
          <ToolCard name="图片广告" mode="模式 · 图片" desc="独立静图广告能力：九宫格初图预览，与视频工作室解耦。" onClick={() => onNavigate("image")} icon={<Ico size={20}><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><path d="M21 15l-5-5L5 21" /></Ico>} />
          <ToolCard name="品牌空间" mode="模式 · 素材库" desc="管理品牌 DNA、商品主图与卖点，供工作室与图片广告复用。" onClick={() => onNavigate("brand")} icon={<Ico size={20}><path d="M12 2 2 7l10 5 10-5-10-5z" /><path d="M2 17l10 5 10-5" /><path d="M2 12l10 5 10-5" /></Ico>} />
          <ToolCard name="有机种草" mode="模式 · 发布" desc="连接抖音 / 小红书，把成片发到有机渠道。" onClick={() => onNavigate("connect")} icon={<Ico size={20}><path d="M4 12c2-4 6-6 8-6s6 2 8 6c-2 4-6 6-8 6s-6-2-8-6z" /><circle cx="12" cy="12" r="2.5" /></Ico>} />
        </div>
        <h2 className="ot-section">最近动态</h2>
        <div className="ot-wn">
          <article className="ot-wn-card"><div className="ot-wn-thumb" /><div className="ot-wn-title">图片广告独立成能力</div><div className="ot-wn-desc">静图广告与工作室出片解耦；出片不必先出图。</div></article>
          <article className="ot-wn-card"><div className="ot-wn-thumb" /><div className="ot-wn-title">主按钮写清积分</div><div className="ot-wn-desc">「确认并生成视频 · 12 积分」，生成前不扣费。</div></article>
          <article className="ot-wn-card"><div className="ot-wn-thumb" /><div className="ot-wn-title">聚焦有机种草</div><div className="ot-wn-desc">不做 Meta 投放主路径；抖音 / 小红书优先。</div></article>
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
          <button type="button" className="ot-btn ot-btn-primary" onClick={onExport}>导出选中图</button>
        </div>
      </header>
      <div className="ot-body">
        <div className="ot-image-layout">
          <section className="ot-card">
            <h2>商品 → 图片广告预览</h2>
            <p>独立图片广告能力：选用品牌空间商品后，左侧以 3×3 九宫格展示初图。与工作室视频流程解耦，不强制进台。</p>
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
            <div className="ot-hint">假预览 · 9 张图片广告初图 · 点击选中 · 不真实生成</div>
          </section>
          <section className="ot-card">
            <h2>本页即可交付</h2>
            <p>图片广告是独立交付物。工作室出片另走「快速出片」，不必先过本页。</p>
            <div className="ot-stack">
              <button type="button" className="ot-btn ot-btn-primary" data-entry="image-export-main" onClick={onExport}>导出选中图（演示）</button>
              <button type="button" className="ot-btn ot-btn-secondary" onClick={() => onNavigate("brand")}>换商品</button>
              <button type="button" className="ot-btn ot-btn-secondary" onClick={() => onNavigate("connect")}>连接并发布（可选）</button>
              <button type="button" className="ot-btn ot-btn-secondary" data-entry="image-prepare-optional" onClick={() => onNavigate("prepare")}>可选 · 另开工作室出片</button>
            </div>
            <div className="ot-note">假数据：{productName} · 本页无真实生成 · 工作室四步不依赖本页结果。</div>
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
          <div className="ot-brand-grid">
            <button type="button" className="ot-brand-card add" onClick={onToggleProduct}>
              <span className="ot-plus">+</span>
              <span className="ot-add-title">添加商品</span>
              <span className="ot-add-sub">含实物与数字商品</span>
            </button>
            {addingProduct ? (
              <ProductForm saving={saving} onSubmit={onAddProduct} />
            ) : null}
            {products.map((product) => (
              <button key={product.project_id} type="button" className="ot-brand-card" onClick={() => onNavigate("prepare", product.project_id)}>
                <div className="ot-brand-thumb" />
                <div className="ot-brand-info">
                  <div className="ot-brand-name">{product.product_name}</div>
                  <div className="ot-brand-status"><i className="ot-dot" />已绑定 · 可出片</div>
                </div>
              </button>
            ))}
          </div>
          {loading ? <p className="ot-hint">正在读取商品…</p> : null}
          {error ? <p className="ot-error">{error}</p> : null}
        </section>
      </div>
    </>
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
  onNavigate,
}: {
  products: Project[];
  loading: boolean;
  error: string | null;
  onNavigate: (view: UrlView, projectId?: string | null) => void;
}) {
  return (
    <>
      <header className="ot-top">
        <h1 className="ot-title">项目</h1>
        <button type="button" className="ot-btn ot-btn-primary" onClick={() => onNavigate("prepare")}>
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
                  <button type="button" className="ot-btn ot-btn-secondary ot-btn-sm" onClick={() => onNavigate("director", product.project_id)}>进导演模式</button>
                  <button type="button" className="ot-btn ot-btn-secondary ot-btn-sm" onClick={() => onNavigate("workbench", product.project_id)}>托管工作台</button>
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
          <h2>连接并发布（可选）</h2>
          <p>把成片发到抖音 / 小红书有机渠道。可随时跳过。没有 Meta，也没有付费投放主路径。</p>
          <div className="ot-channels">
            <span className="ot-channel">抖音 · 未连接</span>
            <span className="ot-channel">小红书 · 未连接</span>
          </div>
          <div className="ot-cta-row" style={{ justifyContent: "center" }}>
            <button type="button" className="ot-btn ot-btn-primary" disabled>连接并发布（演示禁用）</button>
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
  products,
  loading,
  error,
  product,
  presenter,
  characters,
  castOpen,
  reviewFilter,
  onCastOpen,
  onDraft,
  onFilter,
  onNavigate,
}: {
  view: ShellView;
  draft: StudioDraft;
  products: Project[];
  loading: boolean;
  error: string | null;
  product: Project | null;
  presenter: { id: string; name: string; role: string; initial: string };
  characters: Character[];
  castOpen: boolean;
  reviewFilter: (typeof REVIEW_FILTERS)[number];
  onCastOpen: (open: boolean) => void;
  onDraft: (partial: Partial<StudioDraft>) => void;
  onFilter: (filter: (typeof REVIEW_FILTERS)[number]) => void;
  onNavigate: (view: UrlView, projectId?: string | null) => void;
}) {
  const stepIndex = STUDIO_STEPS.findIndex((step) => step.view === view);
  const productId = product?.project_id ?? null;
  const advance = () => {
    const next = nextStudioView(view);
    if (!next) return;
    if (view === "prepare" && product) onDraft({ projectId: product.project_id });
    onNavigate(next, product?.project_id ?? null);
  };

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
        <Prepare
          draft={draft}
          products={products}
          loading={loading}
          error={error}
          product={product}
          presenter={presenter}
          characters={characters}
          castOpen={castOpen}
          onCastOpen={onCastOpen}
          onDraft={onDraft}
          onBrand={() => onNavigate("brand")}
          onCharacters={() => onNavigate("characters")}
          onStart={advance}
        />
      ) : null}
      {view === "review" ? (
        <Review product={product} presenter={presenter} draft={draft} filter={reviewFilter} onFilter={onFilter} onConfirm={advance} />
      ) : null}
      {view === "generate" ? (
        <Generate product={product} presenter={presenter} draft={draft} onNext={advance} />
      ) : null}
      {view === "delivery" ? (
        <Delivery product={product} presenter={presenter} draft={draft} onNavigate={onNavigate} />
      ) : null}
    </div>
  );
}

function Prepare({
  draft,
  products,
  loading,
  error,
  product,
  presenter,
  characters,
  castOpen,
  onCastOpen,
  onDraft,
  onBrand,
  onCharacters,
  onStart,
}: {
  draft: StudioDraft;
  products: Project[];
  loading: boolean;
  error: string | null;
  product: Project | null;
  presenter: { id: string; name: string; role: string; initial: string };
  characters: Character[];
  castOpen: boolean;
  onCastOpen: (open: boolean) => void;
  onDraft: (partial: Partial<StudioDraft>) => void;
  onBrand: () => void;
  onCharacters: () => void;
  onStart: () => void;
}) {
  const options = presenterOptions(characters);
  return (
    <>
      <div className="ot-content">
        <div>
          <h1 className="ot-page-title">准备素材</h1>
          <p className="ot-page-sub">从品牌空间选用已有商品，再选规格与出镜人 · 本步不扣费 · 无需先做图片广告</p>
        </div>
        <div className="ot-split">
          <div className="ot-col">
            <section className="ot-panel">
              <div className="ot-label-row">
                <div className="ot-label">选用已有商品</div>
                <button type="button" className="ot-link" onClick={onBrand}>更换商品 →</button>
              </div>
              {loading ? <p className="ot-hint">正在读取品牌空间…</p> : null}
              {error ? <p className="ot-error">{error}</p> : null}
              {!loading && products.length === 0 ? (
                <p className="ot-hint">品牌空间里还没有可选用的商品。</p>
              ) : (
                products.map((item) => {
                  const selected = product?.project_id === item.project_id;
                  return (
                    <button key={item.project_id} type="button" className={"ot-product" + (selected ? " on" : "")} aria-pressed={selected} onClick={() => onDraft({ projectId: item.project_id })}>
                      <span className="ot-thumb"><span className="ot-ptag">主图</span></span>
                      <span>
                        <span className="ot-product-name">{item.product_name}{selected ? <span className="ot-sel">已选用</span> : null}</span>
                        <span className="ot-product-meta">来自品牌空间 · {item.product_note?.trim() || "主图已就绪"}</span>
                      </span>
                    </button>
                  );
                })
              )}
              <p className="ot-inline-hint">没有商品？<button type="button" className="ot-link" onClick={onBrand}>去品牌空间添加</button>（上传与细节图在品牌空间管理）</p>
            </section>
            <div className="ot-tips">
              <article className="ot-tipcard">
                <h3><span className="ot-mark">✓</span>推荐选用</h3>
                <ul>
                  <li>品牌空间已完善主图的商品</li>
                  <li>正面清晰、占画面 60%+</li>
                  <li>卖点与素材齐全的 SKU</li>
                </ul>
                <p>新品请先在品牌空间添加，再回此步选用。</p>
              </article>
              <article className="ot-tipcard dont">
                <h3><span className="ot-mark">×</span>尽量避免</h3>
                <ul>
                  <li>无主图或占位图的草稿商品</li>
                  <li>杂乱货架 / 多人合影主图</li>
                  <li>严重裁切或低清压缩</li>
                </ul>
              </article>
            </div>
          </div>
          <div className="ot-side-col">
            <section className="ot-panel">
              <div className="ot-label">出镜人 · 库选</div>
              <div className="ot-talent">
                <div className="ot-talent-avatar">{presenter.initial}</div>
                <div>
                  <b>{presenter.name}</b>
                  <span>{presenter.role}</span>
                </div>
              </div>
              <button type="button" className="ot-link" aria-expanded={castOpen} onClick={() => onCastOpen(!castOpen)}>从出镜人库更换 →</button>
              {castOpen ? (
                <div className="ot-cast">
                  {options.map((option) => (
                    <button key={option.id} type="button" className={option.id === presenter.id ? "on" : ""} aria-pressed={option.id === presenter.id} onClick={() => onDraft({ presenterId: option.id })}>
                      {option.name} · {option.role}
                    </button>
                  ))}
                  <button type="button" onClick={onCharacters}>管理出镜人库</button>
                </div>
              ) : null}
            </section>
            <section className="ot-panel">
              <div className="ot-label">成片规格</div>
              <div className="ot-field">画幅</div>
              <div className="ot-seg" role="group" aria-label="画幅">
                {STUDIO_RATIOS.map((ratio) => (
                  <button key={ratio} type="button" className={draft.ratio === ratio ? "on" : ""} aria-pressed={draft.ratio === ratio} onClick={() => onDraft({ ratio })}>{ratio}</button>
                ))}
              </div>
              <div className="ot-field">时长</div>
              <div className="ot-seg" role="group" aria-label="时长">
                {STUDIO_DURATIONS.map((duration) => (
                  <button key={duration} type="button" className={draft.duration === duration ? "on" : ""} aria-pressed={draft.duration === duration} onClick={() => onDraft({ duration })}>{duration}</button>
                ))}
              </div>
            </section>
            <section className="ot-panel">
              <div className="ot-label">卖点（可选）</div>
              {SELLING_POINTS.map((point) => {
                const selected = draft.points.includes(point.id);
                return (
                  <button key={point.id} type="button" className={"ot-check" + (selected ? " on" : "")} aria-pressed={selected} onClick={() => {
                    const points = selected ? draft.points.filter((id) => id !== point.id) : [...draft.points, point.id];
                    onDraft({ points: points.length ? points : [point.id] });
                  }}>
                    <span className="ot-box">{selected ? "✓" : ""}</span>
                    <span><b>{point.title}</b><span>{point.desc}</span></span>
                  </button>
                );
              })}
            </section>
          </div>
        </div>
      </div>
      <footer className="ot-sticky">
        <div>
          <div className="ot-sticky-title">{product?.product_name ?? "先选择品牌空间里的商品"}</div>
          <div className="ot-sticky-sub">下一步审稿九宫格分镜 · 本步不扣费 · 不经过图片广告</div>
        </div>
        <div className="ot-sticky-right">
          <div className="ot-chips">
            <span className="ot-chip on">{draft.ratio}</span>
            <span className="ot-chip on">{draft.duration}</span>
            <span className="ot-chip">{presenter.name} · {presenter.role.split("·")[0].trim()}</span>
          </div>
          <button type="button" className="ot-btn ot-btn-primary ot-btn-lg" disabled={!product} onClick={onStart}>开始制作</button>
        </div>
      </footer>
    </>
  );
}

function Review({
  product,
  presenter,
  draft,
  filter,
  onFilter,
  onConfirm,
}: {
  product: Project | null;
  presenter: { name: string };
  draft: StudioDraft;
  filter: (typeof REVIEW_FILTERS)[number];
  onFilter: (filter: (typeof REVIEW_FILTERS)[number]) => void;
  onConfirm: () => void;
}) {
  const cells = visibleReviewCells(filter);
  const name = product?.product_name ?? "已选商品";
  return (
    <>
      <div className="ot-content">
        <div className="ot-headrow">
          <div>
            <h1 className="ot-page-title">审稿确认</h1>
            <p className="ot-page-sub">核对九宫格分镜与口播，确认后一键生成。无需先做图片广告。</p>
          </div>
          <div className="ot-context">商品 <strong>{name}</strong></div>
        </div>
        <div className="ot-split">
          <div className="ot-col">
            <section className="ot-preview">
              <div className="ot-preview-bar">
                <div className="ot-ptabs">
                  <button type="button">分镜预览</button>
                  <button type="button">关键帧</button>
                  <button type="button" className="on">九宫格</button>
                </div>
                <div className="ot-meta">{draft.duration} · {draft.ratio} · 9 镜</div>
              </div>
              <div className="ot-preview-body">
                <div className="ot-filters-inline" role="group" aria-label="分镜筛选">
                  {REVIEW_FILTERS.map((item) => (
                    <button key={item} type="button" className={item === filter ? "on" : ""} aria-pressed={item === filter} onClick={() => onFilter(item)}>{item}</button>
                  ))}
                </div>
                <div className="ot-nine" role="list" aria-label="审稿九宫格">
                  {cells.map((cell) => (
                    <div key={cell.id} role="listitem" className="ot-cell" style={{ minHeight: 96 }}>
                      <span className={"ot-cell-bg " + cell.tone} />
                      <span className="ot-cell-tag">镜 {cell.id}<span className="dur">{cell.dur}</span></span>
                      <span className="ot-cell-cap">{cell.caption}</span>
                    </div>
                  ))}
                </div>
              </div>
            </section>
          </div>
          <div className="ot-side-col">
            <section className="ot-panel">
              <div className="ot-label">口播文案</div>
              <div className="ot-script">{reviewScript(name)}</div>
            </section>
            <section className="ot-panel">
              <div className="ot-label">配音试听</div>
              <div className="ot-audio">
                <div className="ot-play"><Logo size={10} /></div>
                <div className="ot-wave">{[5, 11, 16, 9, 18, 13, 7, 15, 19, 11, 6, 14].map((height, index) => <i key={index} style={{ height }} />)}</div>
                <div className="ot-meta">{presenter.name}</div>
              </div>
            </section>
            <section className="ot-panel">
              <div className="ot-label">费用明细</div>
              <div className="ot-fee-row"><span>文案与分镜</span><b>已含</b></div>
              <div className="ot-fee-row"><span>配音合成</span><b>2 积分</b></div>
              <div className="ot-fee-row"><span>视频生成 · {draft.duration}</span><b>10 积分</b></div>
              <div className="ot-divider" />
              <div className="ot-fee-row"><span>合计</span><span className="ot-fee-total">{DEMO_FEE} 积分</span></div>
              <div className="ot-hint">演示口径。确认后进入生成步，不在此页扣积分，也不经过图片广告。</div>
            </section>
          </div>
        </div>
      </div>
      <footer className="ot-sticky">
        <div>
          <div className="ot-sticky-title">一键生成成片</div>
          <div className="ot-sticky-sub">下一步是生成，不是图片广告</div>
        </div>
        <div className="ot-sticky-right">
          <button type="button" className="ot-btn ot-btn-primary ot-btn-lg" onClick={onConfirm}>
            确认并生成视频<span className="ot-fee">· {DEMO_FEE} 积分</span>
          </button>
        </div>
      </footer>
    </>
  );
}

function Generate({
  product,
  presenter,
  draft,
  onNext,
}: {
  product: Project | null;
  presenter: { name: string; role: string };
  draft: StudioDraft;
  onNext: () => void;
}) {
  return (
    <>
      <div className="ot-content">
        <div>
          <h1 className="ot-page-title">生成中</h1>
          <p className="ot-page-sub">按已选商品和出镜人生成成片 · 不经过图片广告 · 本页不发起新的出图</p>
        </div>
        <section className="ot-panel">
          <div className="ot-checkline">商品：{product?.product_name ?? "未选择"}</div>
          <div className="ot-checkline">出镜人：{presenter.name} · {presenter.role}</div>
          <div className="ot-checkline">规格：{draft.ratio} · {draft.duration}</div>
          <div className="ot-checkline">图片广告：未使用，也不是本步的前置条件</div>
        </section>
      </div>
      <footer className="ot-sticky">
        <div>
          <div className="ot-sticky-title">生成步骤已完成编排</div>
          <div className="ot-sticky-sub">真实渲染仍可稍后从成片页进入托管工作台</div>
        </div>
        <button type="button" className="ot-btn ot-btn-primary ot-btn-lg" onClick={onNext}>查看成片</button>
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
  presenter: { name: string };
  draft: StudioDraft;
  onNavigate: (view: UrlView, projectId?: string | null) => void;
}) {
  return (
    <>
      <div className="ot-content">
        <div>
          <h1 className="ot-page-title">成片交付</h1>
          <p className="ot-page-sub">工作室四步已走完（准备 → 审稿 → 生成 → 成片），没有经过图片广告。</p>
        </div>
        <section className="ot-panel">
          <div className="ot-checkline">商品：{product?.product_name ?? "未选择"}</div>
          <div className="ot-checkline">出镜人：{presenter.name}</div>
          <div className="ot-checkline">规格：{draft.ratio} · {draft.duration}</div>
          <div className="ot-checkline">发布：可选，抖音 / 小红书有机渠道</div>
        </section>
      </div>
      <footer className="ot-sticky">
        <div>
          <div className="ot-sticky-title">{product?.product_name ?? "成片"}</div>
          <div className="ot-sticky-sub">这条路径不依赖图片广告的九宫格结果</div>
        </div>
        <div className="ot-sticky-right">
          {product ? (
            <button type="button" className="ot-btn ot-btn-secondary" onClick={() => onNavigate("workbench", product.project_id)}>托管工作台继续渲染</button>
          ) : null}
          <button type="button" className="ot-btn ot-btn-secondary" onClick={() => onNavigate("connect")}>去发布（可选）</button>
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
