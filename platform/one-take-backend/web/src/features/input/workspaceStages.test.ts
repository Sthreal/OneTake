import { describe, expect, it } from "vitest";

import { deriveWorkspaceStage } from "./workspaceStages";

const base = {
  hasProject: true,
  readyAssetCount: 0,
  pipelineStatus: null,
  currentStep: 1,
  recognitionStatus: null,
  hasMainImage: false,
  scriptStatus: null,
  hasVoice: false,
  hasSubtitle: false,
  hasContentPlan: false,
  hasVideoPlan: false,
};

describe("deriveWorkspaceStage", () => {
  it("starts without a project on project and assets", () => {
    expect(deriveWorkspaceStage({ ...base, hasProject: false })).toBe(1);
  });

  it("unlocks recognition after an asset is ready", () => {
    expect(deriveWorkspaceStage({ ...base, readyAssetCount: 1 })).toBe(2);
  });

  it("unlocks main image and copy after recognition is confirmed", () => {
    expect(deriveWorkspaceStage({ ...base, recognitionStatus: "confirmed" })).toBe(3);
  });

  it("puts voice and subtitles in stage four after the script is confirmed", () => {
    expect(deriveWorkspaceStage({ ...base, currentStep: 4, scriptStatus: "confirmed" })).toBe(4);
  });

  it("keeps content plan in stage four", () => {
    expect(deriveWorkspaceStage({ ...base, currentStep: 4, hasContentPlan: true })).toBe(4);
  });

  it("moves video plan and completed output to stage five", () => {
    expect(deriveWorkspaceStage({ ...base, currentStep: 4, hasVideoPlan: true })).toBe(5);
    expect(deriveWorkspaceStage({ ...base, currentStep: 4, pipelineStatus: "video_ready" })).toBe(5);
    expect(deriveWorkspaceStage({ ...base, currentStep: 4, pipelineStatus: "completed" })).toBe(5);
  });
});
