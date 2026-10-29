/** 准备步：只读已选商品，填写本场出片输入。不在这里再挑 SKU，也不新建商品。 */
import { useId, useRef, useState } from "react";

import type { Project } from "../../features/input/types";
import type { Character } from "../../shared/api/characterApi";
import {
  PREPARE_IMAGE_ACCEPT,
  STUDIO_DURATIONS,
  STUDIO_RATIOS,
  applyPrepareEdit,
  effectivePrepareFields,
  prepareImageRejection,
  prepareSubmitErrors,
  presenterOptions,
  setPrepareSessionOnly,
  type PrepareImage,
  type PresenterOption,
  type SkuEnrichment,
  type StudioDraft,
} from "./model";

let rowSeq = 0;
function nextRowId(): string {
  rowSeq += 1;
  return `point-${rowSeq}`;
}

function toRows(points: string[]): { id: string; text: string }[] {
  const source = points.length > 0 ? points.slice(0, 5) : [""];
  return source.map((text) => ({ id: nextRowId(), text }));
}

export function PrepareStep(props: {
  draft: StudioDraft;
  requestedProjectId: string | null;
  loading: boolean;
  error: string | null;
  product: Project | null;
  presenter: PresenterOption;
  characters: Character[];
  castOpen: boolean;
  onCastOpen: (open: boolean) => void;
  onDraft: (partial: Partial<StudioDraft>) => void;
  onBrand: () => void;
  onCharacters: () => void;
  onStart: () => void | Promise<void>;
  syncing?: boolean;
  syncError?: string | null;
}) {
  if (!props.product) return <PrepareEmpty {...props} />;
  return <PrepareLoaded key={props.product.project_id} {...props} product={props.product} />;
}

function PrepareEmpty({
  draft,
  requestedProjectId,
  loading,
  error,
  presenter,
  onBrand,
}: {
  draft: StudioDraft;
  requestedProjectId: string | null;
  loading: boolean;
  error: string | null;
  presenter: PresenterOption;
  onBrand: () => void;
}) {
  const pending = Boolean(requestedProjectId) && loading;
  const invalid = Boolean(requestedProjectId) && !loading && !error;
  return (
    <>
      <div className="ot-content">
        <div>
          <h1 className="ot-page-title">准备</h1>
          <p className="ot-page-sub">完善本场出片所需的商品信息 · 本步不扣费 · 无需先做图片广告</p>
        </div>
        {error ? <p className="ot-error">{error}</p> : null}
        {pending ? <p className="ot-hint">正在读取品牌空间…</p> : null}
        {!pending ? (
          <section className="ot-panel ot-prepare-empty">
            <h2>{invalid ? "商品已不存在，回品牌空间" : "请先在品牌空间选择一件商品"}</h2>
            {invalid ? <p className="ot-hint">请先在品牌空间选择一件商品</p> : null}
            <button type="button" className="ot-btn ot-btn-primary" onClick={onBrand}>去品牌空间选商品</button>
          </section>
        ) : null}
      </div>
      <PrepareFooter draft={draft} presenter={presenter} productName={null} errors={[]} ready={false} onStart={() => {}} />
    </>
  );
}

