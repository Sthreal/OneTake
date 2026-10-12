import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { WorkspaceStageNav } from "./WorkspaceStageNav";

describe("WorkspaceStageNav", () => {
  it("locks stages after the current stage", () => {
    render(<WorkspaceStageNav activeStage={2} currentStage={2} onSelect={vi.fn()} />);

    expect(screen.getByText("项目与素材")).toBeInTheDocument();
    expect(screen.getByText("商品识别")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /主图与文案/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /声音字幕与分镜/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /视频与成片/ })).toBeDisabled();
  });

  it("allows navigation to completed stages", async () => {
    const onSelect = vi.fn();
    render(<WorkspaceStageNav activeStage={3} currentStage={3} onSelect={onSelect} />);

    await userEvent.click(screen.getByRole("button", { name: /商品识别/ }));
    expect(onSelect).toHaveBeenCalledWith(2);
  });
});
