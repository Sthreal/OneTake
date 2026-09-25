import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ContentPlanPanel } from "./ContentPlanPanel";

const scenes = [{ scene_id: "scene_1", order: 1, purpose: "hook", script_excerpt: "第一句", start_seconds: 0, end_seconds: 2, shot_type: "product_motion", prompt: "原始镜头", overlay_product: true, product_position: "center", background_style: "clean", template_id: "clean", subtitle_segment_ids: [1], qa_rules: ["product_visible"] }];
const plan = { plan_id: "cpl_1", project_id: "prj_1", status: "ready" as const, provider: "rules", model: "rules-v1", selected_variant_index: 0, total_duration_seconds: 18, variants: [{ variant_id: "var_clean", name: "干净展示", style: "clean", scenes }, { variant_id: "var_story", name: "生活故事", style: "story", scenes: scenes.map((scene) => ({ ...scene, prompt: "故事镜头" })) }], error_code: null, created_at: "2026-09-19T00:00:00Z", updated_at: "2026-09-19T00:00:00Z", confirmed_at: null };

describe("ContentPlanPanel", () => {
  it("generates a plan when empty", async () => {
    const onGenerate = vi.fn();
    render(<ContentPlanPanel plan={null} canStart isGenerating={false} isSaving={false} isConfirming={false} error={null} onGenerate={onGenerate} onSave={vi.fn()} onConfirm={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "生成视频分镜" }));
    expect(onGenerate).toHaveBeenCalled();
  });

  it("switches variants and saves edited prompt", async () => {
    const onSave = vi.fn();
    render(<ContentPlanPanel plan={plan} canStart isGenerating={false} isSaving={false} isConfirming={false} error={null} onGenerate={vi.fn()} onSave={onSave} onConfirm={vi.fn()} />);
    await userEvent.click(screen.getByRole("tab", { name: /生活故事/ }));
    const input = screen.getByDisplayValue("故事镜头");
    await userEvent.clear(input);
    await userEvent.type(input, "新的镜头");
    await userEvent.click(screen.getByRole("button", { name: "保存分镜" }));
    expect(onSave).toHaveBeenCalledWith(1, expect.arrayContaining([expect.objectContaining({ prompt: "新的镜头" })]));
  });
});
