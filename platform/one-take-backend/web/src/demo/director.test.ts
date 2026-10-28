import { describe, expect, it } from "vitest";

import { DIRECTOR_STEPS, formatElapsed, qualitySummary, purposeBadge, repairHeadline, segmentStatusLabel, stepEnabled, stepProgressHint } from "./director";

describe("导演模式纯逻辑", () => {
  it("第一步是**输入**（导演模式与小白并存，能自己输入商品图/链接），后面才是 4 个工作步骤", () => {
    expect(DIRECTOR_STEPS.map((step) => step.label)).toEqual(["输入", "分镜", "素材", "合成", "交付"]);
    expect(stepEnabled("intake", { hasPlan: false, hasSegments: false, hasFinal: false })).toBe(true);
  });

  it("职能徽章：已知 purpose 有中文标签，未知的原样显示（不猜）", () => {
    expect(purposeBadge("hook").label).toBe("钩子");
    expect(purposeBadge("cta").tone).toBe("cta");
    expect(purposeBadge("weird_new_purpose")).toEqual({ label: "weird_new_purpose", tone: "plain" });
    expect(purposeBadge(null).label).toBe("分镜");
  });

  it("质量摘要：缺数据说未测，不编数字", () => {
    expect(qualitySummary(null)).toEqual(["质量指标未生成"]);
    const summary = qualitySummary({
      product_match: null,
      text_intact: null,
      keyframe_fallback: null,
      duration_delta_seconds: null,
      symptom: null,
    });
    expect(summary).toEqual(["商品相似度未测", "文字未测"]);
  });

  it("质量摘要：有数据时给具体数字与提示", () => {
    const summary = qualitySummary({
      product_match: 0.881,
      text_intact: true,
      keyframe_fallback: "pixel_lock",
      duration_delta_seconds: -0.8,
      symptom: "text_blurry",
    });
    expect(summary).toContain("商品相似度 0.881");
    expect(summary).toContain("文字完好");
    expect(summary.some((item) => item.includes("pixel_lock"))).toBe(true);
    expect(summary).toContain("时长偏差 -0.8s");
    expect(summary).toContain("症状式返修产物");
  });

  it("时长偏差小于半秒不报（避免噪声）", () => {
    const summary = qualitySummary({
      product_match: 0.9,
      text_intact: true,
      keyframe_fallback: null,
      duration_delta_seconds: 0.2,
      symptom: null,
    });
    expect(summary.some((item) => item.includes("时长偏差"))).toBe(false);
  });

  it("修复头条：没有问题不吓人，有问题先说必须处理的条数", () => {
    expect(repairHeadline(null)).toBe("没有需要处理的问题");
    expect(repairHeadline({ gate_status: "ok", actions: [] })).toBe("没有需要处理的问题");
    expect(
      repairHeadline({
        gate_status: "warn",
        actions: [{ level: "fail" }, { level: "warn" }, { level: "warn" }],
      }),
    ).toBe("1 项必须处理、2 项待确认");
  });

  it("步骤可用性只看前置有没有", () => {
    expect(stepEnabled("storyboard", { hasPlan: false, hasSegments: false, hasFinal: false })).toBe(false);
    expect(stepEnabled("compose", { hasPlan: true, hasSegments: false, hasFinal: false })).toBe(false);
    expect(stepEnabled("compose", { hasPlan: true, hasSegments: true, hasFinal: false })).toBe(true);
    expect(stepEnabled("delivery", { hasPlan: true, hasSegments: true, hasFinal: false })).toBe(false);
  });
});

describe("每一步底部的「做完没有 / 下一步点哪」（用户三次卡在「没有往下的按钮」）", () => {
  const base = {
    step: "assets" as const,
    hasProject: true,
    contentPlanStatus: "confirmed",
    keyframeTotal: 4,
    keyframeAccepted: 4,
    segmentTotal: 4,
    segmentAccepted: 0,
    hasOutput: false,
  };

  it("素材步：4/4 采纳后必须明说「去合成」", () => {
    expect(stepProgressHint(base)).toContain("4/4 镜已采纳");
    expect(stepProgressHint(base)).toContain("合成");
  });

  it("素材步：没采纳完要说清是硬前置（分段需要首帧）", () => {
    const hint = stepProgressHint({ ...base, keyframeAccepted: 2 });
    expect(hint).toContain("2/4");
    expect(hint).toContain("首帧");
  });

  it("分镜步：ready≠confirmed —— 点不出按钮的坑就在这里，提示必须点名那一步", () => {
    expect(stepProgressHint({ ...base, step: "storyboard", contentPlanStatus: "ready" })).toContain("还没确认");
    expect(stepProgressHint({ ...base, step: "storyboard", contentPlanStatus: "confirmed" })).toContain("已确认");
  });

  it("合成步：逐段推进的进度要说清楚，最后一段才合成", () => {
    const hint = stepProgressHint({ ...base, step: "compose", segmentAccepted: 2 });
    expect(hint).toContain("2/4");
    expect(hint).toContain("逐段推进");
  });

  it("交付步：没成片要说回去哪一步", () => {
    expect(stepProgressHint({ ...base, step: "delivery" })).toContain("合成");
  });
});
describe("分段状态要给人看的中文（原样显示英文 = 用户以为坏了）", () => {
  it("已知状态有中文口径", () => {
    expect(segmentStatusLabel("planned")).toBe("待生成");
    expect(segmentStatusLabel("generating")).toBe("生成中");
    expect(segmentStatusLabel("awaiting_review")).toBe("待采用");
    expect(segmentStatusLabel("accepted")).toBe("已采用");
    expect(segmentStatusLabel("failed")).toBe("失败");
  });

  it("未知状态原样显示、空值说未知 —— 不猜不编", () => {
    expect(segmentStatusLabel("weird_new_state")).toBe("weird_new_state");
    expect(segmentStatusLabel(null)).toBe("未知");
  });

  it("已等待时长要人话（真实一段约 70 秒）", () => {
    expect(formatElapsed(0)).toBe("0 秒");
    expect(formatElapsed(72)).toBe("1 分 12 秒");
    expect(formatElapsed(120)).toBe("2 分");
  });
});