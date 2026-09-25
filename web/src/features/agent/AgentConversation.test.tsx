import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { MiniClawMessage } from "../../shared/api/miniclawClient";
import type { Project } from "../input/types";
import { AgentConversation } from "./AgentConversation";
import type { useAgentSession } from "./useAgentSession";

const project: Project = {
  project_id: "prj_timer_test",
  product_name: "测试商品",
  product_note: null,
  status: "draft",
  created_at: "2026-09-26T00:00:00.000Z",
  updated_at: "2026-09-26T00:00:00.000Z",
};

function userMessage(
  id: string,
  timestamp: string,
  content = "生成方案",
): MiniClawMessage {
  return {
    id,
    chat_jid: "web:timer",
    sender: "user",
    sender_name: "我",
    content,
    timestamp,
    is_from_me: false,
  };
}

function agentMessage(id: string, timestamp: string): MiniClawMessage {
  return {
    id,
    chat_jid: "web:timer",
    sender: "miniclaw-agent",
    sender_name: "One Take 助手",
    content: "方案内容",
    timestamp,
    is_from_me: true,
  };
}

function sessionWith(
  messages: MiniClawMessage[],
  runStatus: "idle" | "running" = "running",
  sendMessage = vi.fn<(content: string) => Promise<void>>(),
) {
  return {
    status: "ready",
    runStatus,
    error: null,
    workspace: {
      name: "测试工作区",
      folder: "timer-test",
      added_at: "2026-09-26T00:00:00.000Z",
    },
    messages,
    sendMessage,
    reload: vi.fn(),
  } as unknown as ReturnType<typeof useAgentSession>;
}

afterEach(() => {
  vi.useRealTimers();
});

describe("AgentConversation waiting timer", () => {
  it("ticks every second while waiting", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-26T00:00:00.000Z"));

    render(
      <AgentConversation
        project={project}
        session={sessionWith([
          userMessage("user-1", "2026-09-26T00:00:00.000Z"),
        ])}
      />,
    );

    expect(screen.getByText("已等待 0 秒。", { exact: false })).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(2000);
    });

    expect(screen.getByText("已等待 2 秒。", { exact: false })).toBeInTheDocument();
  });

  it("disappears after an assistant reply arrives", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-26T00:00:00.000Z"));

    const { rerender } = render(
      <AgentConversation
        project={project}
        session={sessionWith([
          userMessage("user-1", "2026-09-26T00:00:00.000Z"),
        ])}
      />,
    );

    expect(screen.getByText("One Take 助手正在思考…")).toBeInTheDocument();

    rerender(
      <AgentConversation
        project={project}
        session={sessionWith(
          [
            userMessage("user-1", "2026-09-26T00:00:00.000Z"),
            agentMessage("assistant-1", "2026-09-26T00:00:02.000Z"),
          ],
          "idle",
        )}
      />,
    );

    expect(screen.queryByText("One Take 助手正在思考…")).not.toBeInTheDocument();
  });

  it("starts each new send at zero instead of continuing the previous timer", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-26T00:10:00.000Z"));

    const sendMessage = vi.fn<(content: string) => Promise<void>>(
      () => new Promise<void>(() => undefined),
    );
    const previousMessages = [
      userMessage("user-1", "2026-09-26T00:00:00.000Z"),
      agentMessage("assistant-1", "2026-09-26T00:00:05.000Z"),
    ];
    const idleSession = sessionWith(previousMessages, "idle", sendMessage);

    const { rerender } = render(
      <AgentConversation project={project} session={idleSession} />,
    );

    fireEvent.change(
      screen.getByPlaceholderText("给当前项目的 Agent 发消息…"),
      { target: { value: "第二轮问题" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    rerender(
      <AgentConversation
        project={project}
        session={{ ...idleSession, runStatus: "running" }}
      />,
    );

    expect(sendMessage).toHaveBeenCalledWith("第二轮问题");
    expect(screen.getByText("已等待 0 秒。", { exact: false })).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(2000);
    });

    expect(screen.getByText("已等待 2 秒。", { exact: false })).toBeInTheDocument();

    rerender(
      <AgentConversation
        project={project}
        session={sessionWith(
          [
            ...previousMessages,
            userMessage("user-2", "2026-09-26T00:10:00.000Z", "第二轮问题"),
            agentMessage("assistant-2", "2026-09-26T00:10:02.000Z"),
          ],
          "idle",
          sendMessage,
        )}
      />,
    );

    expect(screen.queryByText("One Take 助手正在思考…")).not.toBeInTheDocument();

    vi.setSystemTime(new Date("2026-09-26T00:20:00.000Z"));
    fireEvent.change(
      screen.getByPlaceholderText("给当前项目的 Agent 发消息…"),
      { target: { value: "第三轮问题" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    rerender(
      <AgentConversation
        project={project}
        session={{ ...idleSession, runStatus: "running" }}
      />,
    );

    expect(screen.getByText("已等待 0 秒。", { exact: false })).toBeInTheDocument();
  });
});
