import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { VideoPanel } from "./VideoPanel";
import type { VideoSegmentState } from "./types";

const plan = {
  plan_id: "vid_test",
  project_id: "prj_test",
  mode: "product" as const,
  template_id: "clean" as const,
  status: "completed" as const,
  duration_seconds: 18,
  width: 1080,
  height: 1920,
  fps: 30,
  voice_enabled: true,
  subtitle_enabled: true,
  provider: "mock-video",
  error_code: null,
  video_url: "http://localhost/final.mp4",
  created_at: "2026-09-18T00:00:00Z",
  updated_at: "2026-09-18T00:00:01Z",
  completed_at: "2026-09-18T00:00:01Z",
  batch_status: "idle" as const,
  batch_stop_requested: false,
};

const EMPTY_SEGMENTS: VideoSegmentState = { plan_id: null, segments: [] };

function renderPanel(overrides: Partial<Parameters<typeof VideoPanel>[0]> = {}) {
  const props = {
    state: { plan: null },
    output: null,
    canStart: true,
    voiceEnabled: true,
    subtitleEnabled: true,
    isStarting: false,
    error: null,
    estimate: null,
    segments: EMPTY_SEGMENTS,
    segmentBusy: false,
    onGenerate: vi.fn(),
    onGenerateSegment: vi.fn(),
    onAcceptSegment: vi.fn(),
    onRejectSegment: vi.fn(),
    onStartBatch: vi.fn(),
    onStopBatch: vi.fn(),
    onConfirmEstimate: vi.fn(),
    onCancelEstimate: vi.fn(),
    ...overrides,
  };
  render(<VideoPanel {...props} />);
  return props;
}

describe("VideoPanel", () => {
  it("submits the selected product template", async () => {
    const props = renderPanel();
    await userEvent.click(screen.getByRole("button", { name: /动态聚焦/ }));
    await userEvent.click(screen.getByRole("button", { name: "生成商品视频" }));
    expect(props.onGenerate).toHaveBeenCalledWith("product", "dynamic");
  });

  it("renders the completed video and download action", () => {
    renderPanel({ state: { plan } });
    expect(screen.getByText("成片已完成")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "下载 MP4" })).toHaveAttribute("href", "http://localhost/final.mp4");
  });

  it("shows the backend reason when regeneration is blocked", () => {
    renderPanel({ state: { plan: null }, canStart: true, error: "请先确认配音和字幕" });
    expect(screen.getByText("暂时不能生成视频")).toBeInTheDocument();
    expect(screen.getByText("请先确认配音和字幕")).toBeInTheDocument();
  });

  it("shows the real generation estimate before confirming", async () => {
    const props = renderPanel({
      estimate: {
        plan_id: "vid_estimate", mode: "product", template_id: "dynamic", duration_seconds: 18,
        is_paid: true, wan_clip_count: 4, wan_generated_seconds: 20, qwen_image_edit_calls: 1,
        shotstack_renders: 1, estimated_wan_cost: 3, estimated_known_cost: 3, estimated_cost_max: null,
        currency: "CNY", estimated_minutes: 4.5, confirmation_threshold: 5, requires_confirmation: true,
        missing_price_config: ["QWEN_IMAGE_EDIT_PRICE_PER_CALL", "SHOTSTACK_RENDER_PRICE"],
        price_notes: ["Qwen 图像编辑费用待核算"],
      },
    });
    expect(screen.getByText("确认真实生成")).toBeInTheDocument();
    expect(screen.getByText("Wan：4 段 / 20 秒")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "确认生成" }));
    expect(props.onConfirmEstimate).toHaveBeenCalledOnce();
  });

  it("renders the segment timeline and triggers batch generation", async () => {
    const segments: VideoSegmentState = {
      plan_id: "vid_test",
      segments: [
        {
          segment_id: "seg_0", plan_id: "vid_test", order_index: 1, scene_id: "scene_0",
          start_seconds: 0, end_seconds: 5, duration_seconds: 5, status: "planned",
          accepted_candidate_id: null, last_error: null, anchor_source: null, candidates: [],
        },
        {
          segment_id: "seg_1", plan_id: "vid_test", order_index: 2, scene_id: "scene_1",
          start_seconds: 5, end_seconds: 10, duration_seconds: 5, status: "accepted",
          accepted_candidate_id: "cand_1", last_error: null, anchor_source: "previous_tail",
          candidates: [
            {
              candidate_id: "cand_1", segment_id: "seg_1", order_index: 2, status: "accepted",
              provider: "wan-i2v", anchor_source: "previous_tail", video_url: "http://localhost/seg1.mp4",
              tail_frame_url: null, head_frame_url: null, anchor_candidate_id: "cand_0",
              duration_seconds: 5, width: 1080, height: 1920, fps: 30, error_code: null,
              created_at: "2026-10-11T00:00:00Z",
            },
          ],
        },
      ],
    };
    const props = renderPanel({ state: { plan }, segments });
    expect(screen.getByText("分段生成")).toBeInTheDocument();
    expect(screen.getByText("1/2 段已采用")).toBeInTheDocument();
    // 回归点：order_index 是 1 基，第一段必须显示「第 1 段」（修复前会因为 +1 显示成「第 2 段」）
    expect(screen.getByText("第 1 段")).toBeInTheDocument();
    expect(screen.getByText("第 2 段")).toBeInTheDocument();
    expect(screen.getByText("已使用上一段尾帧续写")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "一键续跑全片" }));
    expect(props.onStartBatch).toHaveBeenCalledOnce();
  });
});
