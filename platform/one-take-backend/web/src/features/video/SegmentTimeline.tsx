import type { SegmentStatus, VideoBatchStatus, VideoSegmentState } from "./types";

interface SegmentTimelineProps {
  segments: VideoSegmentState;
  busy: boolean;
  batchStatus?: VideoBatchStatus;
  onGenerate: (segmentId: string) => void;
  onAccept: (segmentId: string, candidateId: string) => void;
  onReject: (segmentId: string) => void;
  onStartBatch: () => void;
  onStopBatch: () => void;
}

const SEGMENT_STATUS_TEXT: Record<SegmentStatus, string> = {
  planned: "待生成",
  generating: "生成中",
  awaiting_review: "待确认",
  accepted: "已采用",
  failed: "失败",
};

const BATCH_STATUS_TEXT: Record<VideoBatchStatus, string> = {
  idle: "未开始",
  running: "全片生成中",
  stopped: "已停止，可续跑",
  done: "全片已完成",
  failed: "批量失败",
  interrupted: "已中断，可续跑",
};

function cls(prefix: string, value: string): string {
  return prefix + " is-" + value;
}

export function SegmentTimeline({
  segments,
  busy,
  batchStatus = "idle",
  onGenerate,
  onAccept,
  onReject,
  onStartBatch,
  onStopBatch,
}: SegmentTimelineProps) {
  const items = segments.segments;
  if (!items.length) {
    return (
      <div className="segment-timeline">
        <div className="section-heading">
          <div><h3>分段生成</h3><p>分镜确认后可逐段生成，后段自动承接前段尾帧。</p></div>
        </div>
        <div className="empty-state compact">当前方案没有可分段的分镜。</div>
      </div>
    );
  }
  const acceptedCount = items.filter((item) => item.accepted_candidate_id).length;
  const isRunning = batchStatus === "running";

  return (
    <div className="segment-timeline">
      <div className="section-heading">
        <div>
          <h3>分段生成</h3>
          <p>逐段生成并确认；后一段以上一段已采用候选的尾帧续写，改选会自动作废下游。</p>
        </div>
        <span className="count-chip">{acceptedCount}/{items.length} 段已采用</span>
      </div>

      <div className="segment-batch-bar">
        <span className={cls("segment-batch-status", batchStatus)}>{BATCH_STATUS_TEXT[batchStatus]}</span>
        <div className="segment-batch-actions">
          <button className="button button-primary" type="button" disabled={busy || isRunning} onClick={onStartBatch}>
            {acceptedCount > 0 && acceptedCount < items.length ? "一键续跑全片" : "一键生成全片"}
          </button>
          <button className="button button-secondary" type="button" disabled={!isRunning} onClick={onStopBatch}>停止</button>
        </div>
      </div>

      <ol className="segment-list">
        {items.map((segment) => {
          const accepted = segment.candidates.find((c) => c.candidate_id === segment.accepted_candidate_id) ?? null;
          const latest = segment.candidates.length ? segment.candidates[segment.candidates.length - 1] : null;
          const preview = accepted ?? latest;
          return (
            <li className={cls("segment-item", segment.status)} key={segment.segment_id}>
              <div className="segment-index">{segment.order_index + 1}</div>
              <div className="segment-body">
                <div className="segment-head">
                  <strong>第 {segment.order_index + 1} 段</strong>
                  <span className={cls("segment-status", segment.status)}>{SEGMENT_STATUS_TEXT[segment.status]}</span>
                  <small>{segment.duration_seconds.toFixed(1)}s · {segment.candidates.length} 个候选</small>
                </div>
                {preview?.video_url ? (
                  <video className="segment-preview" controls playsInline preload="metadata" src={preview.video_url} />
                ) : (
                  <div className="segment-preview segment-preview-empty">尚未生成</div>
                )}
                {accepted?.anchor_source === "previous_tail" ? (
                  <p className="segment-anchor-note">已使用上一段尾帧续写</p>
                ) : null}
                <div className="segment-actions">
                  <button className="button button-secondary" type="button" disabled={busy} onClick={() => onGenerate(segment.segment_id)}>
                    {segment.candidates.length ? "再生成一个候选" : "生成这一段"}
                  </button>
                  {latest && segment.accepted_candidate_id !== latest.candidate_id ? (
                    <button className="button button-primary" type="button" disabled={busy} onClick={() => onAccept(segment.segment_id, latest.candidate_id)}>
                      采用最新候选
                    </button>
                  ) : null}
                  {segment.accepted_candidate_id ? (
                    <button className="button button-ghost" type="button" disabled={busy} onClick={() => onReject(segment.segment_id)}>
                      取消采用
                    </button>
                  ) : null}
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
