import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  createProject,
  getProject,
  listProjects,
} from "../../shared/api/projectApi";
import { listAssets } from "../../shared/api/assetApi";
import { InputWorkspace } from "./InputWorkspace";

vi.mock("../../shared/api/projectApi", () => ({
  createProject: vi.fn(),
  getProject: vi.fn(),
  listProjects: vi.fn(),
}));
vi.mock("../../shared/api/assetApi", () => ({
  listAssets: vi.fn(),
  presignAsset: vi.fn(),
  completeAsset: vi.fn(),
}));
vi.mock("./validation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./validation")>();
  return {
    ...actual,
    inspectImageFile: vi.fn(),
  };
});

const mockedCreateProject = vi.mocked(createProject);
const mockedGetProject = vi.mocked(getProject);
const mockedListProjects = vi.mocked(listProjects);
const mockedListAssets = vi.mocked(listAssets);

const project = {
  project_id: "prj_created",
  product_name: "榨汁杯",
  product_note: "白色杯身",
  status: "draft" as const,
  created_at: "2026-09-17T00:00:00Z",
  updated_at: "2026-09-17T00:00:00Z",
};

describe("InputWorkspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    mockedListProjects.mockResolvedValue([]);
    mockedGetProject.mockResolvedValue(project);
    mockedListAssets.mockResolvedValue([]);
  });

  it("renders the workspace and four-step progress", async () => {
    render(<InputWorkspace />);
    expect(screen.getByText("创建新的商品项目")).toBeInTheDocument();
    expect(screen.getByText("素材输入")).toBeInTheDocument();
    expect(screen.getByText("视频与成片")).toBeInTheDocument();
    await waitFor(() => expect(mockedListProjects).toHaveBeenCalled());
  });

  it("requires a product name", async () => {
    render(<InputWorkspace />);
    await userEvent.click(screen.getByRole("button", { name: "创建项目" }));
    expect(await screen.findByText("请填写商品名称")).toBeInTheDocument();
  });

  it("creates a project and keeps it in the project rail", async () => {
    mockedCreateProject.mockResolvedValue(project);
    render(<InputWorkspace />);

    await userEvent.type(screen.getByLabelText("商品名称 必填"), "榨汁杯");
    await userEvent.type(screen.getByLabelText(/补充说明/), "白色杯身");
    await userEvent.click(screen.getByRole("button", { name: "创建项目" }));

    await waitFor(() => {
      expect(mockedCreateProject).toHaveBeenCalledWith({
        productName: "榨汁杯",
        productNote: "白色杯身",
      });
    });
    expect(await screen.findByText("商品图片")).toBeInTheDocument();
    expect(screen.getByText("商品名称")).toBeInTheDocument();
    expect(screen.getAllByText("榨汁杯").length).toBeGreaterThan(0);
    expect(screen.getByText("白色杯身")).toBeInTheDocument();
    expect(screen.getAllByText("prj_created").length).toBeGreaterThan(0);

    await userEvent.click(screen.getByRole("button", { name: "复制" }));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("prj_created");
    expect(await screen.findByText("已复制")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /新建项目/ }));
    expect(screen.getByText("创建新的商品项目")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /榨汁杯/ })).toBeInTheDocument();
  });
});
