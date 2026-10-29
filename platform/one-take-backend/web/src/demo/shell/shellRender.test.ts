import { beforeEach, describe, expect, it, vi } from "vitest";

import type { VideoPlan, VideoState } from "../../features/video/types";
import {
  describeShellRender,
  enqueueShellRender,
  presenterIsAbsent,
  resetShellRenderFlight,
  shellVoiceCopy,
  type ShellRenderClient,
} from "./shellRender";

function plan(partial: Partial<VideoPlan>): VideoPlan {
  return {
    plan_id: "vid_1",
    project_id: "prj_skin",
    mode: "product",
    template_id: "clean",
    status: "plan_ready",
    duration_seconds: 15,
    width: 1080,
    height: 1920,
    fps: 30,
    voice_enabled: true,
    subtitle_enabled: true,
    provider: "mock-video",
    error_code: null,
    video_url: null,
    path: "one_shot",
    created_at: "2026-10-29T00:00:00Z",
    updated_at: "2026-10-29T00:00:00Z",
    completed_at: null,
    ...partial,
  };
}

function state(value: VideoPlan | null): VideoState {
  return { plan: value };
}

describe("壳层声线文案", () => {
  it("有出镜人是 TTS + 库选，没有人是旁白字幕，两边都不承诺克隆或原声对口型", () => {
    expect(presenterIsAbsent(null)).toBe(true);
    expect(presenterIsAbsent("")).toBe(true);
    expect(presenterIsAbsent("无人")).toBe(true);
    expect(presenterIsAbsent("premade:linxiao")).toBe(false);

    const withPerson = shellVoiceCopy("premade:linxiao");
    expect(withPerson.label).toBe("TTS + 库选数字人");
    expect(withPerson.detail).toContain("不是克隆声");
    expect(withPerson.detail).toContain("不做原声对口型");
    expect(withPerson.detail).not.toMatch(/live Wan/);

    const absent = shellVoiceCopy(null);
    expect(absent.label).toBe("旁白字幕");
    expect(absent.detail).toContain("旁白加字幕");
    expect(shellVoiceCopy("无人").label).toBe("旁白字幕");
  });
});

describe("渲染三态", () => {
  it("排队、可播、失败分开，mock 成片写明不是 live Wan", () => {
    expect(describeShellRender(null, null).headline).toBe("尚未提交渲染");
    expect(describeShellRender(plan({ status: "video_generating" }), null)).toMatchObject({
      phase: "queued",
      headline: "排队中",
      mockReady: false,
      playableUrl: null,
    });
    const ready = describeShellRender(
      plan({ status: "completed", provider: "mock-video", video_url: "https://example.com/from-plan.mp4" }),
      "https://example.com/mock.mp4",
    );
    expect(ready).toMatchObject({
      phase: "playable",
      headline: "可播预览",
      mockReady: true,
      playableUrl: "https://example.com/mock.mp4",
    });
    expect(ready.detail).toContain("Mock 成片就绪");
    expect(ready.detail).toContain("不是 live Wan");
    const placeholder = describeShellRender(plan({ status: "completed", provider: "mock-video", video_url: null }), null);
    expect(placeholder).toMatchObject({ phase: "playable", mockReady: true, playableUrl: null });
    expect(placeholder.detail).toContain("Mock 成片就绪");
    expect(describeShellRender(plan({ status: "failed", error_code: "QUEUE_UNAVAILABLE" }), null)).toMatchObject({
      phase: "failed",
      headline: "失败可重试",
      playableUrl: null,
      mockReady: false,
    });
  });
});

