import { useCallback, useEffect, useState } from "react";

import {
  getMiniClawAuthStatus,
  getMiniClawCurrentUser,
  type MiniClawAuthSession,
} from "../../shared/api/miniclawClient";
import type { Project } from "../input/types";
import { AgentAuthPanel } from "./AgentAuthPanel";
import { AgentConversation } from "./AgentConversation";
import { useAgentSession } from "./useAgentSession";

type AuthView = "idle" | "checking" | "setup" | "login" | "ready" | "error";

function isMiniClawEnabled(): boolean {
  return import.meta.env.VITE_MINICLAW_ENABLED !== "false";
}

export function AgentDock({ project }: { project: Project | null }) {
  if (!isMiniClawEnabled()) return null;
  return <AgentDockContent project={project} />;
}

function AgentDockContent({ project }: { project: Project | null }) {
  const [expanded, setExpanded] = useState(false);
  const [authView, setAuthView] = useState<AuthView>("idle");
  const [authError, setAuthError] = useState<string | null>(null);

  const checkAuth = useCallback(async () => {
    setAuthView("checking");
    setAuthError(null);
    try {
      const status = await getMiniClawAuthStatus();
      if (!status.initialized) {
        setAuthView("setup");
        return;
      }
      try {
        await getMiniClawCurrentUser();
        setAuthView("ready");
      } catch (error) {
        if (
          error instanceof Error &&
          "status" in error &&
          Number((error as { status?: unknown }).status) === 401
        ) {
          setAuthView("login");
          return;
        }
        throw error;
      }
    } catch (error) {
      setAuthView("error");
      setAuthError(
        error instanceof Error ? error.message : "MiniClaw 连接失败",
      );
    }
  }, []);

  useEffect(() => {
    if (expanded && authView === "idle") void checkAuth();
  }, [authView, checkAuth, expanded]);

  const handleUnauthorized = useCallback(() => {
    setAuthView("login");
  }, []);

  const session = useAgentSession(
    project,
    expanded && !!project && authView === "ready",
    handleUnauthorized,
  );

  function handleAuthenticated(_session: MiniClawAuthSession) {
    setAuthView("ready");
  }

  return (
    <section className="inspector-card agent-dock">
      <div className="agent-dock-header">
        <div>
          <span>MiniClaw 助手</span>
          <small>{project ? project.product_name : "先选择项目"}</small>
        </div>
        <button
          type="button"
          className="agent-dock-toggle"
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? "收起" : "展开"}
        </button>
      </div>

      {!expanded && (
        <p className="agent-dock-hint">
          每个 One Take 项目使用独立的 MiniClaw 工作区。
        </p>
      )}

      {expanded && !project && (
        <div className="agent-empty compact">
          <strong>尚未选择项目</strong>
          <p>从左侧选择或创建项目后即可使用 Agent。</p>
        </div>
      )}

      {expanded && project && authView === "checking" && (
        <div className="agent-empty compact">
          <span className="spinner small" />
          正在连接 MiniClaw…
        </div>
      )}

      {expanded && project && authView === "setup" && (
        <AgentAuthPanel mode="setup" onAuthenticated={handleAuthenticated} />
      )}

      {expanded && project && authView === "login" && (
        <AgentAuthPanel mode="login" onAuthenticated={handleAuthenticated} />
      )}

      {expanded && project && authView === "error" && (
        <div className="agent-empty compact">
          <strong>MiniClaw 不可用</strong>
          <p>{authError}</p>
          <button type="button" onClick={() => void checkAuth()}>
            重试
          </button>
        </div>
      )}

      {expanded && project && authView === "ready" && (
        <AgentConversation project={project} session={session} />
      )}
    </section>
  );
}
