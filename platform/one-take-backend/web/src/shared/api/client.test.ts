import { describe, expect, it, vi, afterEach } from "vitest";

import { ApiError, apiRequest, validationMessage } from "./client";

const jsonResponse = (status: number, body: unknown) =>
  ({ ok: status < 300, status, json: async () => body }) as unknown as Response;

describe("apiRequest 的错误文案（别让用户对着「请求失败（422）」猜）", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("我们自己的领域错误：原样透出 error.message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(422, { error: { code: "URL_NOT_ALLOWED", message: "不允许访问内网/保留地址（192.168.1.10）" } }),
      ),
    );
    await expect(apiRequest("/x", { method: "POST" })).rejects.toThrow("不允许访问内网/保留地址");
  });

  it("FastAPI 的参数校验错误（{detail:[…]}）：翻成可读的一行，而不是兜底文案", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(422, {
          detail: [{ type: "string_too_short", loc: ["body", "url"], msg: "String should have at least 1 character" }],
        }),
      ),
    );
    const error = await apiRequest("/x", { method: "POST" }).catch((err) => err as ApiError);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toContain("参数不合法（422）");
    expect((error as ApiError).message).toContain("url");
    expect((error as ApiError).message).not.toBe("请求失败（422）");
    expect((error as ApiError).status).toBe(422);
  });

  it("既没有 error.message 也没有 detail：保留兜底文案（不伪造原因）", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(500, {})));
    await expect(apiRequest("/x")).rejects.toThrow("请求失败（500）");
    expect(validationMessage(500, undefined)).toBeNull();
  });
});