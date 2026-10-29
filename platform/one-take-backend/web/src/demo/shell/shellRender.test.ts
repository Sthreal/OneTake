import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SubtitleVersion, VoiceRun } from "../../features/audio-subtitle/types";
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
    } as unknown as ShellRenderClient;

    const view = await enqueueShellRender("prj_skin", client);
    expect(view.headline).toBe("排队中");
    expect(view.mockReady).toBe(false);
    expect(calls).toEqual([
      "getVideo",
      "getVoice",
      "getSubtitle",
      "createVideoPlan",
      "getVideoEstimate",
      "approveCost",
      "requestVideo",
      "getOutput",
    ]);
    expect(client.requestVoice).not.toHaveBeenCalled();
    expect(client.requestSubtitle).not.toHaveBeenCalled();
    expect(client.confirmAudioSubtitle).not.toHaveBeenCalled();
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
      getVoice: vi.fn(),
      requestVoice: vi.fn(),
      confirmAudioSubtitle: vi.fn(),
    } as unknown as ShellRenderClient;

    const view = await enqueueShellRender("prj_skin", client);
    expect(client.createVideoPlan).not.toHaveBeenCalled();
    expect(client.getVoice).not.toHaveBeenCalled();
    expect(client.requestVoice).not.toHaveBeenCalled();
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
      getVoice: vi.fn(),
      requestVoice: vi.fn(),
    } as unknown as ShellRenderClient;

    const first = await enqueueShellRender("prj_skin", client);
    expect(first.headline).toBe("失败可重试");
    expect(client.requestVideo).not.toHaveBeenCalled();

    const second = await enqueueShellRender("prj_skin", client, { force: true });
    expect(second.headline).toBe("排队中");
    expect(client.approveCost).toHaveBeenCalledTimes(1);
    expect(client.requestVideo).toHaveBeenCalledTimes(1);
    expect(client.getVoice).not.toHaveBeenCalled();
    expect(client.requestVoice).not.toHaveBeenCalled();
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
        return state(plan({ status: "plan_ready", path: "one_shot" }));
      }),
      getVideoEstimate: vi.fn(async () => ({ plan_id: "vid_1", is_paid: false })),
      approveCost: vi.fn(async () => ({ plan_id: "vid_1" })),
      requestVideo: vi.fn(async () => state(plan({ status: "video_generating", provider: "mock-video" }))),
      startVideoBatch: vi.fn(),
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
    } as unknown as ShellRenderClient;

    const view = await enqueueShellRender("prj_skin", client, noWait);
    expect(view).toMatchObject({ phase: "queued", headline: "排队中" });
    expect(view.detail).not.toContain("请先确认配音");
    expect(view.detail).toContain("Mock 渲染已入队");
    expect(calls).toEqual(["requestVoice", "requestSubtitle", "confirmAudioSubtitle", "createVideoPlan"]);
    expect(client.requestVoice).toHaveBeenCalledWith("prj_skin", SHELL_VOICE_REQUEST);
    expect(client.confirmAudioSubtitle).toHaveBeenCalledWith("prj_skin");
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

  it("配音已确认、字幕仍是 ready 时直接确认，再进入可播预览", async () => {
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
      startVideoBatch: vi.fn(),
      getOutput: vi.fn(async () => ({ download_url: "https://example.com/mock.mp4" })),
      getVoice: vi.fn(async () => ({ run: voiceRun({ status: "confirmed", confirmed_at: "2026-10-29T00:00:00Z" }) })),
      requestVoice: vi.fn(),
      getSubtitle: vi.fn(async () => ({ version: subtitleVersion({ status: "ready" }) })),
      requestSubtitle: vi.fn(),
      confirmAudioSubtitle: vi.fn(async () => {
        confirmed = true;
      }),
    } as unknown as ShellRenderClient;

    const view = await enqueueShellRender("prj_skin", client, noWait);
    expect(view).toMatchObject({
      phase: "playable",
      headline: "可播预览",
      mockReady: true,
      playableUrl: "https://example.com/mock.mp4",
    });
    expect(view.detail).not.toContain("请先确认配音");
    expect(view.detail).toContain("不是 live Wan");
    expect(client.requestVoice).not.toHaveBeenCalled();
    expect(client.requestSubtitle).not.toHaveBeenCalled();
    expect(client.confirmAudioSubtitle).toHaveBeenCalledWith("prj_skin");
    expect(client.createVideoPlan).toHaveBeenCalledTimes(1);
  });
});
