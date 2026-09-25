import type { UploadItem } from "./types";
import { formatBytes } from "./validation";

const STATUS_LABELS: Record<UploadItem["status"], string> = {
  queued: "待上传",
  validating: "校验中",
  invalid: "不可用",
  presigning: "准备上传",
  uploading: "上传中",
  completing: "复核中",
  ready: "已完成",
  failed: "失败",
};

interface UploadAssetCardProps {
  item: UploadItem;
  onRetry: (localId: string) => void;
}

export function UploadAssetCard({ item, onRetry }: UploadAssetCardProps) {
  return (
    <article className={`asset-card status-${item.status}`}>
      <div className="asset-thumbnail">
        {item.previewUrl ? (
          <img src={item.previewUrl} alt={item.filename} />
        ) : (
          <span className="asset-placeholder" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none">
              <path d="M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v11a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 17.5v-11Z" />
              <path d="m5 17 4.5-4.5 3 3 2-2L19 18" />
            </svg>
          </span>
        )}
        <span className="asset-status-dot" aria-hidden="true" />
      </div>
      <div className="asset-copy">
        <div className="asset-name-row">
          <strong title={item.filename}>{item.filename}</strong>
          <span>{STATUS_LABELS[item.status]}</span>
        </div>
        <div className="asset-meta">
          <span>{formatBytes(item.sizeBytes)}</span>
          {item.width && item.height ? <span>{item.width} × {item.height}</span> : null}
        </div>
        {["presigning", "uploading", "completing"].includes(item.status) ? (
          <div className="asset-progress" aria-label={`上传进度 ${item.progress}%`}>
            <span style={{ width: `${item.progress}%` }} />
          </div>
        ) : null}
        {item.error ? <p className="asset-error">{item.error}</p> : null}
        {item.status === "failed" && item.source === "local" ? (
          <button className="text-link" type="button" onClick={() => onRetry(item.localId)}>
            重试此文件
          </button>
        ) : null}
      </div>
    </article>
  );
}