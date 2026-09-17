import { describe, expect, it } from "vitest";

import {
  formatBytes,
  validateFileBasics,
  validateImageMetadata,
} from "./validation";

describe("validation", () => {
  it("formats bytes", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
  });

  it("rejects unsupported files", () => {
    const file = new File(["x"], "image.gif", { type: "image/gif" });
    expect(validateFileBasics(file)).toBe("仅支持 JPG、PNG 和 WebP");
  });

  it("accepts valid dimensions", () => {
    expect(validateImageMetadata(800, 600)).toBeNull();
  });

  it("rejects invalid aspect ratio", () => {
    expect(validateImageMetadata(5000, 900)).toContain("比例");
  });
});