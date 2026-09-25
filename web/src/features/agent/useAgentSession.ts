import { useCallback, useEffect, useState } from "react";

import {
  MiniClawApiError,
  bindMiniClawWorkspaceExternalRef,
  createMiniClawWorkspace,
  getMiniClawWorkspaceExternalRef,
  listMiniClawMessages,
  listMiniClawWorkspaces,
  sendMiniClawMessage,
  type MiniClawMessage,
  type MiniClawWorkspace,
} from "../../shared/api/miniclawClient";
import { miniclawWs } from "../../shared/api/miniclawWs";
import type { Project } from "../input/types";

const ONETAKE_NAMESPACE = "onetake";
const MAX_WORKSPACE_NAME_LENGTH = 60;

export type AgentSessionStatus = "idle" | "loading" | "ready" | "error";
export type AgentRunStatus = "idle" | "running" | "error";

function sortMessages(messages: MiniClawMessage[]): MiniClawMessage[] {
  return [...messages].sort((a, b) => {
    const byTime = a.timestamp.localeCompare(b.timestamp);
    return byTime || a.id.localeCompare(b.id);
  });
}

function mergeMessages(
  current: MiniClawMessage[],
  incoming: MiniClawMessage[],
): MiniClawMessage[] {
  const byId = new Map(current.map((message) => [message.id, message]));
  for (const message of incoming) byId.set(message.id, message);
  return sortMessages(Array.from(byId.values()));
}

function workspaceName(project: Project): string {
  return `One Take · ${project.product_name}`.slice(
    0,
    MAX_WORKSPACE_NAME_LENGTH,
  );
}

async function resolveProjectWorkspace(project: Project): Promise<{
  jid: string;
  workspace: MiniClawWorkspace;
}> {
  const workspaceList = await listMiniClawWorkspaces();
  const workspaces = Object.entries(workspaceList.groups);
  const homeWorkspace = workspaces.find(
    ([, workspace]) => workspace.is_my_home,
  );
  const fallbackWorkspace = workspaces[0];

  try {
    const current = await getMiniClawWorkspaceExternalRef(
      ONETAKE_NAMESPACE,
      project.project_id,
    );
    const jid = current.external_ref.workspace_jid;
    return {
      jid,
      workspace: workspaceList.groups[jid] ?? {
        name: jid,
        folder: "",
        added_at: current.external_ref.created_at,
      },
    };
  } catch (error) {
    if (!(error instanceof MiniClawApiError) || error.status !== 404) {
      throw error;
    }
  }

  const created = await createMiniClawWorkspace({
    name: workspaceName(project),
    executionMode: homeWorkspace?.[1].execution_mode,
    interactionMode: "assistant",
  });

  try {
    await bindMiniClawWorkspaceExternalRef(
      ONETAKE_NAMESPACE,
      project.project_id,
      created.jid,
    );
  } catch (error) {
    if (error instanceof MiniClawApiError && error.status === 409) {
      const current = await getMiniClawWorkspaceExternalRef(
        ONETAKE_NAMESPACE,
        project.project_id,
      );
      return {
        jid: current.external_ref.workspace_jid,
        workspace:
          workspaceList.groups[current.external_ref.workspace_jid] ??
          fallbackWorkspace?.[1] ??
          created.group,
      };
    }
    throw error;
  }

  return {
    jid: created.jid,
    workspace:
      workspaceList.groups[created.jid] ??
      homeWorkspace?.[1] ??
      fallbackWorkspace?.[1] ??
      created.group,
  };
}

export function useAgentSession(
  project: Project | null,
  enabled: boolean,
  onUnauthorized?: () => void,
) {
  const [status, setStatus] = useState<AgentSessionStatus>("idle");
  const [runStatus, setRunStatus] = useState<AgentRunStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [workspace, setWorkspace] = useState<MiniClawWorkspace | null>(null);
  const [workspaceJid, setWorkspaceJid] = useState<string | null>(null);
  const [messages, setMessages] = useState<MiniClawMessage[]>([]);

  const loadMessages = useCallback(async (jid: string) => {
    const page = await listMiniClawMessages(jid);
    setMessages(sortMessages([...page.messages].reverse()));
  }, []);

  const load = useCallback(async () => {
    if (!project || !enabled) {
      setStatus("idle");
      setWorkspace(null);
      setWorkspaceJid(null);
      setMessages([]);
      setError(null);
      return;
    }

    setStatus("loading");
    setError(null);
    try {
      const resolved = await resolveProjectWorkspace(project);
      setWorkspace(resolved.workspace);
      setWorkspaceJid(resolved.jid);
      await loadMessages(resolved.jid);
      setStatus("ready");
    } catch (nextError) {
      if (nextError instanceof MiniClawApiError && nextError.status === 401) {
        onUnauthorized?.();
      }
      setStatus("error");
      setError(
        nextError instanceof Error ? nextError.message : "Agent 会话加载失败",
      );
    }
  }, [enabled, loadMessages, onUnauthorized, project]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!enabled || !workspaceJid) return;
    miniclawWs.connect();

    const unsubscribeMessage = miniclawWs.on<{
      chatJid?: string;
      message?: MiniClawMessage;
    }>("new_message", (event) => {
      if (event.chatJid !== workspaceJid || !event.message) return;
      setMessages((current) => mergeMessages(current, [event.message!]));
      setRunStatus("idle");
      void loadMessages(workspaceJid).catch(() => undefined);
    });

    const unsubscribeStream = miniclawWs.on<{ chatJid?: string }>(
      "stream_event",
      (event) => {
        if (event.chatJid === workspaceJid) setRunStatus("running");
      },
    );

    const unsubscribeFinished = miniclawWs.on<{ chatJid?: string }>(
      "run_finished",
      (event) => {
        if (event.chatJid !== workspaceJid) return;
        setRunStatus("idle");
        void loadMessages(workspaceJid).catch(() => undefined);
      },
    );

    const unsubscribeError = miniclawWs.on<{
      chatJid?: string;
      error?: string;
    }>("ws_error", (event) => {
      if (event.chatJid && event.chatJid !== workspaceJid) return;
      setRunStatus("error");
      setError(event.error || "Agent 运行失败");
    });

    return () => {
      unsubscribeMessage();
      unsubscribeStream();
      unsubscribeFinished();
      unsubscribeError();
    };
  }, [enabled, loadMessages, workspaceJid]);

  const sendMessage = useCallback(
    async (content: string) => {
      if (!workspaceJid) return;
      const trimmed = content.trim();
      if (!trimmed) return;

      setRunStatus("running");
      setError(null);
      try {
        await sendMiniClawMessage(workspaceJid, trimmed);
        await loadMessages(workspaceJid);
      } catch (nextError) {
        if (nextError instanceof MiniClawApiError && nextError.status === 401) {
          onUnauthorized?.();
        }
        setRunStatus("error");
        setError(
          nextError instanceof Error ? nextError.message : "消息发送失败",
        );
        throw nextError;
      }
    },
    [loadMessages, onUnauthorized, workspaceJid],
  );

  return {
    status,
    runStatus,
    error,
    workspace,
    messages,
    sendMessage,
    reload: load,
  };
}
