import type { MainImageState, MainImageStatus } from "./types";

interface MainImagePanelProps {
  state: MainImageState;
  canStart: boolean;
  isStarting: boolean;
  isConfirming: boolean;
  error: string | null;
  onStart: () => void;
  onConfirm: () => void;
}

const STATUS_TEXT: Record<MainImageStatus, string> = {
  queued: "等待图像编辑",
  editing: "正在清理背景和杂项",
  matting: "正在进行智能去背",
  processing: "正在标准化输出规格",
  ready: "主图已生成，请确认",
  confirmed: "主图已确认",
  failed: "主图处理失败",
};

const STAGES = [
  { key: "editing", title: "图像编辑", detail: "清理杂项" },
  { key: "matting", title: "智能去背", detail: "保留主体" },
  { key: "processing", title: "标准化", detail: "PNG / JPG" },
];

function stageState(status: MainImageStatus, stage: string): "done" | "active" | "locked" {
  if (status === "ready" || status === "confirmed") return "done";
  const currentIndex = status === "queued" ? 0 : STAGES.findIndex((item) => item.key === status);
  const stageIndex = STAGES.findIndex((item) => item.key === stage);
  if (status === "failed") return stageIndex === 0 ? "active" : "locked";
  if (stageIndex < currentIndex) return "done";
  if (stageIndex === currentIndex) return "active";
  return "locked";
}

function formatSize(value: number | null): string {
  if (!value) return "—";
  return `${(value / 1024 / 1024).toFixed(2)} MB`;
}

export function MainImagePanel({
  state,
  canStart,
  isStarting,
  isConfirming,
  error,
  onStart,
  onConfirm,
}: MainImagePanelProps) {
  const version = state.version;
  const status = version?.status ?? "idle";
  const isWorking = status === "queued" || status === "editing" || status === "matting" || status === "processing";
  const isReady = status === "ready" || status === "confirmed";

  return (
    <section className="surface-card main-image-card">
      <div className="section-heading">
        <div>
          <h2>主图处理</h2>
          <p>先编辑，再去背，最后统一输出 2000 × 2000 PNG 与 1000 × 1000 JPG。</p>
        </div>
        <span className={"main-image-status is-" + status}>
          {status === "idle" ? "等待生成" : STATUS_TEXT[status as MainImageStatus]}
        </span>
      </div>

      {!version ? (
        <div className="main-image-empty">
          <div>
            <strong>生成干净的商品主图</strong>
            <p>使用已确认的商品素材，默认通过 Mock Provider 完成整条链路。</p>
          </div>
          <button className="button button-primary" type="button" disabled={!canStart || isStarting} onClick={onStart}>
            {isStarting ? "正在创建任务…" : "生成主图"}
          </button>
        </div>
      ) : null}

      {version && isWorking ? (
        <div className="main-image-working">
          <div className="main-image-stage-track">
            {STAGES.map((stage, index) => {
              const stageStatus = stageState(version.status, stage.key);
              return (
                <div className={"main-image-stage is-" + stageStatus} key={stage.key}>
                  <span>{stageStatus === "done" ? "✓" : index + 1}</span>
                  <div><strong>{stage.title}</strong><small>{stage.detail}</small></div>
                </div>
              );
            })}
          </div>
          <div className="main-image-working-copy">
            <span className="spinner small" />
            <strong>{STATUS_TEXT[version.status]}</strong>
            <p>页面会自动刷新，完成后显示 PNG 与 JPG 预览。</p>
          </div>
        </div>
      ) : null}

      {version && isReady ? (
        <>
          <div className="main-image-preview-grid">
            <figure className="main-image-preview checkerboard">
              <img src={version.png_url ?? ""} alt="透明背景主图预览" />
              <figcaption><strong>透明 PNG</strong><span>2000 × 2000</span></figcaption>
            </figure>
            <figure className="main-image-preview white-preview">
              <img src={version.jpg_url ?? ""} alt="白底主图预览" />
              <figcaption><strong>白底 JPG</strong><span>1000 × 1000</span></figcaption>
            </figure>
          </div>
          <div className="main-image-meta">
            <span>JPG {formatSize(version.jpg_size_bytes)}</span>
            <span>商品占比 {version.product_ratio ? Math.round(version.product_ratio * 100) : "—"}%</span>
            <span>{version.status === "confirmed" ? "已确认版本" : "等待确认"}</span>
          </div>
          <div className="main-image-actions">
            <button className="button button-secondary" type="button" disabled={isStarting} onClick={onStart}>
              {isStarting ? "正在重新生成…" : "重新生成"}
            </button>
            <button
              className="button button-primary"
              type="button"
              disabled={version.status === "confirmed" || isConfirming}
              onClick={onConfirm}
            >
              {version.status === "confirmed" ? "已确认" : isConfirming ? "正在确认…" : "确认主图"}
            </button>
          </div>
        </>
      ) : null}

      {status === "failed" || error ? (
        <div className="main-image-error">
          <div><strong>主图未完成</strong><p>{error ?? version?.error_code ?? "请稍后重试"}</p></div>
          <button className="button button-secondary" type="button" disabled={isStarting} onClick={onStart}>
            {isStarting ? "正在重试…" : "重新生成"}
          </button>
        </div>
      ) : null}
    </section>
  );
}

