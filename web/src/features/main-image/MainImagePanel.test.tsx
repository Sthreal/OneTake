import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { MainImagePanel } from "./MainImagePanel";
import type { MainImageState } from "./types";

const readyState: MainImageState = {
  version: {
    version_id: "miv_test",
    project_id: "prj_test",
    source_asset_id: "ast_test",
    status: "ready",
    png_url: "http://localhost:9000/png",
    jpg_url: "http://localhost:9000/jpg",
    png_width: 2000,
    png_height: 2000,
    jpg_width: 1000,
    jpg_height: 1000,
    jpg_size_bytes: 820000,
    product_ratio: 0.82,
    error_code: null,
    created_at: "2026-09-18T00:00:00Z",
    updated_at: "2026-09-18T00:01:00Z",
    completed_at: "2026-09-18T00:01:00Z",
    confirmed_at: null,
  },
};

describe("MainImagePanel", () => {
  it("renders ready previews and confirms the result", async () => {
    const onConfirm = vi.fn();
    render(
      <MainImagePanel
        state={readyState}
        canStart
        isStarting={false}
        isConfirming={false}
        error={null}
        onStart={vi.fn()}
        onConfirm={onConfirm}
      />,
    );
    expect(screen.getByAltText("透明背景主图预览")).toHaveAttribute("src", "http://localhost:9000/png");
    expect(screen.getByAltText("白底主图预览")).toHaveAttribute("src", "http://localhost:9000/jpg");
    expect(screen.getByText("商品占比 82%")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "确认主图" }));
    expect(onConfirm).toHaveBeenCalled();
  });

  it("disables generation before recognition is confirmed", () => {
    render(
      <MainImagePanel
        state={{ version: null }}
        canStart={false}
        isStarting={false}
        isConfirming={false}
        error={null}
        onStart={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "生成主图" })).toBeDisabled();
  });
});
