const MINICLAW_API_PREFIX = "/miniclaw-api";

export class MiniClawApiError extends Error {
  status: number;
  code?: string;
  body?: unknown;

  constructor(
    message: string,
    options: { status: number; code?: string; body?: unknown },
  ) {
    super(message);
    this.name = "MiniClawApiError";
    this.status = options.status;
    this.code = options.code;
    this.body = options.body;
  }
}

function errorMessage(body: unknown, status: number): string {
  if (body && typeof body === "object") {
    const record = body as Record<string, unknown>;
    if (typeof record.error === "string" && record.error.trim()) {
      return record.error;
    }
    if (typeof record.message === "string" && record.message.trim()) {
      return record.message;
    }
  }
  return `One Take 产品后端请求失败（${status}）`;
}

export async function miniclawRequest<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  if (/^https?:\/\//i.test(path)) {
    throw new Error("One Take 产品后端请求必须使用同源相对路径");
  }

  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const isFormData = init?.body instanceof FormData;
  const response = await fetch(`${MINICLAW_API_PREFIX}${normalizedPath}`, {
    ...init,
    credentials: "include",
    headers: isFormData
      ? init?.headers
      : {
          "Content-Type": "application/json",
          ...(init?.headers ?? {}),
        },
  });

  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const record =
      body && typeof body === "object"
        ? (body as Record<string, unknown>)
        : null;
    throw new MiniClawApiError(errorMessage(body, response.status), {
      status: response.status,
      code: typeof record?.code === "string" ? record.code : undefined,
      body,
    });
  }

  return body as T;
}

export interface MiniClawAuthStatus {
  initialized: boolean;
}

export interface MiniClawSetupStatus {
  needsSetup: boolean;
  claudeConfigured: boolean;
  feishuConfigured: boolean;
  providerSetupSkipped: boolean;
}

export interface MiniClawUser {
  id: string;
  username: string;
  display_name: string;
  role: "admin" | "member";
  status: string;
  permissions: string[];
  must_change_password: boolean;
  avatar_url: string | null;
  ai_name: string | null;
  ai_avatar_url: string | null;
}

export interface MiniClawAuthSession {
  user: MiniClawUser;
  setupStatus?: MiniClawSetupStatus;
}

export interface MiniClawWorkspace {
  name: string;
  folder: string;
  added_at: string;
  is_home?: boolean;
  is_my_home?: boolean;
  editable?: boolean;
  execution_mode?: "container" | "host";
  interaction_mode?: "assistant" | "proactive";
  lastMessage?: string;
  lastMessageTime?: string;
}

export interface MiniClawWorkspaceList {
  groups: Record<string, MiniClawWorkspace>;
  admin_host_only_mode?: boolean;
}

export interface MiniClawWorkspaceExternalRef {
  namespace: string;
  external_id: string;
  owner_user_id: string;
  workspace_jid: string;
  created_at: string;
  updated_at: string;
}

export interface MiniClawWorkspaceCreateResponse {
  success: true;
  jid: string;
  group: MiniClawWorkspace;
}

export interface MiniClawSession {
  id: string;
  name: string;
  status: string;
  kind: string;
  chat_jid: string;
  is_main?: boolean;
  created_at?: string;
  last_active_at?: string | null;
}

export interface MiniClawMessage {
  id: string;
  chat_jid: string;
  sender: string;
  sender_name: string;
  content: string;
  timestamp: string;
  is_from_me: boolean;
}

export interface MiniClawMessagePage {
  messages: MiniClawMessage[];
  hasMore?: boolean;
}

export interface MiniClawSendMessageResponse {
  success: true;
  messageId: string;
  timestamp: string;
  disposition: "started" | "queued" | "steered";
  runId?: string;
}

export function getMiniClawAuthStatus(): Promise<MiniClawAuthStatus> {
  return miniclawRequest<MiniClawAuthStatus>("/auth/status");
}

export function getMiniClawCurrentUser(): Promise<MiniClawAuthSession> {
  return miniclawRequest<MiniClawAuthSession>("/auth/me");
}

export function loginMiniClaw(
  username: string,
  password: string,
): Promise<MiniClawAuthSession> {
  return miniclawRequest<MiniClawAuthSession>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export function setupMiniClaw(
  username: string,
  password: string,
): Promise<MiniClawAuthSession> {
  return miniclawRequest<MiniClawAuthSession>("/auth/setup", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export async function logoutMiniClaw(): Promise<void> {
  await miniclawRequest<{ success: true }>("/auth/logout", {
    method: "POST",
  });
}

export function listMiniClawWorkspaces(): Promise<MiniClawWorkspaceList> {
  return miniclawRequest<MiniClawWorkspaceList>("/groups");
}

export function listMiniClawSessions(
  workspaceJid: string,
): Promise<{ sessions: MiniClawSession[] }> {
  return miniclawRequest<{ sessions: MiniClawSession[] }>(
    `/groups/${encodeURIComponent(workspaceJid)}/sessions`,
  );
}

export function listMiniClawMessages(
  workspaceJid: string,
  options: { before?: string; after?: string; limit?: number } = {},
): Promise<MiniClawMessagePage> {
  const params = new URLSearchParams();
  if (options.before) params.set("before", options.before);
  if (options.after) params.set("after", options.after);
  params.set("limit", String(options.limit ?? 50));
  return miniclawRequest<MiniClawMessagePage>(
    `/groups/${encodeURIComponent(workspaceJid)}/messages?${params.toString()}`,
  );
}

export function sendMiniClawMessage(
  workspaceJid: string,
  content: string,
): Promise<MiniClawSendMessageResponse> {
  return miniclawRequest<MiniClawSendMessageResponse>("/messages", {
    method: "POST",
    body: JSON.stringify({
      chatJid: workspaceJid,
      content,
      followUpBehavior: "queue",
    }),
  });
}

export function createMiniClawWorkspace(input: {
  name: string;
  executionMode?: "container" | "host";
  interactionMode?: "assistant" | "proactive";
}): Promise<MiniClawWorkspaceCreateResponse> {
  return miniclawRequest<MiniClawWorkspaceCreateResponse>("/groups", {
    method: "POST",
    body: JSON.stringify({
      name: input.name,
      ...(input.executionMode ? { execution_mode: input.executionMode } : {}),
      interaction_mode: input.interactionMode ?? "assistant",
    }),
  });
}

export function getMiniClawWorkspaceExternalRef(
  namespace: string,
  externalId: string,
): Promise<{ external_ref: MiniClawWorkspaceExternalRef }> {
  return miniclawRequest<{ external_ref: MiniClawWorkspaceExternalRef }>(
    `/workspaces/external-refs/${encodeURIComponent(namespace)}/${encodeURIComponent(externalId)}`,
  );
}

export function bindMiniClawWorkspaceExternalRef(
  namespace: string,
  externalId: string,
  workspaceJid: string,
): Promise<{ external_ref: MiniClawWorkspaceExternalRef }> {
  return miniclawRequest<{ external_ref: MiniClawWorkspaceExternalRef }>(
    `/workspaces/external-refs/${encodeURIComponent(namespace)}/${encodeURIComponent(externalId)}`,
    {
      method: "PUT",
      body: JSON.stringify({ workspace_jid: workspaceJid }),
    },
  );
}
