import { describe, expect, it } from "vitest";

import {
  AUTO_APPROVE_POLICY,
  keyframeReadyFor,
  summarizeKeyframes,
  resumeStageFromStatus,
  stepIndexFromStatus,
  gateNeedsHuman,
  keyframeFloor,
  pickKeyframeCandidate,
  pickRecognitionCandidate,
  voiceSubtitleAutoApprovable,
  oneShotEligibility,
  ONE_SHOT_LIMITS,
} from "./policy";

const candidate = (id: string, confidence: number) => ({ candidate_id: id, asset_id: "ast_" + id, confidence });

describe("A1 识别代按", () => {
  it("最高置信度够高且与第二名拉开 → 自动采纳", () => {
    const decision = pickRecognitionCandidate([candidate("a", 0.91), candidate("b", 0.4)]);
    expect(decision.auto).toBe(true);
    if (decision.auto) expect(decision.value.candidate_id).toBe("a");
  });

  it("没有候选 / 置信度太低 / 前两名太接近 → 一律打断", () => {
    expect(pickRecognitionCandidate([]).auto).toBe(false);
    expect(pickRecognitionCandidate([candidate("a", AUTO_APPROVE_POLICY.recognitionConfidenceFloor - 0.01)]).auto).toBe(false);
    expect(pickRecognitionCandidate([candidate("a", 0.7), candidate("b", 0.68)]).auto).toBe(false);
  });
});

describe("A5 关键帧代按", () => {
  it("取第一个过线候选；网格档门槛比单帧档低", () => {
    const slot = {
      scene_id: "scene_1", order: 1, mode: "grid",
      candidates: [
        { keyframe_id: "k1", status: "rejected", product_match: 0.9, text_intact: true, issues: ["旧候选"] },
        { keyframe_id: "k2", status: "ready", product_match: 0.55, text_intact: true, issues: [] },
      ],
    };
    const decision = pickKeyframeCandidate(slot, "grid");
    expect(decision.auto).toBe(true);
    if (decision.auto) expect(decision.value.keyframe_id).toBe("k2");
    expect(keyframeFloor("grid")).toBeLessThan(keyframeFloor("integrated"));
  });

  it("文字损坏的候选即使分数够也不采纳；一镜全不过线就打断", () => {
    const broken = {
      scene_id: "scene_1", order: 1, mode: "integrated",
      candidates: [{ keyframe_id: "k1", status: "ready", product_match: 0.9, text_intact: false, issues: ["包装文字变形"] }],
    };
    expect(pickKeyframeCandidate(broken, "integrated").auto).toBe(false);
    expect(pickKeyframeCandidate({ ...broken, candidates: [] }, "integrated").auto).toBe(false);
  });
});

describe("A4 配音字幕代按", () => {
  it("时长偏差在容差内 → 自动；偏差过大 / 无时长 / 无字幕 → 打断", () => {
    expect(voiceSubtitleAutoApprovable(18.5, 5, 18).auto).toBe(true);
    expect(voiceSubtitleAutoApprovable(30, 5, 18).auto).toBe(false);
    expect(voiceSubtitleAutoApprovable(null, 5, 18).auto).toBe(false);
    expect(voiceSubtitleAutoApprovable(18, 0, 18).auto).toBe(false);
  });
});

describe("A6 交付门", () => {
  const check = (id: string, level: string) => ({ id, level, label: id, message: "" });

  it("全 ok → 自动过；有 warn → 必须人确认；fail → 阻断", () => {
    expect(gateNeedsHuman({ status: "ok", download_allowed: true, checks: [check("spec", "ok")] }).auto).toBe(true);
    expect(gateNeedsHuman({ status: "warn", download_allowed: true, checks: [check("silence", "warn")] }).auto).toBe(false);
    expect(gateNeedsHuman({ status: "fail", download_allowed: false, checks: [check("spec", "fail")] }).auto).toBe(false);
    expect(gateNeedsHuman(null).auto).toBe(false);
  });
});

describe("进度清单映射（对标 ClipForge 进度卡）", () => {
  it("后端状态依次点亮清单；未知状态如实不点亮", () => {
    expect(stepIndexFromStatus("recognizing")).toBe(2);
    expect(stepIndexFromStatus("audio_subtitle_confirmed")).toBe(5);
    expect(stepIndexFromStatus("content_plan_ready")).toBe(6);
    expect(stepIndexFromStatus("video_generating")).toBe(7);
    expect(stepIndexFromStatus("failed")).toBe(-1);
    expect(stepIndexFromStatus(null)).toBe(-1);
  });

  it("清单顺序必须单调递增（画面上是依次亮起）", () => {
    const order = ["recognizing", "matting", "script_generating", "voice_ready", "content_plan_ready", "video_generating"]
      .map((status) => stepIndexFromStatus(status));
    expect(order).toEqual([...order].sort((a, b) => a - b));
  });
});

describe("按 project_id 恢复：状态 → 屏", () => {
  it("前 4 段还在跑 → 继续轮询；分镜就绪/已确认 → 审核页；已成片 → 成片页；未知 → 如实不猜", () => {
    expect(resumeStageFromStatus("recognizing")).toBe("poll");
    expect(resumeStageFromStatus("audio_subtitle_confirmed")).toBe("review");   // 前 4 段跑完 = 进审核页
    expect(resumeStageFromStatus("content_plan_ready")).toBe("review");
    expect(resumeStageFromStatus("content_plan_confirmed")).toBe("review");
    expect(resumeStageFromStatus("video_generating")).toBe("review");
    expect(resumeStageFromStatus("completed")).toBe("done");
    expect(resumeStageFromStatus("failed")).toBe("retry");        // 失败不是死路：可重读方案后重试
    expect(resumeStageFromStatus("interrupted")).toBe("retry");
    expect(resumeStageFromStatus(null)).toBe("unknown");
  });
});

