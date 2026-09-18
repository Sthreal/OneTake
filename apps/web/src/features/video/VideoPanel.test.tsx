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
    render(<VideoPanel state={{ plan: null }} output={null} canStart voiceEnabled subtitleEnabled isStarting={false} error={null} onGenerate={onGenerate} />);
    await userEvent.click(screen.getByRole("button", { name: /动态聚焦/ }));
    await userEvent.click(screen.getByRole("button", { name: "生成商品视频" }));
    expect(onGenerate).toHaveBeenCalledWith("product", "dynamic");
  });

  it("renders the completed video and download action", () => {
    render(<VideoPanel state={{ plan }} output={null} canStart voiceEnabled subtitleEnabled isStarting={false} error={null} onGenerate={vi.fn()} />);
    expect(screen.getByText("成片已完成")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "下载 MP4" })).toHaveAttribute("href", "http://localhost/final.mp4");
  });
});

  it("shows the backend reason when regeneration is blocked", () => {
    render(<VideoPanel state={{ plan: null }} output={null} canStart isStarting={false} voiceEnabled subtitleEnabled error="请先确认配音和字幕" onGenerate={vi.fn()} />);
    expect(screen.getByText("暂时不能生成视频")).toBeInTheDocument();
    expect(screen.getByText("请先确认配音和字幕")).toBeInTheDocument();
  });
