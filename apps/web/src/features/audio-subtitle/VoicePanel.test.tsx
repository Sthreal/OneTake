import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { VoicePanel } from "./VoicePanel";

describe("VoicePanel", () => {
  it("submits voice settings", async () => {
    const onStart = vi.fn();
    render(<VoicePanel state={{ run: null }} canStart isStarting={false} error={null} onStart={onStart} />);
    await userEvent.click(screen.getByRole("button", { name: "生成配音" }));
    expect(onStart).toHaveBeenCalledWith(expect.objectContaining({ enabled: true, subtitleEnabled: true, voiceId: "longxiaochun_v2", language: "zh", speed: 1 }));
  });

  it("renders generated audio", () => {
    render(
      <VoicePanel
        state={{ run: {
          run_id: "voi_test", project_id: "prj_test", script_version_id: "scr_test", status: "ready", enabled: true, subtitle_enabled: true,
          provider: "mock-cosyvoice-v2", model: "cosyvoice-v2", voice_id: "longxiaochun_v2", language: "zh", speed: 1,
          duration_seconds: 18.2, audio_url: "http://localhost/voice.wav", error_code: null,
          created_at: "2026-09-18T00:00:00Z", updated_at: "2026-09-18T00:00:01Z", completed_at: "2026-09-18T00:00:01Z", confirmed_at: null,
        } }}
        canStart
        isStarting={false}
        error={null}
        onStart={vi.fn()}
      />,
    );
    expect(screen.getAllByText("配音已生成").length).toBeGreaterThan(0);
    expect(screen.getByText(/18.2 秒/)).toBeInTheDocument();
  });
});
