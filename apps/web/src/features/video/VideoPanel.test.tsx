import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { VideoPanel } from "./VideoPanel";

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
};

describe("VideoPanel", () => {
  it("submits the selected product template", async () => {
    const onGenerate = vi.fn();
    render(<VideoPanel state={{ plan: null }} output={null} canStart voiceEnabled subtitleEnabled isStarting={false} error={null} estimate={null} onGenerate={onGenerate} onConfirmEstimate={vi.fn()} onCancelEstimate={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: /动态聚焦/ }));
    await userEvent.click(screen.getByRole("button", { name: "生成商品视频" }));
    expect(onGenerate).toHaveBeenCalledWith("product", "dynamic");
  });

  it("renders the completed video and download action", () => {
    render(<VideoPanel state={{ plan }} output={null} canStart voiceEnabled subtitleEnabled isStarting={false} error={null} estimate={null} onGenerate={vi.fn()} onConfirmEstimate={vi.fn()} onCancelEstimate={vi.fn()} />);
    expect(screen.getByText("成片已完成")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "下载 MP4" })).toHaveAttribute("href", "http://localhost/final.mp4");
  });
});

  it("shows the backend reason when regeneration is blocked", () => {
    render(<VideoPanel state={{ plan: null }} output={null} canStart isStarting={false} voiceEnabled subtitleEnabled error="请先确认配音和字幕" estimate={null} onGenerate={vi.fn()} onConfirmEstimate={vi.fn()} onCancelEstimate={vi.fn()} />);
    expect(screen.getByText("暂时不能生成视频")).toBeInTheDocument();
    expect(screen.getByText("请先确认配音和字幕")).toBeInTheDocument();
  });

  it("shows the real generation estimate before confirming", async () => {
    const onConfirmEstimate = vi.fn();
    const onCancelEstimate = vi.fn();
    const estimate = {
      plan_id: "vid_estimate",
      mode: "product" as const,
      template_id: "dynamic" as const,
      duration_seconds: 18,
      is_paid: true,
      wan_clip_count: 4,
      wan_generated_seconds: 20,
      qwen_image_edit_calls: 1,
      shotstack_renders: 1,
      estimated_wan_cost: 3,
      estimated_known_cost: 3,
      estimated_cost_max: null,
      currency: "CNY",
      estimated_minutes: 4.5,
      confirmation_threshold: 5,
      requires_confirmation: true,
      missing_price_config: ["QWEN_IMAGE_EDIT_PRICE_PER_CALL", "SHOTSTACK_RENDER_PRICE"],
      price_notes: ["Qwen 图像编辑费用待核算"],
    };
    render(<VideoPanel state={{ plan: null }} output={null} canStart voiceEnabled subtitleEnabled isStarting={false} error={null} estimate={estimate} onGenerate={vi.fn()} onConfirmEstimate={onConfirmEstimate} onCancelEstimate={onCancelEstimate} />);
    expect(screen.getByText("确认真实生成")).toBeInTheDocument();
    expect(screen.getByText("Wan：4 段 / 20 秒")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "确认生成" }));
    expect(onConfirmEstimate).toHaveBeenCalledOnce();
  });
