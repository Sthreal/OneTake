import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FlowProgress } from "./FlowProgress";

describe("FlowProgress", () => {
  it("renders four steps with the first active", () => {
    const { container } = render(<FlowProgress currentStep={1} />);
    expect(screen.getByText("素材输入")).toBeInTheDocument();
    expect(screen.getByText("商品识别")).toBeInTheDocument();
    expect(screen.getByText("主图与文案")).toBeInTheDocument();
    expect(screen.getByText("视频与成片")).toBeInTheDocument();
    expect(container.querySelectorAll(".flow-segment")).toHaveLength(4);
    expect(container.querySelector(".flow-segment.is-active")?.textContent).toContain("素材输入");
  });
});
