import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getMiniClawAuthStatus,
  loginMiniClaw,
  miniclawRequest,
} from "./miniclawClient";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("miniclawClient", () => {
  it("uses the One Take same-origin API bridge", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ initialized: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(getMiniClawAuthStatus()).resolves.toEqual({ initialized: true });
    expect(fetchMock).toHaveBeenCalledWith(
      "/miniclaw-api/auth/status",
      expect.objectContaining({
        credentials: "include",
        headers: { "Content-Type": "application/json" },
      }),
    );
  });

  it("sends login credentials to the MiniClaw backend", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
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
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await loginMiniClaw("admin", "secret");
    expect(fetchMock).toHaveBeenCalledWith(
      "/miniclaw-api/auth/login",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ username: "admin", password: "secret" }),
      }),
    );
  });

  it("maps MiniClaw errors without exposing a non-JSON response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: "Unauthorized", code: "AUTH" }), {
          status: 401,
        }),
      ),
    );

    await expect(miniclawRequest("/auth/me")).rejects.toMatchObject({
      name: "MiniClawApiError",
      message: "Unauthorized",
      status: 401,
      code: "AUTH",
    });
  });

  it("rejects cross-origin MiniClaw requests", async () => {
    await expect(miniclawRequest("https://example.com/api")).rejects.toThrow(
      "同源相对路径",
    );
  });
});