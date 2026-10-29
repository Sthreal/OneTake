import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SubtitleVersion, VoiceRun } from "../../features/audio-subtitle/types";
import type { ContentPlan, ContentPlanStatus } from "../../features/content-plan/types";
import type { VideoPlan, VideoState } from "../../features/video/types";
import {
  describeShellRender,
  enqueueShellRender,
  presenterIsAbsent,
  resetShellRenderFlight,
  SHELL_VOICE_REQUEST,
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
    path: "segmented",
    created_at: "2026-10-29T00:00:00Z",
    updated_at: "2026-10-29T00:00:00Z",
    completed_at: null,
    ...partial,
  };
}

function state(value: VideoPlan | null): VideoState {
  return { plan: value };
}

function voiceRun(partial: Partial<VoiceRun> = {}): VoiceRun {
  return {
    run_id: "voi_1",
    project_id: "prj_skin",
    script_version_id: "scr_1",
    status: "ready",
    enabled: true,
    subtitle_enabled: true,
    provider: "mock-cosyvoice-v2",
    model: "cosyvoice-v2",
    voice_id: "longxiaochun_v2",
    language: "zh",
    speed: 1,
    duration_seconds: 14.2,
    audio_url: null,
    error_code: null,
    created_at: "2026-10-29T00:00:00Z",
    updated_at: "2026-10-29T00:00:00Z",
    completed_at: "2026-10-29T00:00:00Z",
    confirmed_at: null,
    ...partial,
  };
}

function subtitleVersion(partial: Partial<SubtitleVersion> = {}): SubtitleVersion {
  return {
    subtitle_id: "sub_1",
    project_id: "prj_skin",
    script_version_id: "scr_1",
    voice_run_id: "voi_1",
    status: "ready",
    enabled: true,
    language: "zh",
    segments: [{ index: 1, text: "这只水壶通勤也能装", start: 0, end: 14.2 }],
    srt_url: null,
    error_code: null,
    created_at: "2026-10-29T00:00:00Z",
    updated_at: "2026-10-29T00:00:00Z",
    completed_at: "2026-10-29T00:00:00Z",
    confirmed_at: null,
    ...partial,
  };
}

function contentPlan(status: ContentPlanStatus): ContentPlan {
  return {
    plan_id: "cpl_1",
    project_id: "prj_skin",
    status,
    provider: "rules",
    model: "rules-v1",
    selected_variant_index: 0,
    total_duration_seconds: 14,
    variants: [],
    error_code: null,
    created_at: "2026-10-29T00:00:00Z",
    updated_at: "2026-10-29T00:00:00Z",
    confirmed_at: status === "confirmed" ? "2026-10-29T00:00:00Z" : null,
  };
}

