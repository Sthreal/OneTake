import { useEffect, useState } from "react";

import type { SubtitleSegment, SubtitleState, SubtitleStatus } from "./types";

interface SubtitlePanelProps {
  state: SubtitleState;
  canStart: boolean;
  isSaving: boolean;
  isConfirming: boolean;
  error: string | null;
  onSave: (segments: SubtitleSegment[]) => void;
  onConfirm: () => void;
}

const STATUS_TEXT: Record<SubtitleStatus, string> = {
  queued: "等待生成字幕", generating: "正在生成字幕时间轴", ready: "字幕已生成",
  confirmed: "字幕已确认", failed: "字幕生成失败",
};

export function SubtitlePanel({ state, canStart, isSaving, isConfirming, error, onSave, onConfirm }: SubtitlePanelProps) {
  const version = state.version;
  const [texts, setTexts] = useState<Record<number, string>>({});

  useEffect(() => {
    setTexts(Object.fromEntries((version?.segments ?? []).map((segment) => [segment.index, segment.text])));
  }, [version?.subtitle_id, version?.segments]);

  const status = version?.status;
  const working = status === "queued" || status === "generating";
  const dirty = Boolean(version && version.segments.some((segment) => (texts[segment.index] ?? "") !== segment.text));
  const displaySegments: SubtitleSegment[] = version ? version.segments.map((segment) => ({ ...segment, text: texts[segment.index] ?? segment.text })) : [];

  return (
    <section className="surface-card subtitle-card">
      <div className="section-heading">
        <div><h2>字幕</h2><p>字幕时间轴以最终配音时长为基准，支持编辑后重新配音。</p></div>
        <span className={"subtitle-status is-" + (status ?? "idle")}>{status ? STATUS_TEXT[status] : "等待生成"}</span>
      </div>

      {working ? <div className="subtitle-working"><span className="spinner" /><div><strong>{STATUS_TEXT[status]}</strong><p>页面会自动刷新。</p></div></div> : null}

      {version?.status === "ready" || version?.status === "confirmed" ? (
        version.enabled ? (
          <>
            <div className="subtitle-list">
              {displaySegments.map((segment) => (
                <label className="subtitle-row" key={segment.index}>
                  <span>{segment.index}<small>{segment.start.toFixed(1)}–{segment.end.toFixed(1)}s</small></span>
                  <textarea value={segment.text} rows={2} onChange={(event) => setTexts((current) => ({ ...current, [segment.index]: event.target.value }))} />
                </label>
              ))}
            </div>
            <div className="subtitle-actions">
              {version.srt_url ? <a href={version.srt_url} target="_blank" rel="noreferrer">下载 SRT</a> : null}
              <button className="button button-secondary" type="button" disabled={!dirty || isSaving || !canStart} onClick={() => onSave(displaySegments)}>{isSaving ? "保存中…" : "保存并重新配音"}</button>
              <button className="button button-primary" type="button" disabled={dirty || version.status === "confirmed" || isConfirming} onClick={onConfirm}>{version.status === "confirmed" ? "已确认" : isConfirming ? "正在确认…" : "确认字幕"}</button>
            </div>
          </>
        ) : <div className="subtitle-skipped"><strong>字幕输出已关闭</strong><p>本次不会向合成流程提供 SRT 或字幕层。</p></div>
      ) : null}

      {status === "failed" || error ? <div className="subtitle-error"><strong>字幕未完成</strong><p>{error ?? version?.error_code ?? "请稍后重试"}</p></div> : null}
    </section>
  );
}
