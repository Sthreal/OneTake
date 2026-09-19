import { useEffect, useState } from "react";

import type {
  OutputArtifact,
  ProductTemplateId,
  VideoMode,
  VideoEstimate,
  VideoPlanStatus,
  VideoState,
} from "./types";

interface VideoPanelProps {
  state: VideoState;
  output: OutputArtifact | null;
  canStart: boolean;
  voiceEnabled: boolean;
  subtitleEnabled: boolean;
  isStarting: boolean;
  error: string | null;
  estimate: VideoEstimate | null;
  onGenerate: (mode: VideoMode, templateId: ProductTemplateId | null) => void;
  onConfirmEstimate: () => void;
  onCancelEstimate: () => void;
}

const STATUS_TEXT: Record<VideoPlanStatus, string> = {
  plan_ready: "视频方案已就绪",
  video_generating: "正在生成基础视频",
  video_ready: "基础视频已完成",
  rendering: "正在合成字幕与音轨",
  completed: "成片已完成",
  failed: "视频生成失败",
};

const TEMPLATES: Array<{ id: ProductTemplateId; name: string; detail: string }> = [
  { id: "clean", name: "干净展示", detail: "白底居中，画面稳定" },
  { id: "dynamic", name: "动态聚焦", detail: "轻微淡入与节奏变化" },
  { id: "lifestyle", name: "生活氛围", detail: "留白柔和，适合种草" },
];

const ACTIVE_STATUSES = new Set<VideoPlanStatus>(["video_generating", "video_ready", "rendering"]);

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function currentStage(status: VideoPlanStatus): number {
  if (status === "completed") return 4;
  if (status === "rendering" || status === "video_ready") return 3;
  if (status === "video_generating") return 2;
  if (status === "plan_ready") return 1;
  return 0;
}

