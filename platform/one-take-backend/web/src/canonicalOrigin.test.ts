import { describe, expect, it, vi } from "vitest";

import { canonicalDevOriginRedirect, redirectLoopbackDevOrigin } from "./canonicalOrigin";

describe("开发地址统一到 localhost:5173", () => {
  it("127.0.0.1:5173 跳到 localhost，并保留 path、query、hash", () => {
    expect(canonicalDevOriginRedirect("http://127.0.0.1:5173/studio?view=prepare&project=prj_a#shot"))
      .toBe("http://localhost:5173/studio?view=prepare&project=prj_a#shot");
    expect(canonicalDevOriginRedirect("http://127.0.0.1:5173")).toBe("http://localhost:5173/");
  });

  it("已经是 localhost，或端口 / 协议不同，就不跳", () => {
    expect(canonicalDevOriginRedirect("http://localhost:5173/studio?view=brand")).toBeNull();
    expect(canonicalDevOriginRedirect("http://127.0.0.1:5174/studio")).toBeNull();
    expect(canonicalDevOriginRedirect("https://127.0.0.1:5173/studio")).toBeNull();
    expect(canonicalDevOriginRedirect("not a url")).toBeNull();
  });

  it("redirectLoopbackDevOrigin 只在需要时 replace", () => {
    const replace = vi.fn();
    expect(redirectLoopbackDevOrigin({
      href: "http://127.0.0.1:5173/a?b=1#c",
      replace,
    })).toBe(true);
    expect(replace).toHaveBeenCalledWith("http://localhost:5173/a?b=1#c");

    const stay = vi.fn();
    expect(redirectLoopbackDevOrigin({ href: "http://localhost:5173/a", replace: stay })).toBe(false);
    expect(stay).not.toHaveBeenCalled();
  });
});
