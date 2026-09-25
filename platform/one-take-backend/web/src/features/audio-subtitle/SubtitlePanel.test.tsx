import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SubtitlePanel } from "./SubtitlePanel";

const state = { version: { subtitle_id: "sub_test", project_id: "prj_test", script_version_id: "scr_test", voice_run_id: "voi_test", status: "ready" as const, enabled: true, language: "zh" as const, segments: [{ index: 1, text: "第一句话。", start: 0, end: 2 }, { index: 2, text: "第二句话。", start: 2, end: 4 }], srt_url: "http://localhost/srt", error_code: null, created_at: "2026-09-18T00:00:00Z", updated_at: "2026-09-18T00:00:01Z", completed_at: "2026-09-18T00:00:01Z", confirmed_at: null } };

describe("SubtitlePanel", () => {
  it("renders subtitle segments", () => {
    render(<SubtitlePanel state={state} canStart isSaving={false} isConfirming={false} error={null} onSave={vi.fn()} onConfirm={vi.fn()} />);
    expect(screen.getByDisplayValue("第一句话。")).toBeInTheDocument();
    expect(screen.getByText("下载 SRT")).toBeInTheDocument();
  });

  it("saves edited subtitle", async () => {
    const onSave = vi.fn();
    render(<SubtitlePanel state={state} canStart isSaving={false} isConfirming={false} error={null} onSave={onSave} onConfirm={vi.fn()} />);
    const input = screen.getByDisplayValue("第一句话。");
    await userEvent.clear(input);
    await userEvent.type(input, "修改后的字幕。");
    await userEvent.click(screen.getByRole("button", { name: "保存并重新配音" }));
    expect(onSave).toHaveBeenCalledWith(expect.arrayContaining([expect.objectContaining({ text: "修改后的字幕。" })]));
  });
});
