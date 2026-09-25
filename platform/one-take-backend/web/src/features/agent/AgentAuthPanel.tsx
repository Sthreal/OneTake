import { useState } from "react";

import {
  loginMiniClaw,
  setupMiniClaw,
  type MiniClawAuthSession,
} from "../../shared/api/miniclawClient";

export function AgentAuthPanel({
  mode,
  onAuthenticated,
}: {
  mode: "setup" | "login";
  onAuthenticated: (session: MiniClawAuthSession) => void;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!username.trim() || !password) {
      setError("请输入用户名和密码");
      return;
    }

    setBusy(true);
    setError(null);
    try {
      const session =
        mode === "setup"
          ? await setupMiniClaw(username.trim(), password)
          : await loginMiniClaw(username.trim(), password);
      setPassword("");
      onAuthenticated(session);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "登录失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="agent-auth-form" onSubmit={(event) => void submit(event)}>
      <p>
        {mode === "setup"
          ? "首次使用，请初始化 One Take 产品后端管理员账号。"
          : "登录 One Take 产品后端后即可使用当前项目的 Agent。"}
      </p>
      <label>
        <span>用户名</span>
        <input
          autoComplete="username"
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          disabled={busy}
        />
      </label>
      <label>
        <span>密码</span>
        <input
          type="password"
          autoComplete={mode === "setup" ? "new-password" : "current-password"}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          disabled={busy}
        />
      </label>
      {error && <div className="agent-inline-error">{error}</div>}
      <button type="submit" disabled={busy}>
        {busy ? "处理中…" : mode === "setup" ? "初始化并登录" : "登录"}
      </button>
    </form>
  );
}