const noWait = { sleep: async () => {}, intervalMs: 0, maxPolls: 5 };

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

    expect(shellVoiceCopy("premade:linxiao", "talking_head").label).toBe("TTS + 库选数字人");
    expect(shellVoiceCopy("chr_zhou", "multi_angle").label).toBe("TTS + 库选数字人");
    expect(shellVoiceCopy(null, "talking_head").label).toBe("旁白字幕");
    expect(shellVoiceCopy(null, "multi_angle").label).toBe("旁白字幕");
    expect(shellVoiceCopy("premade:linxiao", "product_only").label).toBe("旁白字幕");
    expect(shellVoiceCopy("premade:linxiao", "product_only").detail).toContain("旁白加字幕");
    expect(shellVoiceCopy("premade:linxiao", "product_only").detail).not.toMatch(/唇形已同步|克隆声驱动|live Wan/);
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
      headline: "成片可播",
      mockReady: true,
      playableUrl: "https://example.com/mock.mp4",
    });
    expect(ready.detail).toContain("Mock 成片就绪");
    expect(ready.detail).toContain("不是 live Wan");
    const placeholder = describeShellRender(plan({ status: "completed", provider: "mock-video", video_url: null }), null);
    expect(placeholder).toMatchObject({ phase: "playable", headline: "待渲染", mockReady: false, playableUrl: null });
    expect(placeholder.detail).toContain("不提供预览");
    expect(placeholder.detail).not.toContain("可播预览");
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

  it("没有方案时建 product+segmented：预估 → 批准费用 → requestVideo，不走 batch，也不因缺分镜 VIDEO_CONFLICT", async () => {
    const calls: string[] = [];
    let current = plan({ status: "plan_ready" });
    const client = {
      getVideo: vi.fn(async () => {
        calls.push("getVideo");
        return state(calls.includes("createVideoPlan") ? current : null);
      }),
      createVideoPlan: vi.fn(async () => {
        calls.push("createVideoPlan");
        current = plan({ status: "plan_ready", path: "segmented" });
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
        if (current.path !== "segmented") {
          current = plan({ status: "failed", path: current.path, error_code: "VIDEO_CONFLICT" });
          return state(current);
        }
        current = plan({ status: "video_generating", path: "segmented" });
        return state(current);
      }),
      startVideoBatch: vi.fn(async () => {
        calls.push("startVideoBatch");
        current = plan({ status: "failed", path: "segmented", error_code: "VIDEO_CONFLICT" });
        return state(current);
      }),
      getOutput: vi.fn(async () => {
        calls.push("getOutput");
        return null;
      }),
      getVoice: vi.fn(async () => {
        calls.push("getVoice");
        return { run: voiceRun({ status: "confirmed", confirmed_at: "2026-10-29T00:00:00Z" }) };
      }),
      getSubtitle: vi.fn(async () => {
        calls.push("getSubtitle");
        return { version: subtitleVersion({ status: "confirmed", confirmed_at: "2026-10-29T00:00:00Z" }) };
      }),
      requestVoice: vi.fn(),
      requestSubtitle: vi.fn(),
      confirmAudioSubtitle: vi.fn(),
      getContentPlan: vi.fn(async () => {
        calls.push("getContentPlan");
        return contentPlan("confirmed");
      }),
      generateContentPlan: vi.fn(async () => {
        calls.push("generateContentPlan");
        return contentPlan("ready");
      }),
      confirmContentPlan: vi.fn(async () => {
        calls.push("confirmContentPlan");
        return contentPlan("confirmed");
      }),
    } as unknown as ShellRenderClient;

    const view = await enqueueShellRender("prj_skin", client);
    expect(view.headline).toBe("排队中");
    expect(view.mockReady).toBe(false);
    expect(view.errorCode).toBeNull();
    expect(view.detail).not.toContain("VIDEO_CONFLICT");
    expect(view.detail).not.toContain("CONTENT_QA_CONFLICT");
    expect(view.detail).not.toContain("请先确认视频分镜");
    expect(calls).toEqual([
      "getVideo",
      "getVoice",
      "getSubtitle",
      "getContentPlan",
      "createVideoPlan",
      "getVideoEstimate",
      "approveCost",
      "requestVideo",
      "getOutput",
    ]);
    expect(client.requestVoice).not.toHaveBeenCalled();
    expect(client.requestSubtitle).not.toHaveBeenCalled();
    expect(client.confirmAudioSubtitle).not.toHaveBeenCalled();
    expect(client.generateContentPlan).not.toHaveBeenCalled();
    expect(client.confirmContentPlan).not.toHaveBeenCalled();
    expect(client.startVideoBatch).not.toHaveBeenCalled();
    expect(client.createVideoPlan).toHaveBeenCalledWith("prj_skin", "product", "clean", "segmented");
    expect(client.requestVideo).toHaveBeenCalledWith("prj_skin");
    expect(client.approveCost).toHaveBeenCalledWith("prj_skin", "vid_1");
  });

  it("已有 segmented 方案仍走 requestVideo，不走要求确认分镜的 batch", async () => {
    const current = plan({ status: "plan_ready", path: "segmented", provider: "mock-video" });
    const client = {
      getVideo: vi.fn(async () => state(current)),
      createVideoPlan: vi.fn(),
      getVideoEstimate: vi.fn(async () => ({ plan_id: "vid_1", is_paid: true })),
      approveCost: vi.fn(async () => ({ plan_id: "vid_1" })),
      requestVideo: vi.fn(async () => state(plan({
        status: "completed",
        path: "segmented",
        provider: "mock-video",
        video_url: "https://example.com/mock.mp4",
      }))),
      startVideoBatch: vi.fn(async () => state(plan({
        status: "failed",
        path: "segmented",
        error_code: "VIDEO_CONFLICT",
      }))),
      getOutput: vi.fn(async () => ({ download_url: "https://example.com/mock.mp4" })),
      getVoice: vi.fn(),
      requestVoice: vi.fn(),
      confirmAudioSubtitle: vi.fn(),
      getContentPlan: vi.fn(),
      generateContentPlan: vi.fn(),
      confirmContentPlan: vi.fn(),
    } as unknown as ShellRenderClient;

    const view = await enqueueShellRender("prj_skin", client);
    expect(client.createVideoPlan).not.toHaveBeenCalled();
    expect(client.getVoice).not.toHaveBeenCalled();
    expect(client.requestVoice).not.toHaveBeenCalled();
    expect(client.getContentPlan).not.toHaveBeenCalled();
    expect(client.generateContentPlan).not.toHaveBeenCalled();
    expect(client.confirmContentPlan).not.toHaveBeenCalled();
    expect(client.startVideoBatch).not.toHaveBeenCalled();
    expect(client.requestVideo).toHaveBeenCalledWith("prj_skin");
    expect(client.approveCost).toHaveBeenCalledWith("prj_skin", "vid_1");
    expect(view).toMatchObject({ phase: "playable", mockReady: true, playableUrl: "https://example.com/mock.mp4", errorCode: null });
    expect(view.detail).toContain("Mock 成片就绪");
    expect(view.detail).not.toContain("VIDEO_CONFLICT");
    expect(view.detail).not.toContain("CONTENT_QA_CONFLICT");
    expect(view.detail).not.toContain("请先确认视频分镜");
  });

  it("失败方案不会自动再提交，重试才再次批准并出片", async () => {
    const failed = plan({ status: "failed", error_code: "GATE_FAILED", path: "segmented" });
    const client = {
      getVideo: vi.fn(async () => state(failed)),
      createVideoPlan: vi.fn(),
      getVideoEstimate: vi.fn(async () => ({ plan_id: "vid_1", is_paid: false })),
      approveCost: vi.fn(async () => ({ plan_id: "vid_1" })),
      requestVideo: vi.fn(async () => state(plan({ status: "video_generating", path: "segmented" }))),
      startVideoBatch: vi.fn(async () => state(plan({ status: "failed", path: "segmented", error_code: "VIDEO_CONFLICT" }))),
      getOutput: vi.fn(async () => null),
      getVoice: vi.fn(),
      requestVoice: vi.fn(),
      getContentPlan: vi.fn(),
      generateContentPlan: vi.fn(),
      confirmContentPlan: vi.fn(),
    } as unknown as ShellRenderClient;

    const first = await enqueueShellRender("prj_skin", client);
    expect(first.headline).toBe("失败可重试");
    expect(client.requestVideo).not.toHaveBeenCalled();

    const second = await enqueueShellRender("prj_skin", client, { force: true });
    expect(second.headline).toBe("排队中");
    expect(second.errorCode).toBeNull();
    expect(second.detail).not.toContain("VIDEO_CONFLICT");
    expect(second.errorCode).not.toBe("CONTENT_QA_CONFLICT");
    expect(second.detail).not.toContain("CONTENT_QA_CONFLICT");
    expect(second.detail).not.toContain("请先确认视频分镜");
    expect(client.approveCost).toHaveBeenCalledTimes(1);
    expect(client.requestVideo).toHaveBeenCalledTimes(1);
    expect(client.startVideoBatch).not.toHaveBeenCalled();
    expect(client.getVoice).not.toHaveBeenCalled();
    expect(client.requestVoice).not.toHaveBeenCalled();
    expect(client.getContentPlan).not.toHaveBeenCalled();
    expect(client.generateContentPlan).not.toHaveBeenCalled();
    expect(client.confirmContentPlan).not.toHaveBeenCalled();
  });

  it("配音字幕未确认时先生成并确认，Mock 入队后不再出现「请先确认配音」", async () => {
    const calls: string[] = [];
    let confirmed = false;
    let voiceReads = 0;
    let subtitleReads = 0;
    const client = {
      getVideo: vi.fn(async () => state(calls.includes("createVideoPlan") ? plan({ status: "plan_ready" }) : null)),
      createVideoPlan: vi.fn(async () => {
        calls.push("createVideoPlan");
        if (!confirmed) throw new Error("请先确认配音和字幕");
        return state(plan({ status: "plan_ready", path: "segmented" }));
      }),
      getVideoEstimate: vi.fn(async () => ({ plan_id: "vid_1", is_paid: false })),
      approveCost: vi.fn(async () => ({ plan_id: "vid_1" })),
      requestVideo: vi.fn(async () => state(plan({ status: "video_generating", path: "segmented", provider: "mock-video" }))),
      startVideoBatch: vi.fn(async () => state(plan({ status: "failed", path: "segmented", error_code: "VIDEO_CONFLICT" }))),
      getOutput: vi.fn(async () => null),
      getVoice: vi.fn(async () => {
        voiceReads += 1;
        if (voiceReads === 1) return { run: null };
        return { run: voiceRun({ status: "ready", duration_seconds: 14.2 }) };
      }),
      requestVoice: vi.fn(async () => {
        calls.push("requestVoice");
        return { run: voiceRun({ status: "queued", duration_seconds: null }) };
      }),
      getSubtitle: vi.fn(async () => {
        subtitleReads += 1;
        if (subtitleReads === 1) return { version: null };
        if (subtitleReads === 2) return { version: subtitleVersion({ status: "generating", segments: [] }) };
        return { version: subtitleVersion({ status: "ready" }) };
      }),
      requestSubtitle: vi.fn(async () => {
        calls.push("requestSubtitle");
        return { version: subtitleVersion({ status: "queued", segments: [] }) };
      }),
      confirmAudioSubtitle: vi.fn(async () => {
        calls.push("confirmAudioSubtitle");
        confirmed = true;
      }),
      getContentPlan: vi.fn(async () => {
        calls.push("getContentPlan");
        return contentPlan("confirmed");
      }),
      generateContentPlan: vi.fn(),
      confirmContentPlan: vi.fn(),
    } as unknown as ShellRenderClient;

    const view = await enqueueShellRender("prj_skin", client, noWait);
    expect(view).toMatchObject({ phase: "queued", headline: "排队中", errorCode: null });
    expect(view.detail).not.toContain("请先确认配音");
    expect(view.detail).not.toContain("CONTENT_QA_CONFLICT");
    expect(view.detail).not.toContain("请先确认视频分镜");
    expect(view.detail).not.toContain("VIDEO_CONFLICT");
    expect(view.detail).toContain("Mock 渲染已入队");
    expect(calls).toEqual(["requestVoice", "requestSubtitle", "confirmAudioSubtitle", "getContentPlan", "createVideoPlan"]);
    expect(client.generateContentPlan).not.toHaveBeenCalled();
    expect(client.confirmContentPlan).not.toHaveBeenCalled();
    expect(client.requestVoice).toHaveBeenCalledWith("prj_skin", SHELL_VOICE_REQUEST);
    expect(client.confirmAudioSubtitle).toHaveBeenCalledWith("prj_skin");
    expect(client.createVideoPlan).toHaveBeenCalledWith("prj_skin", "product", "clean", "segmented");
    expect(client.startVideoBatch).not.toHaveBeenCalled();
    expect(client.requestVideo).toHaveBeenCalledWith("prj_skin");
  });

  it("配音已在排队时不再重复请求，字幕为空则不代按、也不建方案", async () => {
    const client = {
      getVideo: vi.fn(async () => state(null)),
      createVideoPlan: vi.fn(async () => {
        throw new Error("请先确认配音和字幕");
      }),
      getVideoEstimate: vi.fn(),
      approveCost: vi.fn(),
      requestVideo: vi.fn(),
      startVideoBatch: vi.fn(),
      getOutput: vi.fn(),
      getVoice: vi.fn()
        .mockResolvedValueOnce({ run: voiceRun({ status: "queued", duration_seconds: null }) })
        .mockResolvedValueOnce({ run: voiceRun({ status: "ready", duration_seconds: 14.2 }) }),
      requestVoice: vi.fn(),
      getSubtitle: vi.fn(async () => ({ version: subtitleVersion({ status: "ready", segments: [] }) })),
      requestSubtitle: vi.fn(),
      confirmAudioSubtitle: vi.fn(),
    } as unknown as ShellRenderClient;

    await expect(enqueueShellRender("prj_skin", client, noWait)).rejects.toThrow(/字幕分段为空/);
    expect(client.requestVoice).not.toHaveBeenCalled();
    expect(client.requestSubtitle).not.toHaveBeenCalled();
    expect(client.confirmAudioSubtitle).not.toHaveBeenCalled();
    expect(client.createVideoPlan).not.toHaveBeenCalled();
  });

  it("配音已确认、字幕仍是 ready 时直接确认，再进入成片可播", async () => {
    let confirmed = false;
    const client = {
      getVideo: vi.fn(async () => state(confirmed ? plan({ status: "plan_ready" }) : null)),
      createVideoPlan: vi.fn(async () => {
        if (!confirmed) throw new Error("请先确认配音和字幕");
        return state(plan({ status: "plan_ready" }));
      }),
      getVideoEstimate: vi.fn(async () => ({ plan_id: "vid_1", is_paid: false })),
      approveCost: vi.fn(async () => ({ plan_id: "vid_1" })),
      requestVideo: vi.fn(async () => state(plan({
        status: "completed",
        provider: "mock-video",
        video_url: "https://example.com/mock.mp4",
      }))),
      startVideoBatch: vi.fn(async () => state(plan({ status: "failed", error_code: "VIDEO_CONFLICT" }))),
      getOutput: vi.fn(async () => ({ download_url: "https://example.com/mock.mp4" })),
      getVoice: vi.fn(async () => ({ run: voiceRun({ status: "confirmed", confirmed_at: "2026-10-29T00:00:00Z" }) })),
      requestVoice: vi.fn(),
      getSubtitle: vi.fn(async () => ({ version: subtitleVersion({ status: "ready" }) })),
      requestSubtitle: vi.fn(),
      confirmAudioSubtitle: vi.fn(async () => {
        confirmed = true;
      }),
      getContentPlan: vi.fn(async () => contentPlan("confirmed")),
      generateContentPlan: vi.fn(),
      confirmContentPlan: vi.fn(),
    } as unknown as ShellRenderClient;

    const view = await enqueueShellRender("prj_skin", client, noWait);
    expect(view).toMatchObject({
      phase: "playable",
      headline: "成片可播",
      mockReady: true,
      playableUrl: "https://example.com/mock.mp4",
    });
    expect(view.detail).not.toContain("请先确认配音");
    expect(view.detail).not.toContain("CONTENT_QA_CONFLICT");
    expect(view.detail).not.toContain("请先确认视频分镜");
    expect(view.detail).not.toContain("VIDEO_CONFLICT");
    expect(view.detail).toContain("不是 live Wan");
    expect(client.requestVoice).not.toHaveBeenCalled();
    expect(client.requestSubtitle).not.toHaveBeenCalled();
    expect(client.confirmAudioSubtitle).toHaveBeenCalledWith("prj_skin");
    expect(client.generateContentPlan).not.toHaveBeenCalled();
    expect(client.confirmContentPlan).not.toHaveBeenCalled();
    expect(client.startVideoBatch).not.toHaveBeenCalled();
    expect(client.requestVideo).toHaveBeenCalledWith("prj_skin");
    expect(client.createVideoPlan).toHaveBeenCalledWith("prj_skin", "product", "clean", "segmented");
  });

  it("缺分镜时先 generate+confirm，再 createVideoPlan，入队视图不含 CONTENT_QA_CONFLICT", async () => {
    const calls: string[] = [];
    let storyboard: ContentPlanStatus | null = null;
    const client = {
      getVideo: vi.fn(async () => state(calls.includes("createVideoPlan") ? plan({ status: "plan_ready" }) : null)),
      createVideoPlan: vi.fn(async () => {
        calls.push("createVideoPlan");
        if (storyboard !== "confirmed") throw new Error("请先确认视频分镜");
        return state(plan({ status: "plan_ready", path: "segmented" }));
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
        if (storyboard !== "confirmed") {
          return state(plan({ status: "failed", path: "segmented", error_code: "CONTENT_QA_CONFLICT" }));
        }
        return state(plan({ status: "video_generating", path: "segmented", provider: "mock-video" }));
      }),
      startVideoBatch: vi.fn(async () => state(plan({ status: "failed", path: "segmented", error_code: "VIDEO_CONFLICT" }))),
      getOutput: vi.fn(async () => {
        calls.push("getOutput");
        return null;
      }),
      getVoice: vi.fn(async () => {
        calls.push("getVoice");
        return { run: voiceRun({ status: "confirmed", confirmed_at: "2026-10-29T00:00:00Z" }) };
      }),
      requestVoice: vi.fn(),
      getSubtitle: vi.fn(async () => {
        calls.push("getSubtitle");
        return { version: subtitleVersion({ status: "confirmed", confirmed_at: "2026-10-29T00:00:00Z" }) };
      }),
      requestSubtitle: vi.fn(),
      confirmAudioSubtitle: vi.fn(),
      getContentPlan: vi.fn(async () => {
        calls.push("getContentPlan");
        return storyboard ? contentPlan(storyboard) : null;
      }),
      generateContentPlan: vi.fn(async () => {
        calls.push("generateContentPlan");
        storyboard = "ready";
        return contentPlan("ready");
      }),
      confirmContentPlan: vi.fn(async () => {
        calls.push("confirmContentPlan");
        storyboard = "confirmed";
        return contentPlan("confirmed");
      }),
    } as unknown as ShellRenderClient;

    const view = await enqueueShellRender("prj_skin", client);
    expect(view).toMatchObject({ phase: "queued", headline: "排队中", errorCode: null });
    expect(view.detail).not.toContain("CONTENT_QA_CONFLICT");
    expect(view.detail).not.toContain("请先确认视频分镜");
    expect(view.detail).not.toContain("VIDEO_CONFLICT");
    expect(view.detail).toContain("Mock 渲染已入队");
    expect(calls).toEqual([
      "getVoice",
      "getSubtitle",
      "getContentPlan",
      "generateContentPlan",
      "confirmContentPlan",
      "createVideoPlan",
      "getVideoEstimate",
      "approveCost",
      "requestVideo",
      "getOutput",
    ]);
    expect(client.generateContentPlan).toHaveBeenCalledWith("prj_skin");
    expect(client.confirmContentPlan).toHaveBeenCalledWith("prj_skin");
    expect(client.confirmContentPlan).toHaveBeenCalledTimes(1);
    expect(client.createVideoPlan).toHaveBeenCalledWith("prj_skin", "product", "clean", "segmented");
    expect(client.requestVideo).toHaveBeenCalledWith("prj_skin");
    expect(client.startVideoBatch).not.toHaveBeenCalled();
    expect(client.requestVoice).not.toHaveBeenCalled();
    expect(client.confirmAudioSubtitle).not.toHaveBeenCalled();
  });

  it("分镜已是 ready 时只 confirm，不重复 generate", async () => {
    const calls: string[] = [];
    let storyboard: ContentPlanStatus = "ready";
    const client = {
      getVideo: vi.fn(async () => state(calls.includes("createVideoPlan") ? plan({ status: "plan_ready" }) : null)),
      createVideoPlan: vi.fn(async () => {
        calls.push("createVideoPlan");
        if (storyboard !== "confirmed") throw new Error("请先确认视频分镜");
        return state(plan({ status: "plan_ready", path: "segmented" }));
      }),
      getVideoEstimate: vi.fn(async () => ({ plan_id: "vid_1", is_paid: false })),
      approveCost: vi.fn(async () => ({ plan_id: "vid_1" })),
      requestVideo: vi.fn(async () => {
        if (storyboard !== "confirmed") {
          return state(plan({ status: "failed", path: "segmented", error_code: "CONTENT_QA_CONFLICT" }));
        }
        return state(plan({ status: "completed", path: "segmented", provider: "mock-video", video_url: "https://example.com/mock.mp4" }));
      }),
      startVideoBatch: vi.fn(),
      getOutput: vi.fn(async () => ({ download_url: "https://example.com/mock.mp4" })),
      getVoice: vi.fn(async () => ({ run: voiceRun({ status: "confirmed", confirmed_at: "2026-10-29T00:00:00Z" }) })),
      requestVoice: vi.fn(),
      getSubtitle: vi.fn(async () => ({ version: subtitleVersion({ status: "confirmed", confirmed_at: "2026-10-29T00:00:00Z" }) })),
      requestSubtitle: vi.fn(),
      confirmAudioSubtitle: vi.fn(),
      getContentPlan: vi.fn(async () => {
        calls.push("getContentPlan");
        return contentPlan(storyboard);
      }),
      generateContentPlan: vi.fn(async () => {
        calls.push("generateContentPlan");
        return contentPlan("ready");
      }),
      confirmContentPlan: vi.fn(async () => {
        calls.push("confirmContentPlan");
        storyboard = "confirmed";
        return contentPlan("confirmed");
      }),
    } as unknown as ShellRenderClient;

    const view = await enqueueShellRender("prj_skin", client);
    expect(view).toMatchObject({
      phase: "playable",
      headline: "成片可播",
      errorCode: null,
      mockReady: true,
    });
    expect(view.detail).not.toContain("CONTENT_QA_CONFLICT");
    expect(view.detail).not.toContain("请先确认视频分镜");
    expect(calls).toEqual(["getContentPlan", "confirmContentPlan", "createVideoPlan"]);
    expect(client.generateContentPlan).not.toHaveBeenCalled();
    expect(client.confirmContentPlan).toHaveBeenCalledTimes(1);
    expect(client.confirmContentPlan).toHaveBeenCalledWith("prj_skin");
    expect(client.startVideoBatch).not.toHaveBeenCalled();
    expect(client.requestVideo).toHaveBeenCalledWith("prj_skin");
  });
});
