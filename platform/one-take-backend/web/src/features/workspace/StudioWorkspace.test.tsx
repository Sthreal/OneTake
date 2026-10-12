import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { listProjects } from "../../shared/api/projectApi";
import { StudioWorkspace } from "./StudioWorkspace";

vi.mock("../../shared/api/projectApi", () => ({
  createProject: vi.fn(),
  getProject: vi.fn(),
  listProjects: vi.fn(),
  updateProject: vi.fn(),
}));

const mockedListProjects = vi.mocked(listProjects);

describe("StudioWorkspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    mockedListProjects.mockResolvedValue([]);
  });

  it("renders the five-stage production shell and project creation form", async () => {
    const { container } = render(<StudioWorkspace />);

    expect(screen.getAllByText("项目与素材").length).toBeGreaterThan(0);
    expect(screen.getAllByText("商品识别").length).toBeGreaterThan(0);
    expect(screen.getAllByText("主图与文案").length).toBeGreaterThan(0);
    expect(screen.getByText("声音字幕与分镜")).toBeInTheDocument();
    expect(screen.getByText("视频与成片")).toBeInTheDocument();
    expect(screen.getByText("商品信息")).toBeInTheDocument();
    expect(container.querySelector(".workspace-content-scroll")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /商品识别/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /视频与成片/ })).toBeDisabled();

    await waitFor(() => expect(mockedListProjects).toHaveBeenCalled());
  });
});

