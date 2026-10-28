import { describe, expect, it, vi } from "vitest";

import type { GenerateScriptInput, ScriptState, ScriptVersion } from "../../features/script/types";
import {
  ackAllowed,
  angleSwitchLocked,
  applyAllowed,
  editResetGate,
  gateHeadline,
  lengthFailureCopy,
  loadStudioScript,
  mergeReviewedVersion,
  orderedCandidates,
  paidVideoBlock,
  studioScriptInput,
} from "./scriptGate";

function version(partial: Partial<ScriptVersion> = {}): ScriptVersion {
  return {
    version_id: "scr_pain",
    project_id: "prj",
    version_number: 1,
    status: "ready",
    provider: "mock",
    model: "mock",
    facts: {
      product_name: "水杯",
      product_note: null,
      pain_point: "清洗麻烦",
      selling_points: ["杯身可拆卸"],
      usage_scenario: "通勤",
      offer: null,
    },
    hook: "还在为清洗麻烦烦恼？",
    pain_point: "重点看它的实际表现。",
    selling_points: ["杯身可拆卸。"],
    usage_scenario: "日常用起来很自然，顺手看看。",
    offer: null,
    cta: "想确认这些特点，现在就进一步看看。",
    full_text: "口播",
    character_count: 48,
    estimated_duration_seconds: 12,
    error_code: null,
    created_at: "2026-10-28T00:00:00Z",
    updated_at: "2026-10-28T00:00:00Z",
    completed_at: "2026-10-28T00:00:00Z",
    confirmed_at: null,
    angle: "pain_point",
    angle_label: "痛点种草",
    selected: true,
    generation_batch_id: "sbg_1",
    review_gate: { mode: "enforce", status: "pending", decision: null, length_ok: null, error_code: null },
    ...partial,
  };
}

const input: GenerateScriptInput = {
  painPoint: "清洗麻烦",
  sellingPoints: ["杯身可拆卸"],
  usageScenario: "通勤和办公室",
  offer: null,
};

