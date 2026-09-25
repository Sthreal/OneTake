import { useEffect, useMemo, useState } from "react";

import type { EditScriptInput, GenerateScriptInput, ScriptState, ScriptStatus } from "./types";

interface ScriptPanelProps {
  state: ScriptState;
  canStart: boolean;
  isStarting: boolean;
  isSaving: boolean;
  isConfirming: boolean;
  error: string | null;
  onStart: (input: GenerateScriptInput) => void;
  onSave: (input: EditScriptInput) => void;
  onConfirm: () => void;
}

const STATUS_TEXT: Record<ScriptStatus, string> = {
  queued: "等待生成",
  generating: "正在生成文案",
  ready: "文案已生成，请确认",
  confirmed: "文案已确认",
  failed: "文案生成失败",
};

function splitLines(value: string): string[] {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
}

export function ScriptPanel({
  state,
  canStart,
  isStarting,
  isSaving,
  isConfirming,
  error,
  onStart,
  onSave,
  onConfirm,
}: ScriptPanelProps) {
  const version = state.version;
  const status = version?.status ?? "idle";
  const [painPoint, setPainPoint] = useState("");
  const [sellingPointsText, setSellingPointsText] = useState("");
  const [usageScenario, setUsageScenario] = useState("");
  const [offer, setOffer] = useState("");
  const [hook, setHook] = useState("");
  const [editedPainPoint, setEditedPainPoint] = useState("");
  const [editedSellingPointsText, setEditedSellingPointsText] = useState("");
  const [editedUsageScenario, setEditedUsageScenario] = useState("");
  const [cta, setCta] = useState("");

  useEffect(() => {
    if (!version) return;
    setPainPoint(version.facts.pain_point);
    setSellingPointsText(version.facts.selling_points.join("\n"));
    setUsageScenario(version.facts.usage_scenario);
    setOffer(version.facts.offer ?? "");
    setHook(version.hook);
    setEditedPainPoint(version.pain_point);
    setEditedSellingPointsText(version.selling_points.join("\n"));
    setEditedUsageScenario(version.usage_scenario);
    setCta(version.cta);
  }, [version?.version_id]);

  const isWorking = status === "queued" || status === "generating";
  const isReady = status === "ready" || status === "confirmed";
  const isDirty = useMemo(() => {
    if (!version) return false;
    return hook !== version.hook
      || editedPainPoint !== version.pain_point
      || editedSellingPointsText !== version.selling_points.join("\n")
      || editedUsageScenario !== version.usage_scenario
      || cta !== version.cta;
  }, [cta, editedPainPoint, editedSellingPointsText, editedUsageScenario, hook, version]);

  function generationInput(): GenerateScriptInput {
    return {
      painPoint: painPoint.trim(),
      sellingPoints: splitLines(sellingPointsText),
      usageScenario: usageScenario.trim(),
      offer: offer.trim() || null,
    };
  }

  function regenerate() {
    if (!version) return;
    onStart({
      painPoint: version.facts.pain_point,
      sellingPoints: version.facts.selling_points,
      usageScenario: version.facts.usage_scenario,
      offer: version.facts.offer,
    });
  }

  return (
    <section className="surface-card script-card">
      <div className="section-heading">
        <div>
          <h2>商品文案</h2>
          <p>只基于已确认事实生成约 20 秒的强带货中文口播文案。</p>
        </div>
        <span className={"script-status is-" + status}>
          {status === "idle" ? "等待生成" : STATUS_TEXT[status as ScriptStatus]}
        </span>
      </div>

      {!version || status === "failed" ? (
        <div className="script-facts-form">
          <label className="field">
            <span>商品痛点 <em>必填</em></span>
            <textarea value={painPoint} onChange={(event) => setPainPoint(event.target.value)} rows={2} maxLength={80} placeholder="例如：清洗麻烦、携带不方便" />
          </label>
          <label className="field">
            <span>已确认卖点 <em>每行一条</em></span>
            <textarea value={sellingPointsText} onChange={(event) => setSellingPointsText(event.target.value)} rows={3} placeholder={"例如：杯身可拆卸\n支持快速清洗"} />
          </label>
          <label className="field">
            <span>使用场景 <em>必填</em></span>
            <textarea value={usageScenario} onChange={(event) => setUsageScenario(event.target.value)} rows={2} maxLength={100} placeholder="例如：通勤、办公室、旅行途中" />
          </label>
          <label className="field">
            <span>优惠信息 <small>可选</small></span>
            <input value={offer} onChange={(event) => setOffer(event.target.value)} maxLength={80} placeholder="没有可以留空，不要填写未确认优惠" />
          </label>
          <div className="script-form-actions">
            <span>系统不会补充未提供的数字、销量或功效。</span>
            <button className="button button-primary" type="button" disabled={!canStart || isStarting} onClick={() => onStart(generationInput())}>
              {isStarting ? "正在创建任务…" : "生成文案"}
            </button>
          </div>
        </div>
      ) : null}

      {version && isWorking ? (
        <div className="script-working">
          <span className="spinner" />
          <div><strong>{STATUS_TEXT[version.status]}</strong><p>Qwen-VL-Plus 适配器正在根据主图和确认事实生成结构化文案。</p></div>
        </div>
      ) : null}

      {version && isReady ? (
        <div className="script-editor">
          <div className="script-facts-summary">
            <span>痛点：{version.facts.pain_point}</span>
            <span>场景：{version.facts.usage_scenario}</span>
            {version.facts.offer ? <span>优惠：{version.facts.offer}</span> : null}
          </div>
          <div className="script-edit-grid">
            <label className="field"><span>钩子</span><textarea value={hook} onChange={(event) => setHook(event.target.value)} rows={2} /></label>
            <label className="field"><span>痛点段</span><textarea value={editedPainPoint} onChange={(event) => setEditedPainPoint(event.target.value)} rows={2} /></label>
            <label className="field"><span>卖点段 <small>每行一条</small></span><textarea value={editedSellingPointsText} onChange={(event) => setEditedSellingPointsText(event.target.value)} rows={3} /></label>
            <label className="field"><span>使用场景段</span><textarea value={editedUsageScenario} onChange={(event) => setEditedUsageScenario(event.target.value)} rows={2} /></label>
            <label className="field script-cta-field"><span>CTA</span><textarea value={cta} onChange={(event) => setCta(event.target.value)} rows={2} /></label>
          </div>
          <div className="script-full-text"><span>完整口播文本</span><p>{version.full_text}</p></div>
          <div className="script-meta">
            <span>{version.character_count} 字</span>
            <span>约 {version.estimated_duration_seconds} 秒</span>
            <span>版本 {version.version_number}</span>
            <span>{version.status === "confirmed" ? "已确认" : "等待确认"}</span>
          </div>
          <div className="script-actions">
            <button className="button button-secondary" type="button" disabled={isStarting || isDirty} onClick={regenerate}>
              {isStarting ? "正在重新生成…" : "重新生成"}
            </button>
            <button
              className="button button-secondary"
              type="button"
              disabled={!isDirty || isSaving}
              onClick={() => onSave({ hook, painPoint: editedPainPoint, sellingPoints: splitLines(editedSellingPointsText), usageScenario: editedUsageScenario, cta })}
            >
              {isSaving ? "正在保存…" : "保存修改"}
            </button>
            <button className="button button-primary" type="button" disabled={isDirty || version.status === "confirmed" || isConfirming} onClick={onConfirm}>
              {version.status === "confirmed" ? "已确认" : isConfirming ? "正在确认…" : "确认文案"}
            </button>
          </div>
        </div>
      ) : null}

      {version?.status === "failed" || error ? (
        <div className="script-error">
          <div><strong>文案未完成</strong><p>{error ?? version?.error_code ?? "请稍后重试"}</p></div>
          <button className="button button-secondary" type="button" disabled={isStarting} onClick={regenerate}>
            {isStarting ? "正在重试…" : "重新生成"}
          </button>
        </div>
      ) : null}
    </section>
  );
}

