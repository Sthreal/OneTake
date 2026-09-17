import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  createProject,
  getProject,
  listProjects,
  updateProject,
} from "../../shared/api/projectApi";
import { listAssets } from "../../shared/api/assetApi";
import { InputWorkspace } from "./InputWorkspace";

vi.mock("../../shared/api/projectApi", () => ({
  createProject: vi.fn(),
  getProject: vi.fn(),
  listProjects: vi.fn(),
  updateProject: vi.fn(),
}));
vi.mock("../../shared/api/recognitionApi", () => ({
  getPipeline: vi.fn().mockResolvedValue({
    pipeline_run_id: "run_test",
    project_id: "prj_created",
    status: "assets_ready",
    current_step: 1,
    state_version: 1,
    updated_at: "2026-09-17T00:00:00Z",
  }),
  getRecognition: vi.fn().mockResolvedValue({ run: null, candidates: [] }),
  requestRecognition: vi.fn().mockResolvedValue({ run: null, candidates: [] }),
  confirmRecognition: vi.fn().mockResolvedValue({ run: null, candidates: [] }),
}));
vi.mock("../../shared/api/mainImageApi", () => ({
  getMainImage: vi.fn().mockResolvedValue({ version: null }),
  requestMainImage: vi.fn().mockResolvedValue({ version: null }),
  confirmMainImage: vi.fn().mockResolvedValue({ version: null }),
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
const mockedUpdateProject = vi.mocked(updateProject);
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
    mockedUpdateProject.mockResolvedValue(project);
  });

  it("renders the workspace and four-step progress", async () => {
    render(<InputWorkspace />);
    expect(screen.queryByText("创建新的商品项目")).not.toBeInTheDocument();
    expect(screen.queryByText("INPUT WORKSPACE")).not.toBeInTheDocument();
    expect(screen.getByText("商品信息")).toBeInTheDocument();
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
    expect(screen.queryByText("创建新的商品项目")).not.toBeInTheDocument();
    expect(screen.getByText("商品信息")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /榨汁杯/ })).toBeInTheDocument();
  });

  it("edits project information after creation", async () => {
    mockedCreateProject.mockResolvedValue(project);
    mockedUpdateProject.mockResolvedValue({
      ...project,
      product_name: "榨汁杯 Pro",
      product_note: "新说明",
      updated_at: "2026-09-17T01:00:00Z",
    });
    render(<InputWorkspace />);
    await userEvent.type(screen.getByLabelText("商品名称 必填"), "榨汁杯");
    await userEvent.click(screen.getByRole("button", { name: "创建项目" }));

    await userEvent.click(await screen.findByRole("button", { name: "编辑" }));
    const nameInput = screen.getByLabelText("商品名称 必填");
    const noteInput = screen.getByLabelText(/补充说明/);
    await userEvent.clear(nameInput);
    await userEvent.type(nameInput, "榨汁杯 Pro");
    await userEvent.clear(noteInput);
    await userEvent.type(noteInput, "新说明");
    await userEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockedUpdateProject).toHaveBeenCalledWith("prj_created", {
        productName: "榨汁杯 Pro",
        productNote: "新说明",
      });
    });
    expect((await screen.findAllByText("榨汁杯 Pro")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("新说明").length).toBeGreaterThan(0);
  });
});
