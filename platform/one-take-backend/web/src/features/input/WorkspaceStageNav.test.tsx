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

  it("keeps the current stage reachable after looking back", async () => {
    const onSelect = vi.fn();
    render(<WorkspaceStageNav activeStage={1} currentStage={5} onSelect={onSelect} />);

    // 回归点：回看更早的阶段后，当前阶段不能变成锁定禁用，否则用户点不回去
    const current = screen.getByRole("button", { name: /视频与成片/ });
    expect(current).not.toBeDisabled();
    await userEvent.click(current);
    expect(onSelect).toHaveBeenCalledWith(5);
  });
});
