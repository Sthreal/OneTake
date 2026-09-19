import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ContentQualityPanel } from "./ContentQualityPanel";

describe("ContentQualityPanel", () => {
  it("renders score and failed checks", () => {
    render(<ContentQualityPanel isLoading={false} error={null} report={{ report_id: "qar_1", project_id: "prj_1", plan_id: "cpl_1", video_plan_id: "vid_1", status: "failed", score: 70, passed: false, checks: [{ check_id: "product_layer", label: "商品图层", passed: false, weight: 20, message: "商品图层缺失", critical: true }], critical_failures: ["product_layer"], provider: "rules", model: "rules-v1", created_at: "2026-09-19T00:00:00Z", rule_score: 70, semantic_score: null, semantic_checks: [], semantic_issues: [] }} />);
    expect(screen.getByText("70")).toBeInTheDocument();
    expect(screen.getByText("商品图层")).toBeInTheDocument();
    expect(screen.getByText("质检失败")).toBeInTheDocument();
  });
});