export function VideoPanel({
  state,
  output,
  canStart,
  voiceEnabled,
  subtitleEnabled,
  isStarting,
  error,
  estimate,
  onGenerate,
  onConfirmEstimate,
  onCancelEstimate,
}: VideoPanelProps) {
  const plan = state.plan;
  const [mode, setMode] = useState<VideoMode>("product");
  const [templateId, setTemplateId] = useState<ProductTemplateId>("clean");

  useEffect(() => {
    if (!plan) return;
    setMode(plan.mode);
    if (plan.template_id) setTemplateId(plan.template_id);
  }, [plan?.plan_id, plan?.mode, plan?.template_id]);

  const status = plan?.status ?? null;
  const isBusy = Boolean(status && ACTIVE_STATUSES.has(status));
  const isCompleted = status === "completed";
  const videoUrl = plan?.video_url ?? output?.download_url ?? null;
  const effectiveVoice = plan?.voice_enabled ?? voiceEnabled;
  const effectiveSubtitle = plan?.subtitle_enabled ?? subtitleEnabled;
  const stage = status ? currentStage(status) : 0;

  return (
    <section className="surface-card video-card">
      <div className="section-heading">
        <div>
          <h2>视频与成片</h2>
          <p>选择视频形式后生成 9:16 竖屏成片，配音与字幕跟随前面的确认结果。</p>
        </div>
        <span className={"video-status is-" + (status ?? "idle")}>{status ? STATUS_TEXT[status] : "等待生成"}</span>
      </div>

      {!canStart && !plan ? (
        <div className="video-locked">
          <span className="video-locked-icon">4</span>
          <div><strong>先完成配音与字幕确认</strong><p>确认后即可选择有人或无人模式生成成片。</p></div>
        </div>
      ) : null}

      <div className="video-mode-grid">
        <button
          className={"video-mode-option " + (mode === "avatar" ? "is-selected" : "")}
          type="button"
          aria-pressed={mode === "avatar"}
          onClick={() => setMode("avatar")}
        >
          <span className="video-mode-icon">人</span>
          <span><strong>有人讲解</strong><small>固定数字人口播，商品图保持清晰</small></span>
        </button>
        <button
          className={"video-mode-option " + (mode === "product" ? "is-selected" : "")}
          type="button"
          aria-pressed={mode === "product"}
          onClick={() => setMode("product")}
        >
          <span className="video-mode-icon">物</span>
          <span><strong>无人商品</strong><small>商品图动效与模板场景组合</small></span>
        </button>
      </div>

      {mode === "product" ? (
        <div className="video-template-grid">
          {TEMPLATES.map((template) => (
            <button
              className={"video-template-option " + (templateId === template.id ? "is-selected" : "")}
              type="button"
              aria-pressed={templateId === template.id}
              key={template.id}
              onClick={() => setTemplateId(template.id)}
            >
              <span className="template-preview" aria-hidden="true"><i /><b /></span>
              <strong>{template.name}</strong>
              <small>{template.detail}</small>
            </button>
          ))}
        </div>
      ) : null}

      <div className="video-output-summary">
        <span><i className={effectiveVoice ? "is-on" : ""} />配音 {effectiveVoice ? "开启" : "关闭"}</span>
        <span><i className={effectiveSubtitle ? "is-on" : ""} />字幕 {effectiveSubtitle ? "开启" : "关闭"}</span>
        <span>9:16</span>
        <span>1080 × 1920</span>
        <span>30 fps</span>
      </div>

      {plan && (isBusy || isCompleted) ? (
        <div className="video-progress" aria-label="视频生成进度">
          {[
            ["方案", "参数锁定"],
            ["视频", "基础画面"],
            ["渲染", "音频字幕"],
            ["成片", "预览下载"],
          ].map(([title, detail], index) => {
            const stateName = isCompleted || index < stage ? "done" : index === stage ? "active" : "locked";
            return (
              <div className={"video-progress-step is-" + stateName} key={title}>
                <span>{stateName === "done" ? "✓" : index + 1}</span>
                <div><strong>{title}</strong><small>{detail}</small></div>
              </div>
            );
          })}
        </div>
      ) : null}

      {isBusy ? (
        <div className="video-working"><span className="spinner" /><div><strong>{status ? STATUS_TEXT[status] : "正在生成"}</strong><p>页面会自动刷新，完成后展示成片。</p></div></div>
      ) : null}

      {isCompleted && videoUrl ? (
        <div className="video-result">
          <video controls playsInline preload="metadata" src={videoUrl} />
          <div className="video-result-copy">
            <div><strong>成片已生成</strong><span>{output ? `${formatBytes(output.size_bytes)} · ${output.duration_seconds.toFixed(1)}s` : `${plan?.duration_seconds.toFixed(1)}s`}</span></div>
            <div className="video-meta">
              <span>H.264</span>
              {output?.audio_codec ? <span>AAC</span> : null}
              {output?.video_width && output.video_height ? <span>{output.video_width} × {output.video_height}</span> : null}
            </div>
            <a className="button button-primary video-download" href={videoUrl} download={`onetake-${plan?.plan_id ?? "video"}.mp4`}>下载 MP4</a>
          </div>
        </div>
      ) : null}

      {estimate ? (
        <div className="video-estimate">
          <div className="video-estimate-heading">
            <strong>确认真实生成</strong>
            <span>提交后会产生供应商费用</span>
          </div>
          <div className="video-estimate-grid">
            <span>Wan：{estimate.wan_clip_count} 段 / {estimate.wan_generated_seconds} 秒</span>
            <span>Wan 费用：¥{estimate.estimated_wan_cost.toFixed(2)}</span>
            <span>Qwen 图像编辑：{estimate.qwen_image_edit_calls} 次</span>
            <span>Shotstack：{estimate.shotstack_renders} 次渲染</span>
            <span>预计耗时：约 {estimate.estimated_minutes.toFixed(1)} 分钟</span>
            <span>已知费用合计：¥{estimate.estimated_known_cost.toFixed(2)}</span>
          </div>
          {estimate.missing_price_config.length ? (
            <p className="video-estimate-note">待核算：{estimate.missing_price_config.join("、")}</p>
          ) : null}
          {estimate.price_notes.length ? <p className="video-estimate-note">{estimate.price_notes.join("；")}</p> : null}
          <div className="video-estimate-actions">
            <button className="button button-secondary" type="button" onClick={onCancelEstimate}>取消</button>
            <button className="button button-primary" type="button" disabled={isStarting} onClick={onConfirmEstimate}>确认生成</button>
          </div>
        </div>
      ) : null}

      {status === "failed" || error ? (
        <div className="video-error"><strong>{status === "failed" ? "视频生成失败" : "暂时不能生成视频"}</strong><p>{error ?? plan?.error_code ?? "请重试生成"}</p></div>
      ) : null}

      <div className="video-actions">
        <span>{canStart ? "生成后可在线预览并下载 MP4。" : "完成音频与字幕确认后解锁。"}</span>
        <button
          className="button button-primary"
          type="button"
          disabled={!canStart || isBusy || isStarting || Boolean(estimate)}
          onClick={() => onGenerate(mode, mode === "product" ? templateId : null)}
        >
          {isStarting ? "正在提交…" : isCompleted ? "重新生成" : status === "failed" ? "重试生成" : "生成商品视频"}
        </button>
      </div>
    </section>
  );
}
