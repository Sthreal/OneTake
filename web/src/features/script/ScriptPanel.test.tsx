import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ScriptPanel } from "./ScriptPanel";
import type { ScriptState } from "./types";

const readyState: ScriptState = {
  version: {
    version_id: "scr_test",
    project_id: "prj_test",
    version_number: 1,
    status: "ready",
    provider: "mock-qwen-vl-plus",
    model: "qwen-vl-plus",
    facts: {
      product_name: "便携榨汁杯",
      product_note: "白色杯身",
      pain_point: "清洗麻烦",
      selling_points: ["杯身可拆卸", "适合随身携带"],
      usage_scenario: "通勤和办公室",
      offer: null,
    },
    hook: "还在为清洗麻烦烦恼吗？这款便携榨汁杯值得看看。",
    pain_point: "针对清洗麻烦，可以重点了解它的实际表现。",
    selling_points: ["杯身可拆卸。", "适合随身携带。"],
    usage_scenario: "在通勤和办公室时，可以自然使用。",
    offer: null,
    cta: "想确认这些特点，现在就进一步看看。",
    full_text: "还在为清洗麻烦烦恼吗？这款便携榨汁杯值得看看。针对清洗麻烦，可以重点了解它的实际表现。杯身可拆卸。适合随身携带。在通勤和办公室时，可以自然使用。想确认这些特点，现在就进一步看看。",
    character_count: 97,
    estimated_duration_seconds: 19.4,
    error_code: null,
    created_at: "2026-09-18T00:00:00Z",
    updated_at: "2026-09-18T00:01:00Z",
    completed_at: "2026-09-18T00:01:00Z",
    confirmed_at: null,
  },
};

describe("ScriptPanel", () => {
  it("submits confirmed facts for generation", async () => {
    const onStart = vi.fn();
    render(
      <ScriptPanel state={{ version: null }} canStart isStarting={false} isSaving={false} isConfirming={false} error={null} onStart={onStart} onSave={vi.fn()} onConfirm={vi.fn()} />,
    );
    await userEvent.type(screen.getByLabelText(/商品痛点/), "清洗麻烦");
    await userEvent.type(screen.getByLabelText(/已确认卖点/), "杯身可拆卸");
    await userEvent.type(screen.getByLabelText(/使用场景/), "通勤和办公室");
    await userEvent.click(screen.getByRole("button", { name: "生成文案" }));
    expect(onStart).toHaveBeenCalledWith({
      painPoint: "清洗麻烦",
      sellingPoints: ["杯身可拆卸"],
      usageScenario: "通勤和办公室",
      offer: null,
    });
  });

  it("saves edits and confirms generated copy", async () => {
    const onSave = vi.fn();
    const onConfirm = vi.fn();
    render(
      <ScriptPanel state={readyState} canStart isStarting={false} isSaving={false} isConfirming={false} error={null} onStart={vi.fn()} onSave={onSave} onConfirm={onConfirm} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "确认文案" }));
    expect(onConfirm).toHaveBeenCalled();

    const cta = screen.getByLabelText("CTA");
    await userEvent.clear(cta);
    await userEvent.type(cta, "想确认这些已经写明的特点，现在就来进一步看看。");
    await userEvent.click(screen.getByRole("button", { name: "保存修改" }));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ cta: "想确认这些已经写明的特点，现在就来进一步看看。" }));
  });
});