describe("关键帧等待条件（只等当前镜）", () => {
  const slots = [
    { scene_id: "scene_1", accepted: null, candidates: [{ id: 1, status: "ready" }] },
    { scene_id: "scene_2", accepted: null, candidates: [] },
    { scene_id: "scene_3", accepted: { id: 9 }, candidates: [] },
  ];
  it("有候选或已采纳 → 就绪；其它镜没候选不影响", () => {
    expect(keyframeReadyFor(slots, "scene_1")).toBe(true);
    expect(keyframeReadyFor(slots, "scene_2")).toBe(false);
    expect(keyframeReadyFor(slots, "scene_3")).toBe(true);
    expect(keyframeReadyFor(slots, "scene_9")).toBe(false);
  });
});

describe("候选状态（2026-10-15 实测死锁：挑到 rejected 候选 → 后端拒绝 → 无限重生成）", () => {
  const slot = {
    scene_id: "scene_1", order: 1, mode: "grid",
    candidates: [
      { keyframe_id: "old_1", status: "rejected", product_match: 0.924, text_intact: true, issues: [] },
      { keyframe_id: "old_2", status: "rejected", product_match: 0.924, text_intact: true, issues: [] },
      { keyframe_id: "newest", status: "ready", product_match: 0.924, text_intact: true, issues: [] },
    ],
  };

  it("只从 ready 里挑，且优先最新的（挑 rejected 会被后端拒：该候选未通过质检，不能采用）", () => {
    const decision = pickKeyframeCandidate(slot, "grid");
    expect(decision.auto).toBe(true);
    if (decision.auto) expect(decision.value.keyframe_id).toBe("newest");
  });

  it("全是被拒绝的候选 → 不硬挑，如实报'没有可用候选'", () => {
    const allRejected = { ...slot, candidates: slot.candidates.map((c) => ({ ...c, status: "rejected" })) };
    const decision = pickKeyframeCandidate(allRejected, "grid");
    expect(decision.auto).toBe(false);
    if (!decision.auto) expect(decision.reason).toContain("可用");
  });

  it("等待条件也要求出现 ready（只有 rejected 时不能继续）", () => {
    expect(keyframeReadyFor([{ scene_id: "scene_1", accepted: null, candidates: [{ status: "rejected" }] }], "scene_1")).toBe(false);
    expect(keyframeReadyFor([{ scene_id: "scene_1", accepted: null, candidates: [{ status: "ready" }] }], "scene_1")).toBe(true);
  });
});

describe("关键帧汇总（成片页卡片用）", () => {
  const slots = [
    { scene_id: "s1", order: 1, accepted: { product_match: 0.873, mode: "grid" } },
    { scene_id: "s2", order: 2, accepted: { product_match: 0.831, mode: "integrated" } },   // ← 走了单帧回退
    { scene_id: "s3", order: 3, accepted: null },
  ];

  it("统计采纳数/平均分，并如实标出发生回退的镜", () => {
    const s = summarizeKeyframes(slots, "grid");
    expect(s.total).toBe(3);
    expect(s.accepted).toBe(2);
    expect(s.averageMatch).toBeCloseTo(0.852, 3);
    expect(s.fellBackScenes).toEqual([2]);
    expect(s.gridMode).toBe(true);
  });

  it("顶层不是九宫格档时，不谎报回退；无已采纳时不谎报平均分", () => {
    const s = summarizeKeyframes(slots, "integrated");
    expect(s.gridMode).toBe(false);
    expect(s.fellBackScenes).toEqual([]);
    expect(summarizeKeyframes([{ scene_id: "s1", order: 1, accepted: null }], "grid").averageMatch).toBeNull();
  });
});

describe("S3 小白「一次生成整片」的能力上限", () => {
  it("15 秒 / 4 个分镜 → 可一键出片", () => {
    const result = oneShotEligibility({ durationSeconds: 15, shotCount: 4 });
    expect(result.allowed).toBe(true);
    expect(result.reasons).toEqual([]);
    expect(result.message).toBe("");
  });

  it("16 秒（时长超限）→ 拦住并说清原因", () => {
    const result = oneShotEligibility({ durationSeconds: 16, shotCount: 4 });
    expect(result.allowed).toBe(false);
    expect(result.reasons).toEqual(["duration-over-limit"]);
    expect(result.message).toContain("16 秒");
    expect(result.message).toContain("进导演模式");
  });

  it("5 个分镜（镜数超限）→ 拦住", () => {
    const result = oneShotEligibility({ durationSeconds: 14, shotCount: 5 });
    expect(result.allowed).toBe(false);
    expect(result.reasons).toEqual(["shots-over-limit"]);
    expect(result.message).toContain("分镜 5 个");
  });

  it("两条同时超限 → 两条原因都报，且文案里没有任何金额", () => {
    const result = oneShotEligibility({ durationSeconds: 18, shotCount: 6 });
    expect(result.reasons).toEqual(["duration-over-limit", "shots-over-limit"]);
    expect(result.message).not.toMatch(/[¥￥]|\d+\s*元/);
    expect(ONE_SHOT_LIMITS).toEqual({ maxSeconds: 15, maxShots: 4 });
  });
});