describe("工作室审稿闸判断", () => {
  it("候选按痛点、场景、对比排列", () => {
    const scene = version({ version_id: "scr_scene", version_number: 3, angle: "scene", angle_label: "场景安利" });
    const comparison = version({ version_id: "scr_cmp", version_number: 2, angle: "comparison" });
    const pain = version({ version_number: 4 });
    const ordered = orderedCandidates({ version: scene, candidates: [scene, comparison, pain], selected_version_id: scene.version_id });
    expect(ordered.map((item) => item.angle)).toEqual(["pain_point", "scene", "comparison"]);
  });

  it("enforce 下只有 passed 才能进付费视频", () => {
    expect(paidVideoBlock(null).code).toBe("SCRIPT_REVIEW_REQUIRED");
    expect(paidVideoBlock(version()).blocked).toBe(true);
    expect(paidVideoBlock(version({ review_gate: { mode: "enforce", status: "reviewed", decision: null, length_ok: true, error_code: null } })).message).toContain("还没过闸");
    expect(paidVideoBlock(version({ review_gate: { mode: "enforce", status: "failed", decision: null, length_ok: false, error_code: "SCRIPT_REVIEW_LENGTH" } })).blocked).toBe(true);
    const passed = paidVideoBlock(version({ review_gate: { mode: "enforce", status: "passed", decision: "acked", length_ok: true, error_code: null } }));
    expect(passed.blocked).toBe(false);
    expect(paidVideoBlock(version({ review_gate: { mode: "off", status: "pending", decision: null, length_ok: null, error_code: null } })).blocked).toBe(false);
    expect(paidVideoBlock(version({ review_gate: { mode: "warn", status: "pending", decision: null, length_ok: null, error_code: null } })).blocked).toBe(false);
  });

  it("已审可以 apply 或 ack；等长失败只能 ack", () => {
    expect(applyAllowed({ gate_status: "pending", length_ok: null, error_code: null })).toBe(false);
    expect(ackAllowed({ gate_status: "pending" })).toBe(false);
    expect(applyAllowed({ gate_status: "reviewed", length_ok: true, error_code: null })).toBe(true);
    expect(ackAllowed({ gate_status: "reviewed" })).toBe(true);
    expect(applyAllowed({ gate_status: "failed", length_ok: false, error_code: "SCRIPT_REVIEW_LENGTH" })).toBe(false);
    expect(ackAllowed({ gate_status: "failed" })).toBe(true);
    expect(lengthFailureCopy({ gate_status: "failed", error_code: "SCRIPT_REVIEW_LENGTH", length_errors: ["hook"] })).toContain("hook");
    expect(applyAllowed({ gate_status: "passed", length_ok: true, error_code: null })).toBe(false);
  });

  it("过闸文案和手改清闸", () => {
    expect(gateHeadline({ mode: "enforce", status: "reviewed", decision: null, length_ok: true, error_code: null })).toBe("审稿闸：已审，还没过闸");
    expect(gateHeadline({ mode: "enforce", status: "passed", decision: "applied", length_ok: true, error_code: null })).toContain("已写入改写");
    expect(gateHeadline({ mode: "enforce", status: "failed", decision: null, length_ok: false, error_code: "SCRIPT_REVIEW_LENGTH" })).toContain("只能保留原稿");
    expect(editResetGate(
      { mode: "enforce", status: "passed", decision: "acked", length_ok: true, error_code: null },
      { mode: "enforce", status: "pending", decision: null, length_ok: null, error_code: null },
    )).toBe(true);
    expect(editResetGate(
      { mode: "enforce", status: "pending", decision: null, length_ok: null, error_code: null },
      { mode: "enforce", status: "pending", decision: null, length_ok: null, error_code: null },
    )).toBe(false);
  });

  it("已确认的一批不能再切角度", () => {
    const state: ScriptState = {
      version: version({ status: "confirmed" }),
      candidates: [version({ status: "confirmed" }), version({ version_id: "scr_scene", angle: "scene", status: "ready" })],
      selected_version_id: "scr_pain",
    };
    expect(angleSwitchLocked(state)).toBe(true);
  });

  it("准备步卖点写成 generate 的痛点、卖点和可选优惠", () => {
    expect(studioScriptInput(
      { product_name: "春季护肤精华液", product_note: "主图已就绪" },
      { points: ["texture", "sensitive"] },
    )).toEqual({
      painPoint: "轻薄不粘腻、一抹吸收",
      sellingPoints: ["突出材质与质感", "强调敏感肌友好"],
      usageScenario: "主图已就绪",
      offer: null,
    });
    expect(studioScriptInput({ product_name: "水杯", product_note: "" }, { points: ["promo"] }).offer).toBe("下单赠小样");
  });

  it("没有稿就 generate，排队中轮询到 ready，不再次 generate", async () => {
    const projectId = "prj_poll_gate";
    const queued = version({ status: "queued", hook: "" });
    const ready = version({ status: "ready" });
    let gets = 0;
    const api = {
      getScript: vi.fn(async (): Promise<ScriptState> => {
        gets += 1;
        if (gets === 1) return { version: null, candidates: [], selected_version_id: null };
        return { version: ready, candidates: [ready], selected_version_id: ready.version_id };
      }),
      generateScript: vi.fn(async (): Promise<ScriptState> => ({
        version: queued,
        candidates: [queued],
        selected_version_id: queued.version_id,
      })),
    };
    const state = await loadStudioScript(projectId, input, api, { sleep: async () => {}, maxPolls: 3 });
    expect(api.generateScript).toHaveBeenCalledTimes(1);
    expect(state.version?.status).toBe("ready");

    const again = await loadStudioScript(projectId, input, {
      getScript: async () => ({ version: ready, candidates: [ready], selected_version_id: ready.version_id }),
      generateScript: api.generateScript,
    }, { sleep: async () => {} });
    expect(api.generateScript).toHaveBeenCalledTimes(1);
    expect(again.version?.version_id).toBe(ready.version_id);
  });

  it("审稿结果写回当前角度，不丢掉另外两套", () => {
    const pain = version();
    const scene = version({ version_id: "scr_scene", angle: "scene", version_number: 2, selected: false });
    const passed = version({
      review_gate: { mode: "enforce", status: "passed", decision: "acked", length_ok: true, error_code: null },
    });
    const merged = mergeReviewedVersion(
      { version: pain, candidates: [pain, scene], selected_version_id: pain.version_id },
      passed,
    );
    expect(merged.version?.review_gate?.status).toBe("passed");
    expect(merged.candidates?.map((item) => item.version_id)).toEqual(["scr_pain", "scr_scene"]);
    expect(merged.candidates?.[1].angle).toBe("scene");
  });
});
