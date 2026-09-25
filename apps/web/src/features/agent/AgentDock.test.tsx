import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AgentDock } from "./AgentDock";

vi.mock("../../shared/api/miniclawClient", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("../../shared/api/miniclawClient")>();
  return {
    ...actual,
    getMiniClawAuthStatus: vi.fn(),
    getMiniClawCurrentUser: vi.fn(),
    listMiniClawWorkspaces: vi.fn(),
    getMiniClawWorkspaceExternalRef: vi.fn(),
    listMiniClawMessages: vi.fn(),
    createMiniClawWorkspace: vi.fn(),
    bindMiniClawWorkspaceExternalRef: vi.fn(),
    sendMiniClawMessage: vi.fn(),
  };
});

vi.mock("../../shared/api/miniclawWs", () => ({
  miniclawWs: {
    connect: vi.fn(),
    on: vi.fn(() => vi.fn()),
  },
}));

import {
  MiniClawApiError,
  bindMiniClawWorkspaceExternalRef,
  createMiniClawWorkspace,
  getMiniClawAuthStatus,
  getMiniClawCurrentUser,
  getMiniClawWorkspaceExternalRef,
  listMiniClawMessages,
  listMiniClawWorkspaces,
  sendMiniClawMessage,
} from "../../shared/api/miniclawClient";

const project = {
  project_id: "prj_agent_test",
  product_name: "鲜榨果汁杯",
  product_note: null,
  status: "draft" as const,
  created_at: "2026-09-25T00:00:00.000Z",
  updated_at: "2026-09-25T00:00:00.000Z",
};

function authenticatedMocks() {
  vi.mocked(getMiniClawAuthStatus).mockResolvedValue({ initialized: true });
  vi.mocked(getMiniClawCurrentUser).mockResolvedValue({
    user: {
      id: "user-1",
      username: "admin",
      display_name: "Admin",
      role: "admin",
      status: "active",
      permissions: [],
      must_change_password: false,
      avatar_url: null,
      ai_name: null,
      ai_avatar_url: null,
    },
  });
  vi.mocked(listMiniClawWorkspaces).mockResolvedValue({
    groups: {
      "web:project-workspace": {
        name: "One Take · 鲜榨果汁杯",
        folder: "project-workspace",
        added_at: "2026-09-25T00:00:00.000Z",
        is_home: false,
        is_my_home: true,
        execution_mode: "host",
      },
    },
  });
  vi.mocked(getMiniClawWorkspaceExternalRef).mockResolvedValue({
    external_ref: {
      namespace: "onetake",
      external_id: project.project_id,
      owner_user_id: "user-1",
      workspace_jid: "web:project-workspace",
      created_at: "2026-09-25T00:00:00.000Z",
      updated_at: "2026-09-25T00:00:00.000Z",
    },
  });
  vi.mocked(listMiniClawMessages).mockResolvedValue({ messages: [] });
  vi.mocked(sendMiniClawMessage).mockResolvedValue({
    success: true,
    messageId: "message-1",
    timestamp: "2026-09-25T00:00:01.000Z",
    disposition: "started",
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("AgentDock", () => {
  it("does not mount or call MiniClaw when the feature is disabled", () => {
    vi.stubEnv("VITE_MINICLAW_ENABLED", "false");
    render(<AgentDock project={project} />);

    expect(screen.queryByText("MiniClaw 助手")).not.toBeInTheDocument();
    expect(getMiniClawAuthStatus).not.toHaveBeenCalled();
  });
  it("loads the project workspace after login", async () => {
    authenticatedMocks();
    const user = userEvent.setup();
    render(<AgentDock project={project} />);

    await user.click(screen.getByRole("button", { name: "展开" }));
    expect(await screen.findByText("还没有对话")).toBeInTheDocument();
    expect(getMiniClawWorkspaceExternalRef).toHaveBeenCalledWith(
      "onetake",
      project.project_id,
    );
  });

  it("creates and binds a workspace for an unmapped project", async () => {
    authenticatedMocks();
    vi.mocked(getMiniClawWorkspaceExternalRef).mockRejectedValue(
      new MiniClawApiError("not found", { status: 404 }),
    );
    vi.mocked(createMiniClawWorkspace).mockResolvedValue({
      success: true,
      jid: "web:new-project-workspace",
      group: {
        name: "One Take · 鲜榨果汁杯",
        folder: "new-project-workspace",
        added_at: "2026-09-25T00:00:00.000Z",
        execution_mode: "host",
      },
    });
    vi.mocked(bindMiniClawWorkspaceExternalRef).mockResolvedValue({
      external_ref: {
        namespace: "onetake",
        external_id: project.project_id,
        owner_user_id: "user-1",
        workspace_jid: "web:new-project-workspace",
        created_at: "2026-09-25T00:00:00.000Z",
        updated_at: "2026-09-25T00:00:00.000Z",
      },
    });

    const user = userEvent.setup();
    render(<AgentDock project={project} />);
    await user.click(screen.getByRole("button", { name: "展开" }));
    await screen.findByText("还没有对话");

    expect(createMiniClawWorkspace).toHaveBeenCalledWith({
      name: "One Take · 鲜榨果汁杯",
      executionMode: "host",
      interactionMode: "assistant",
    });
    expect(bindMiniClawWorkspaceExternalRef).toHaveBeenCalledWith(
      "onetake",
      project.project_id,
      "web:new-project-workspace",
    );
  });

  it("offers setup when MiniClaw is not initialized", async () => {
    vi.mocked(getMiniClawAuthStatus).mockResolvedValue({
      initialized: false,
    });
    const user = userEvent.setup();
    render(<AgentDock project={project} />);

    await user.click(screen.getByRole("button", { name: "展开" }));
    expect(await screen.findByText("初始化并登录")).toBeInTheDocument();
  });

  it("sends a project-scoped message", async () => {
    authenticatedMocks();
    const user = userEvent.setup();
    render(<AgentDock project={project} />);

    await user.click(screen.getByRole("button", { name: "展开" }));
    const composer =
      await screen.findByPlaceholderText("给当前项目的 Agent 发消息…");
    await user.type(composer, "分析这个商品的卖点");
    await user.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => {
      expect(sendMiniClawMessage).toHaveBeenCalledWith(
        "web:project-workspace",
        "分析这个商品的卖点",
      );
    });
  });
});