function PrepareLoaded({
  draft,
  product,
  presenter,
  characters,
  castOpen,
  onCastOpen,
  onDraft,
  onBrand,
  onCharacters,
  onStart,
  syncing,
  syncError,
}: {
  draft: StudioDraft;
  product: Project;
  presenter: PresenterOption;
  characters: Character[];
  castOpen: boolean;
  onCastOpen: (open: boolean) => void;
  onDraft: (partial: Partial<StudioDraft>) => void;
  onBrand: () => void;
  onCharacters: () => void;
  onStart: () => void | Promise<void>;
  syncing?: boolean;
  syncError?: string | null;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const errorId = useId();
  const initial = effectivePrepareFields(product.project_id, draft);
  const [pain, setPain] = useState(initial.pain_point);
  const [rows, setRows] = useState(() => toRows(initial.selling_points));
  const [scene, setScene] = useState(initial.usage_scenario);
  const [specs, setSpecs] = useState(initial.specs);
  const [offer, setOffer] = useState(initial.offer);
  const [images, setImages] = useState<PrepareImage[]>(initial.images);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const options = presenterOptions(characters);
  const errors = prepareSubmitErrors({
    imageCount: images.length,
    painPoint: pain,
    sellingPoints: rows.map((row) => row.text),
    usageScenario: scene,
  });
  const ready = errors.length === 0;

  function snapshot(overrides: Partial<SkuEnrichment> = {}): SkuEnrichment {
    return {
      pain_point: pain,
      selling_points: rows.map((row) => row.text),
      usage_scenario: scene,
      specs,
      offer,
      images,
      ...overrides,
    };
  }

  function commit(next: SkuEnrichment) {
    onDraft(applyPrepareEdit(product.project_id, draft, next));
  }

  function onFiles(list: FileList | null) {
    if (!list?.length) return;
    let rejected: string | null = null;
    const accepted: PrepareImage[] = [];
    for (const file of Array.from(list)) {
      const reason = prepareImageRejection(file);
      if (reason) {
        rejected = reason;
        continue;
      }
      accepted.push({
        id: `${file.name}-${file.size}-${accepted.length}-${Date.now()}`,
        name: file.name,
        mime: file.type || "image/jpeg",
        size: file.size,
        preview: URL.createObjectURL(file),
      });
    }
    setUploadError(rejected);
    if (accepted.length === 0) return;
    const nextImages = [...images, ...accepted];
    setImages(nextImages);
    commit(snapshot({ images: nextImages }));
  }

  return (
    <>
      <div className="ot-content">
        <div>
          <h1 className="ot-page-title">准备</h1>
          <p className="ot-page-sub">完善本场出片所需的商品信息 · 本步不扣费 · 无需先做图片广告</p>
        </div>
        <div className="ot-split">
          <div className="ot-col">
            <section className="ot-panel" aria-label="已选商品">
              <div className="ot-label-row">
                <div className="ot-label">已选商品</div>
                <button type="button" className="ot-link" onClick={onBrand}>更换 →</button>
              </div>
              <div className="ot-summary">
                <span className="ot-thumb">
                  {images[0] ? <img src={images[0].preview} alt="" /> : <span className="ot-ptag">主图</span>}
                </span>
                <span>
                  <span className="ot-product-name">{product.product_name}</span>
                  <span className="ot-product-meta">来自品牌空间</span>
                  <span className="ot-summary-links">
                    <button type="button" className="ot-link" onClick={onBrand}>在品牌空间编辑</button>
                  </span>
                </span>
              </div>
            </section>
            <section className="ot-panel">
              <div className="ot-label">商品图片 <span className="ot-req">必填</span></div>
              {images.length > 0 ? (
                <div className="ot-image-grid">
                  {images.map((image) => (
                    <div key={image.id} className="ot-image-tile">
                      <img src={image.preview} alt={image.name} />
                      <button
                        type="button"
                        aria-label={`移除图片 ${image.name}`}
                        onClick={() => {
                          if (image.preview.startsWith("blob:")) URL.revokeObjectURL(image.preview);
                          const nextImages = images.filter((item) => item.id !== image.id);
                          setImages(nextImages);
                          commit(snapshot({ images: nextImages }));
                        }}
                      >
                        移除
                      </button>
                    </div>
                  ))}
                </div>
              ) : null}
              <input
                ref={fileRef}
                className="ot-file"
                type="file"
                accept={PREPARE_IMAGE_ACCEPT}
                multiple
                aria-label="选择商品图片"
                onChange={(event) => {
                  onFiles(event.target.files);
                  event.target.value = "";
                }}
              />
              <button type="button" className="ot-btn ot-btn-secondary ot-btn-sm" onClick={() => fileRef.current?.click()}>上传图片</button>
              <p className="ot-hint">支持 PNG / JPEG / JPG / WEBP，单张 ≤10MB，至少 1 张</p>
              {uploadError ? <p className="ot-error" role="alert">{uploadError}</p> : null}
            </section>
            <section className="ot-panel">
              <label className="ot-field-block">
                <span className="ot-label">痛点 <span className="ot-req">必填</span></span>
                <textarea
                  className="ot-textarea"
                  aria-label="痛点"
                  maxLength={80}
                  placeholder="例：清洗麻烦、容易拔干…"
                  value={pain}
                  onChange={(event) => {
                    const value = event.target.value;
                    setPain(value);
                    commit(snapshot({ pain_point: value }));
                  }}
                />
              </label>
              <div className="ot-field-block" role="group" aria-label="核心卖点">
                <div className="ot-label">核心卖点 <span className="ot-req">必填</span></div>
                {rows.map((row, index) => (
                  <div key={row.id} className="ot-point-row">
                    <input
                      aria-label={`卖点 ${index + 1}`}
                      maxLength={60}
                      value={row.text}
                      placeholder={index === 0 ? "例：杯身可拆，冲洗方便" : "再写一条卖点"}
                      onChange={(event) => {
                        const nextRows = rows.map((item) => (item.id === row.id ? { ...item, text: event.target.value } : item));
                        setRows(nextRows);
                        commit(snapshot({ selling_points: nextRows.map((item) => item.text) }));
                      }}
                    />
                    <button
                      type="button"
                      className="ot-link"
                      aria-label={`删除卖点 ${index + 1}`}
                      onClick={() => {
                        const nextRows = rows.filter((item) => item.id !== row.id);
                        const visible = nextRows.length > 0 ? nextRows : [{ id: nextRowId(), text: "" }];
                        setRows(visible);
                        commit(snapshot({ selling_points: visible.map((item) => item.text) }));
                      }}
                    >
                      删除
                    </button>
                  </div>
                ))}
                <button
                  type="button"
                  className="ot-btn ot-btn-secondary ot-btn-sm"
                  disabled={rows.length >= 5}
                  onClick={() => setRows([...rows, { id: nextRowId(), text: "" }])}
                >
                  添加卖点
                </button>
              </div>
              <label className="ot-field-block">
                <span className="ot-label">使用场景 <span className="ot-req">必填</span></span>
                <textarea
                  className="ot-textarea"
                  aria-label="使用场景"
                  maxLength={100}
                  placeholder="例：通勤路上、办公室下午…"
                  value={scene}
                  onChange={(event) => {
                    const value = event.target.value;
                    setScene(value);
                    commit(snapshot({ usage_scenario: value }));
                  }}
                />
              </label>
              <label className="ot-field-block">
                <span className="ot-label">规格要点 <span className="ot-opt">可选</span></span>
                <textarea
                  className="ot-textarea"
                  aria-label="规格要点"
                  maxLength={200}
                  placeholder="例：30ml、玻璃瓶"
                  value={specs}
                  onChange={(event) => {
                    const value = event.target.value;
                    setSpecs(value);
                    commit(snapshot({ specs: value }));
                  }}
                />
              </label>
              <label className="ot-field-block">
                <span className="ot-label">优惠活动 <span className="ot-opt">可选</span></span>
                <textarea
                  className="ot-textarea"
                  aria-label="优惠活动"
                  maxLength={80}
                  placeholder="例：下单赠小样；留空则脚本不含促销"
                  value={offer}
                  onChange={(event) => {
                    const value = event.target.value;
                    setOffer(value);
                    commit(snapshot({ offer: value }));
                  }}
                />
              </label>
              <label className="ot-session">
                <input
                  type="checkbox"
                  checked={draft.sessionOnly}
                  onChange={(event) => {
                    onDraft(setPrepareSessionOnly(product.project_id, draft, event.target.checked, snapshot()));
                  }}
                />
                仅用于本次出片
              </label>
              <p className="ot-hint">默认写回该商品，下次进入仍会带上。勾选后只影响这一次出片。</p>
            </section>
          </div>
          <div className="ot-side-col">
            <section className="ot-panel">
              <div className="ot-label">出镜人 · 库选</div>
              {presenter.source === "none" ? (
                <div className="ot-cast-picked">
                  <b>{presenter.name}</b>
                  <span>{presenter.role}</span>
                </div>
              ) : (
                <div className="ot-talent">
                  <div className="ot-talent-avatar">{presenter.initial}</div>
                  <div>
                    <b>{presenter.name}</b>
                    <span>{presenter.role}</span>
                  </div>
                </div>
              )}
              <button type="button" className="ot-link" aria-expanded={castOpen} onClick={() => onCastOpen(!castOpen)}>从出镜人库更换 →</button>
              {castOpen ? (
                <div className="ot-cast">
                  {options.map((option) => (
                    <button key={option.id ?? "none"} type="button" className={option.id === presenter.id ? "on" : ""} aria-pressed={option.id === presenter.id} onClick={() => onDraft({ presenterId: option.id })}>
                      <b>{option.name}</b>
                      <span>{option.role}</span>
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
          </div>
        </div>
      </div>
      <PrepareFooter
        draft={draft}
        presenter={presenter}
        productName={product.product_name}
        errors={errors}
        errorId={errorId}
        ready={ready}
        syncing={syncing}
        syncError={syncError}
        onStart={onStart}
      />
    </>
  );
}

function PrepareFooter({
  draft,
  presenter,
  productName,
  errors,
  errorId,
  ready,
  syncing = false,
  syncError = null,
  onStart,
}: {
  draft: StudioDraft;
  presenter: PresenterOption;
  productName: string | null;
  errors: string[];
  errorId?: string;
  ready: boolean;
  syncing?: boolean;
  syncError?: string | null;
  onStart: () => void | Promise<void>;
}) {
  return (
    <footer className="ot-sticky">
      <div>
        <div className="ot-sticky-title">{productName ?? "请先选择商品"}</div>
        <div className="ot-sticky-sub">下一步审稿九宫格 · 本步不扣费</div>
        {errors.length > 0 ? (
          <ul id={errorId} className="ot-prepare-errors" aria-label="还不能开始制作">
            {errors.map((item) => <li key={item}>{item}</li>)}
          </ul>
        ) : null}
        {syncError ? <p className="ot-error" role="alert">{syncError}</p> : null}
      </div>
      <div className="ot-sticky-right">
        <div className="ot-chips">
          <span className="ot-chip on">{draft.ratio}</span>
          <span className="ot-chip on">{draft.duration}</span>
          <span className="ot-chip">{presenter.source === "none" ? presenter.name : `${presenter.name} · ${presenter.role.split("·")[0].trim()}`}</span>
        </div>
        <button
          type="button"
          className="ot-btn ot-btn-primary ot-btn-lg"
          disabled={!ready || syncing}
          aria-describedby={errors.length > 0 ? errorId : undefined}
          onClick={() => {
            if (ready && !syncing) return onStart();
          }}
        >
          开始制作
        </button>
      </div>
    </footer>
  );
}