describe("enqueueShellRender", () => {
  beforeEach(() => {
    resetShellRenderFlight();
  });

  it("没有方案时按工作台 one_shot：预估 → 批准费用 → requestVideo，不走 batch", async () => {
    const calls: string[] = [];
    let current = plan({ status: "plan_ready" });
    const client = {
      getVideo: vi.fn(async () => {
        calls.push("getVideo");
        return state(calls.includes("createVideoPlan") ? current : null);
      }),
      createVideoPlan: vi.fn(async () => {
        calls.push("createVideoPlan");
        current = plan({ status: "plan_ready", path: "one_shot" });
        return state(current);
      }),
      getVideoEstimate: vi.fn(async () => {
        calls.push("getVideoEstimate");
        return { plan_id: "vid_1", is_paid: false };
      }),
      approveCost: vi.fn(async () => {
        calls.push("approveCost");
        return { plan_id: "vid_1" };
      }),
      requestVideo: vi.fn(async () => {
        calls.push("requestVideo");
        current = plan({ status: "video_generating", path: "one_shot" });
        return state(current);
      }),
      startVideoBatch: vi.fn(async () => {
        calls.push("startVideoBatch");
        return state(current);
      }),
      getOutput: vi.fn(async () => {
        calls.push("getOutput");
        return null;
      }),
    } as unknown as ShellRenderClient;

    const view = await enqueueShellRender("prj_skin", client);
    expect(view.headline).toBe("排队中");
    expect(view.mockReady).toBe(false);
    expect(calls).toEqual(["getVideo", "createVideoPlan", "getVideoEstimate", "approveCost", "requestVideo", "getOutput"]);
    expect(client.startVideoBatch).not.toHaveBeenCalled();
    expect(client.createVideoPlan).toHaveBeenCalledWith("prj_skin", "product", "clean", "one_shot");
    expect(client.approveCost).toHaveBeenCalledWith("prj_skin", "vid_1");
  });

  it("已有 segmented 方案时走 startVideoBatch，与工作台分段出片相同", async () => {
    const current = plan({ status: "plan_ready", path: "segmented", provider: "mock-video" });
    const client = {
      getVideo: vi.fn(async () => state(current)),
      createVideoPlan: vi.fn(),
      getVideoEstimate: vi.fn(async () => ({ plan_id: "vid_1", is_paid: true })),
      approveCost: vi.fn(async () => ({ plan_id: "vid_1" })),
      requestVideo: vi.fn(),
      startVideoBatch: vi.fn(async () => state(plan({
        status: "completed",
        path: "segmented",
        provider: "mock-video",
        batch_status: "done",
        video_url: "https://example.com/mock.mp4",
      }))),
      getOutput: vi.fn(async () => ({ download_url: "https://example.com/mock.mp4" })),
    } as unknown as ShellRenderClient;

    const view = await enqueueShellRender("prj_skin", client);
    expect(client.createVideoPlan).not.toHaveBeenCalled();
    expect(client.requestVideo).not.toHaveBeenCalled();
    expect(client.approveCost).toHaveBeenCalledWith("prj_skin", "vid_1");
    expect(client.startVideoBatch).toHaveBeenCalledWith("prj_skin");
    expect(view).toMatchObject({ phase: "playable", mockReady: true, playableUrl: "https://example.com/mock.mp4" });
    expect(view.detail).toContain("Mock 成片就绪");
  });

  it("失败方案不会自动再提交，重试才再次批准并出片", async () => {
    const failed = plan({ status: "failed", error_code: "GATE_FAILED", path: "one_shot" });
    const client = {
      getVideo: vi.fn(async () => state(failed)),
      createVideoPlan: vi.fn(),
      getVideoEstimate: vi.fn(async () => ({ plan_id: "vid_1", is_paid: false })),
      approveCost: vi.fn(async () => ({ plan_id: "vid_1" })),
      requestVideo: vi.fn(async () => state(plan({ status: "video_generating" }))),
      startVideoBatch: vi.fn(),
      getOutput: vi.fn(async () => null),
    } as unknown as ShellRenderClient;

    const first = await enqueueShellRender("prj_skin", client);
    expect(first.headline).toBe("失败可重试");
    expect(client.requestVideo).not.toHaveBeenCalled();

    const second = await enqueueShellRender("prj_skin", client, { force: true });
    expect(second.headline).toBe("排队中");
    expect(client.approveCost).toHaveBeenCalledTimes(1);
    expect(client.requestVideo).toHaveBeenCalledTimes(1);
  });
});
