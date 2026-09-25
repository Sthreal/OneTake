import { useEffect, useRef, useState } from "react";

import type { Project } from "../input/types";
import { useAgentSession } from "./useAgentSession";

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function AgentConversation({
  project,
  session,
}: {
  project: Project;
  session: ReturnType<typeof useAgentSession>;
}) {
  const [draft, setDraft] = useState("");
  const [thinkingStartedAt, setThinkingStartedAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const listRef = useRef<HTMLDivElement>(null);
  const waitingForReply = session.messages.at(-1)?.is_from_me === false;
  const showThinking = session.runStatus === "running" || waitingForReply;

  useEffect(() => {
    const list = listRef.current;
    if (list) list.scrollTop = list.scrollHeight;
  }, [session.messages, session.runStatus]);

  useEffect(() => {
    if (!showThinking) {
      setThinkingStartedAt(null);
      return;
    }

    const lastUserMessage = [...session.messages]
      .reverse()
      .find((message) => !message.is_from_me);
    const startedAt = lastUserMessage
      ? Date.parse(lastUserMessage.timestamp)
      : Date.now();

    setNow(Date.now());
    setThinkingStartedAt((current) => current ?? (startedAt || Date.now()));
  }, [session.messages, showThinking]);

  useEffect(() => {
    if (!showThinking) return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [showThinking]);

  const thinkingSeconds = thinkingStartedAt
    ? Math.max(0, Math.floor((now - thinkingStartedAt) / 1000))
    : 0;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const content = draft.trim();
    if (!content || showThinking) return;
    setDraft("");
    try {
      await session.sendMessage(content);
    } catch {
      setDraft(content);
    }
  }

  if (session.status === "loading") {
    return (
      <div className="agent-empty">
        <span className="spinner small" />
        正在准备项目工作区…
      </div>
    );
  }

  if (session.status === "error") {
    return (
      <div className="agent-empty">
        <strong>Agent 暂不可用</strong>
        <p>{session.error}</p>
        <button type="button" onClick={() => void session.reload()}>
          重试
        </button>
      </div>
    );
  }

  return (
    <div className="agent-conversation">
      <div className="agent-workspace-meta">
        <span>{session.workspace?.name || "One Take Agent"}</span>
        <span>{project.product_name}</span>
      </div>

      {showThinking && (
        <div className="agent-thinking-card" role="status" aria-live="polite">
          <span className="spinner small" />
          <div>
            <strong>One Take 助手正在思考…</strong>
            <p>
              已等待 {thinkingSeconds} 秒。生成完整方案通常需要十几秒到一分钟，
              请不要重复发送。
            </p>
          </div>
        </div>
      )}

      <div className="agent-message-list" ref={listRef}>
        {session.messages.length ? (
          session.messages.map((message) => {
            const fromUser = !message.is_from_me;
            return (
              <article
                className={`agent-message ${fromUser ? "is-user" : "is-agent"}`}
                key={message.id}
              >
                <div className="agent-message-meta">
                  <span>
                    {message.sender_name || (fromUser ? "我" : "Agent")}
                  </span>
                  <time>{formatTime(message.timestamp)}</time>
                </div>
                <p>{message.content}</p>
              </article>
            );
          })
        ) : (
          <div className="agent-empty compact">
            <strong>还没有对话</strong>
            <p>可以询问商品卖点、视频方案或生成质量检查。</p>
          </div>
        )}
      </div>

      {session.error && session.runStatus === "error" && (
        <div className="agent-inline-error">{session.error}</div>
      )}

      <form className="agent-composer" onSubmit={(event) => void submit(event)}>
        <textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="给当前项目的 Agent 发消息…"
          rows={3}
          disabled={showThinking}
        />
        <button
          type="submit"
          disabled={!draft.trim() || showThinking}
        >
          发送
        </button>
      </form>
    </div>
  );
}
