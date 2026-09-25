import { useEffect, useState } from "react";

import type { RecognitionState } from "./types";

interface RecognitionPanelProps {
  state: RecognitionState;
  readyAssetCount: number;
  isStarting: boolean;
  isConfirming: boolean;
  error: string | null;
  onStart: () => void;
  onConfirm: (assetId: string, candidateId: string) => void;
}

const STATUS_TEXT: Record<string, string> = {
  queued: "任务排队中",
  running: "正在识别商品主体",
  ready: "请确认识别结果",
  confirmed: "识别结果已确认",
  failed: "识别失败",
};

export function RecognitionPanel({ state, readyAssetCount, isStarting, isConfirming, error, onStart, onConfirm }: RecognitionPanelProps) {
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null);

  useEffect(() => {
    setSelectedCandidateId(state.candidates[0]?.candidate_id ?? null);
  }, [state.run?.run_id, state.candidates]);

  const run = state.run;
  const status = run?.status ?? "idle";
  const isWorking = status === "queued" || status === "running";
  const canStart = readyAssetCount > 0 && !run && !isStarting;

  return (
    <section className="surface-card recognition-card">
      <div className="section-heading">
        <div>
          <h2>商品识别</h2>
          <p>使用 Mock Provider 验证候选确认和 Pipeline 状态。</p>
        </div>
        <span className={"recognition-status is-" + status}>{STATUS_TEXT[status] ?? "等待开始"}</span>
      </div>

      {!run ? (
        <div className="recognition-empty">
          <p>{readyAssetCount > 0 ? "素材已准备，可以开始识别。" : "至少需要一张已完成上传的素材。"}</p>
          <button className="button button-primary" type="button" disabled={!canStart} onClick={onStart}>
            {isStarting ? "正在创建任务…" : "开始识别"}
          </button>
        </div>
      ) : null}

      {isWorking ? (
        <div className="recognition-working">
          <span className="spinner" />
          <strong>{STATUS_TEXT[status]}</strong>
          <p>任务会在后台执行，页面会自动刷新状态。</p>
        </div>
      ) : null}

      {status === "ready" ? (
        <div className="candidate-list">
          {state.candidates.map((candidate, index) => (
            <label className={"candidate-card " + (selectedCandidateId === candidate.candidate_id ? "is-selected" : "")} key={candidate.candidate_id}>
              <input
                type="radio"
                name="recognition-candidate"
                checked={selectedCandidateId === candidate.candidate_id}
                onChange={() => setSelectedCandidateId(candidate.candidate_id)}
              />
              <span className="candidate-index">{index + 1}</span>
              <span className="candidate-copy">
                <strong>{candidate.label}</strong>
                <small>置信度 {Math.round(candidate.confidence * 100)}%</small>
                <p>{candidate.reason}</p>
              </span>
            </label>
          ))}
          <button
            className="button button-primary"
            type="button"
            disabled={!selectedCandidateId || isConfirming}
            onClick={() => {
              const candidate = state.candidates.find((item) => item.candidate_id === selectedCandidateId);
              if (candidate) onConfirm(candidate.asset_id, candidate.candidate_id);
            }}
          >
            {isConfirming ? "正在确认…" : "确认商品主体"}
          </button>
        </div>
      ) : null}

      {status === "confirmed" ? (
        <div className="recognition-success">
          <span>✓</span>
          <div><strong>商品主体已确认</strong><p>后续识别模块可以直接替换为 Qwen-VL-Plus。</p></div>
        </div>
      ) : null}

      {status === "failed" || error ? (
        <div className="recognition-error">
          <strong>识别未完成</strong>
          <p>{error ?? run?.error_code ?? "请稍后重试"}</p>
          {!run || status === "failed" ? (
            <button className="button button-secondary" type="button" disabled={!readyAssetCount || isStarting} onClick={onStart}>重新识别</button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
