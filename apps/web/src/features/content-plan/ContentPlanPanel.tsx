import { useEffect, useState } from "react";

import type { ContentPlan, ContentScene } from "./types";

interface ContentPlanPanelProps {
  plan: ContentPlan | null;
  canStart: boolean;
  isGenerating: boolean;
  isSaving: boolean;
  isConfirming: boolean;
  error: string | null;
  onGenerate: () => void;
  onSave: (variantIndex: number, scenes: ContentScene[]) => void;
  onConfirm: () => void;
}

export function ContentPlanPanel({
  plan,
  canStart,
  isGenerating,
  isSaving,
  isConfirming,
  error,
  onGenerate,
  onSave,
  onConfirm,
}: ContentPlanPanelProps) {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [draftScenes, setDraftScenes] = useState<ContentScene[]>([]);

  useEffect(() => {
    if (!plan) {
      setSelectedIndex(0);
      setDraftScenes([]);
      return;
    }
    const index = Math.min(plan.selected_variant_index, plan.variants.length - 1);
    setSelectedIndex(index);
    setDraftScenes(plan.variants[index]?.scenes ?? []);
  }, [plan]);

  if (!plan) {
    return (
      <section className="surface-card content-plan-card">
        <div className="section-heading">
          <div>
            <h2>视频分镜</h2>
            <p>先生成 4–6 个场景，确认镜头和商品展示方式后再生成视频。</p>
          </div>
        </div>
        <div className="video-actions">
          <span>{canStart ? "系统会生成 clean、story、trend 三套方案。" : "完成配音和字幕确认后解锁。"}</span>
          <button className="button button-primary" type="button" disabled={!canStart || isGenerating} onClick={onGenerate}>
            {isGenerating ? "正在生成…" : "生成视频分镜"}
          </button>
        </div>
        {error ? <div className="video-error">{error}</div> : null}
      </section>
    );
  }

  const variant = plan.variants[selectedIndex];
  const dirty = draftScenes.some((scene, index) => scene.prompt !== variant?.scenes[index]?.prompt);

  function selectVariant(index: number) {
    if (plan?.status === "confirmed") return;
    setSelectedIndex(index);
    setDraftScenes(plan?.variants[index]?.scenes ?? []);
  }

  return (
    <section className="surface-card content-plan-card">
      <div className="section-heading">
        <div>
          <h2>视频分镜</h2>
          <p>{plan.total_duration_seconds.toFixed(1)} 秒 · {variant?.scenes.length ?? 0} 个场景 · {plan.provider}</p>
        </div>
        <span className={"video-status " + (plan.status === "confirmed" ? "is-completed" : "")}>
          {plan.status === "confirmed" ? "分镜已确认" : "分镜待确认"}
        </span>
      </div>

      <div className="content-plan-variants" role="tablist" aria-label="视频分镜方案">
        {plan.variants.map((item, index) => (
          <button
            className={"content-plan-variant " + (index === selectedIndex ? "is-selected" : "")}
            type="button"
            role="tab"
            aria-selected={index === selectedIndex}
            disabled={plan.status === "confirmed"}
            key={item.variant_id}
            onClick={() => selectVariant(index)}
          >
            <strong>{item.name}</strong>
            <small>{item.scenes.length} 个场景</small>
          </button>
        ))}
      </div>

      <div className="content-scene-list">
        {draftScenes.map((scene, index) => (
          <article className="content-scene" key={scene.scene_id}>
            <div className="content-scene-meta">
              <span>{scene.order}</span>
              <div>
                <strong>{scene.purpose}</strong>
                <small>{scene.start_seconds.toFixed(1)}–{scene.end_seconds.toFixed(1)}s</small>
              </div>
              <code>{scene.shot_type}</code>
            </div>
            <p>{scene.script_excerpt}</p>
            <label className="field compact-field">
              <span>镜头 Prompt</span>
              <textarea
                rows={3}
                value={scene.prompt}
                disabled={plan.status === "confirmed"}
                onChange={(event) => setDraftScenes((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, prompt: event.target.value } : item))}
              />
            </label>
            <div className="content-scene-tags">
              <span>{scene.overlay_product ? "商品图层已锁定" : "无商品图层"}</span>
              <span>{scene.background_style}</span>
            </div>
          </article>
        ))}
      </div>

      {error ? <div className="video-error">{error}</div> : null}

      <div className="video-actions">
        <span>{plan.status === "confirmed" ? "当前分镜已锁定，可重新生成新版本。" : "时间轴和商品事实由系统锁定，只可修改 Prompt。"}</span>
        <div className="inline-actions">
          <button className="button button-secondary" type="button" disabled={plan.status === "confirmed" || !dirty || isSaving} onClick={() => onSave(selectedIndex, draftScenes)}>
            {isSaving ? "保存中…" : "保存分镜"}
          </button>
          <button className="button button-primary" type="button" disabled={plan.status === "confirmed" || dirty || isConfirming} onClick={onConfirm}>
            {plan.status === "confirmed" ? "已确认" : isConfirming ? "确认中…" : "确认分镜"}
          </button>
        </div>
      </div>
    </section>
  );
}
