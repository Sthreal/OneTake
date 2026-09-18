import { useEffect, useState } from "react";

import type { VoiceState, VoiceStatus } from "./types";

interface VoicePanelProps {
  state: VoiceState;
  canStart: boolean;
  isStarting: boolean;
  error: string | null;
  onStart: (input: { enabled: boolean; voiceId: string; language: "zh" | "en"; speed: number }) => void;
}

const STATUS_TEXT: Record<VoiceStatus, string> = {
  queued: "配音任务排队中",
  generating: "正在生成配音",
  ready: "配音已生成",
  failed: "配音生成失败",
};

const VOICES = [
  { id: "longxiaochun_v2", label: "龙小淳·女声" },
  { id: "longwan_v2", label: "龙婉·女声" },
  { id: "longcheng_v2", label: "龙橙·女声" },
];

export function VoicePanel({ state, canStart, isStarting, error, onStart }: VoicePanelProps) {
  const run = state.run;
  const [enabled, setEnabled] = useState(true);
  const [voiceId, setVoiceId] = useState("longxiaochun_v2");
  const [language, setLanguage] = useState<"zh" | "en">("zh");
  const [speed, setSpeed] = useState(1.0);

  useEffect(() => {
    if (!run) return;
    setEnabled(run.enabled);
    setVoiceId(run.voice_id);
    setLanguage(run.language);
    setSpeed(run.speed);
  }, [run?.run_id]);

  const status = run?.status;
  const working = status === "queued" || status === "generating";

  return (
    <section className="surface-card voice-card">
      <div className="section-heading">
        <div>
          <h2>商品配音</h2>
          <p>基于最终确认文案生成配音，默认使用 CosyVoice V2。</p>
        </div>
        <span className={"voice-status is-" + (status ?? "idle")}>
          {status ? STATUS_TEXT[status] : "等待生成"}
        </span>
      </div>

      {!working ? (
        <div className="voice-controls">
          <label className="voice-toggle">
            <input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />
            <span><strong>输出语音</strong><small>关闭后不生成用户可播放音频</small></span>
          </label>
          <label className="field compact-field">
            <span>音色</span>
            <select value={voiceId} onChange={(event) => setVoiceId(event.target.value)} disabled={!enabled}>
              {VOICES.map((voice) => <option value={voice.id} key={voice.id}>{voice.label}</option>)}
            </select>
          </label>
          <label className="field compact-field">
            <span>语言</span>
            <select value={language} onChange={(event) => setLanguage(event.target.value as "zh" | "en")} disabled={!enabled}>
              <option value="zh">中文</option>
              <option value="en">英文</option>
            </select>
          </label>
          <label className="field compact-field">
            <span>语速 <small>{speed.toFixed(1)}x</small></span>
            <input type="range" min="0.5" max="2" step="0.1" value={speed} onChange={(event) => setSpeed(Number(event.target.value))} disabled={!enabled} />
          </label>
          <div className="voice-actions">
            <button className="button button-primary" type="button" disabled={!canStart || isStarting} onClick={() => onStart({ enabled, voiceId, language, speed })}>
              {isStarting ? "正在创建任务…" : status === "ready" ? "重新生成配音" : "生成配音"}
            </button>
          </div>
        </div>
      ) : null}

      {working ? (
        <div className="voice-working">
          <span className="spinner" />
          <div><strong>{STATUS_TEXT[status]}</strong><p>页面会自动刷新，完成后可以试听。</p></div>
        </div>
      ) : null}

      {run?.status === "ready" ? (
        run.enabled && run.audio_url ? (
          <div className="voice-result">
            <div><strong>配音已生成</strong><span>{run.duration_seconds?.toFixed(1)} 秒 · {run.voice_id}</span></div>
            <audio controls src={run.audio_url} />
          </div>
        ) : (
          <div className="voice-skipped"><strong>配音输出已关闭</strong><p>本次不会向视频合成提供音频。</p></div>
        )
      ) : null}

      {status === "failed" || error ? (
        <div className="voice-error"><strong>配音未完成</strong><p>{error ?? run?.error_code ?? "请稍后重试"}</p></div>
      ) : null}
    </section>
  );
}
