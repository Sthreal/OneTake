import { afterEach, describe, expect, it, vi } from "vitest";

import { applyScriptReview, reviewScriptGate, selectScript } from "./scriptApi";

const jsonResponse = (status: number, body: unknown) =>
  ({ ok: status < 300, status, json: async () => body }) as unknown as Response;

describe("文案选稿和审稿闸请求", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("select / review / apply 打到切片 B、C 的路径和请求体", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return jsonResponse(200, { data: { version: null, candidates: [], selected_version_id: null, gate_status: "reviewed" } });
    }));

    await selectScript("prj_1", "scr_scene");
    await reviewScriptGate("prj_1");
    await applyScriptReview("prj_1", "ack");
    await applyScriptReview("prj_1", "apply");

    expect(calls.map((call) => [call.url, call.init?.method, call.init?.body])).toEqual([
      ["/api/v1/projects/prj_1/script/select", "POST", JSON.stringify({ version_id: "scr_scene" })],
      ["/api/v1/projects/prj_1/script/review", "POST", undefined],
      ["/api/v1/projects/prj_1/script/review/apply", "POST", JSON.stringify({ action: "ack" })],
      ["/api/v1/projects/prj_1/script/review/apply", "POST", JSON.stringify({ action: "apply" })],
    ]);
  });
});
