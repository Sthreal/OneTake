import { describe, expect, it } from "vitest";

import { buildMiniClawWebSocketUrl } from "./miniclawWs";

describe("miniclawWs", () => {
  it("builds a same-origin WebSocket URL for local development", () => {
    expect(buildMiniClawWebSocketUrl("http://localhost:5173")).toBe(
      "ws://localhost:5173/miniclaw-ws",
    );
  });

  it("uses secure WebSockets for HTTPS origins", () => {
    expect(buildMiniClawWebSocketUrl("https://onetake.example.com")).toBe(
      "wss://onetake.example.com/miniclaw-ws",
    );
  });
});