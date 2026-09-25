import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

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

function sessionWith(
  messages: Array<Record<string, unknown>>,
  runStatus: "idle" | "running" = "running",
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
    sendMessage: vi.fn(),
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
        session={sessionWith(
          [
            {
              id: "user-1",
            chat_jid: "web:timer",
            sender: "user",
            sender_name: "我",
            content: "生成方案",
            timestamp: "2026-09-26T00:00:00.000Z",
            is_from_me: false,
          },
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
          {
            id: "user-1",
            chat_jid: "web:timer",
            sender: "user",
            sender_name: "我",
            content: "生成方案",
            timestamp: "2026-09-26T00:00:00.000Z",
            is_from_me: false,
          },
        ])}
      />,
    );

    expect(screen.getByText("One Take 助手正在思考…")).toBeInTheDocument();

    rerender(
      <AgentConversation
        project={project}
        session={sessionWith(
          [
          {
            id: "user-1",
            chat_jid: "web:timer",
            sender: "user",
            sender_name: "我",
            content: "生成方案",
            timestamp: "2026-09-26T00:00:00.000Z",
            is_from_me: false,
          },
          {
            id: "assistant-1",
            chat_jid: "web:timer",
            sender: "miniclaw-agent",
            sender_name: "One Take 助手",
            content: "方案内容",
            timestamp: "2026-09-26T00:00:02.000Z",
            is_from_me: true,
          },
        ], "idle")}
      />,
    );

    expect(screen.queryByText("One Take 助手正在思考…")).not.toBeInTheDocument();
  });
});
